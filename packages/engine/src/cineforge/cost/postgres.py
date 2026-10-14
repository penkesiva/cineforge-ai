"""Postgres BudgetService (tables budgets, cost_ledger, credit_balances, productions).

Concurrency: every mutation locks the affected budget rows with
``SELECT ... FOR UPDATE ORDER BY scope_key`` before touching the ledger, so
'production' is always locked before 'scene:<id>' (deterministic order, no
deadlocks) and all reservations for one production serialize across processes.
Ledger rows are locked only after the budget rows (same order everywhere).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

import psycopg

from cineforge.contracts.common import DEFAULT_CURRENCY, money, new_id
from cineforge.contracts.cost import (
    Budget,
    BudgetExceededError,
    CostEstimate,
    CostOverview,
    CostSummary,
    CreditBalance,
    LedgerEvent,
    LedgerStatus,
    ReservationRequest,
)
from cineforge.cost.credits import SIMULATED_CREDIT_BALANCES, with_default_balances
from cineforge.cost.reporting import (
    PRODUCTION_SCOPE,
    Totals,
    agent_label,
    build_summary,
    capped_actual,
    overspend_reason,
    rows,
    scope_key,
)
from cineforge.db import connection

log = logging.getLogger(__name__)

_LEDGER_COLUMNS = (
    "event_id, tenant_id, production_id, scene_id, shot_id, agent_id, provider, model, "
    "capability, provider_request_id, usage_units, usage_unit, unit_price_version, "
    "estimated_cost, reserved_cost, actual_cost, currency, status, status_reason, attempt, "
    "retry_reason, "
    'cache_hit, credits_used, idempotency_key, "timestamp", updated_at'
)

_AGGREGATES = (
    "coalesce(sum(estimated_cost), 0) as estimated, "
    "coalesce(sum(reserved_cost) filter (where status = 'reserved'), 0) as reserved, "
    "coalesce(sum(actual_cost), 0) as actual, "
    "count(*) as n"
)


def _budget(row: dict[str, Any]) -> Budget:
    data = dict(row)
    data.pop("scope_key", None)
    return Budget.model_validate(data)


def _event(row: dict[str, Any]) -> LedgerEvent:
    return LedgerEvent.model_validate(row)


def _totals(row: dict[str, Any]) -> Totals:
    return Totals(
        estimated=row["estimated"], reserved=row["reserved"], actual=row["actual"], count=row["n"]
    )


class PostgresBudgetService:
    def __init__(
        self, database_url: str, initial_credits: dict[str, Decimal] | None = None
    ) -> None:
        self.database_url = database_url
        self._initial_credits = dict(
            SIMULATED_CREDIT_BALANCES if initial_credits is None else initial_credits
        )

    # ------------------------------------------------------------------ budgets
    def create_budget(
        self,
        *,
        tenant_id: str,
        production_id: str,
        limit: Decimal,
        currency: str = DEFAULT_CURRENCY,
        scene_limits: dict[str, Decimal] | None = None,
    ) -> Budget:
        with connection(self.database_url) as conn:
            inserted = conn.execute(
                """
                insert into budgets (id, tenant_id, production_id, scope_key, scene_id, currency,
                                     limit_amount)
                values (%s, %s, %s, %s, null, %s, %s)
                on conflict (production_id, scope_key) do nothing
                returning *
                """,
                (new_id("budget"), tenant_id, production_id, PRODUCTION_SCOPE, currency,
                 money(limit)),
            ).fetchone()  # fmt: skip
            if inserted is None:
                self._set_limit(conn, production_id, limit, None)
            for scene_id, scene_limit in (scene_limits or {}).items():
                self._set_limit(conn, production_id, scene_limit, scene_id)
            row = conn.execute(
                "select * from budgets where production_id = %s and scope_key = %s",
                (production_id, PRODUCTION_SCOPE),
            ).fetchone()
            return _budget(row)

    def get_budget(self, production_id: str, scene_id: str | None = None) -> Budget | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select * from budgets where production_id = %s and scope_key = %s",
                (production_id, scope_key(scene_id)),
            ).fetchone()
            return _budget(row) if row else None

    def set_limit(self, production_id: str, limit: Decimal, scene_id: str | None = None) -> Budget:
        with connection(self.database_url) as conn:
            return self._set_limit(conn, production_id, limit, scene_id)

    def _set_limit(
        self, conn: psycopg.Connection, production_id: str, limit: Decimal, scene_id: str | None
    ) -> Budget:
        limit = money(limit)
        production = conn.execute(
            "select * from budgets where production_id = %s and scope_key = %s for update",
            (production_id, PRODUCTION_SCOPE),
        ).fetchone()
        if production is None:
            raise LookupError(f"no production budget for {production_id}; create it first")
        target = production
        if scene_id is not None:
            target = conn.execute(
                "select * from budgets where production_id = %s and scope_key = %s for update",
                (production_id, scope_key(scene_id)),
            ).fetchone()
        if target is None:
            # A new scene scope inherits the ledger history already booked for the scene.
            history = conn.execute(
                f"select {_AGGREGATES} from cost_ledger where production_id = %s and scene_id = %s",
                (production_id, scene_id),
            ).fetchone()
            reserved, actual = history["reserved"], history["actual"]
            if reserved + actual > limit:
                raise ValueError(f"limit {limit} is below reserved+actual {reserved + actual}")
            row = conn.execute(
                """
                insert into budgets (id, tenant_id, production_id, scope_key, scene_id, currency,
                                     limit_amount, reserved_amount, actual_amount)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                returning *
                """,
                (new_id("budget"), production["tenant_id"], production_id, scope_key(scene_id),
                 scene_id, production["currency"], limit, reserved, actual),
            ).fetchone()  # fmt: skip
            return _budget(row)
        used = target["reserved_amount"] + target["actual_amount"]
        if limit < used:
            raise ValueError(f"limit {limit} is below reserved+actual {used}")
        row = conn.execute(
            "update budgets set limit_amount = %s, updated_at = now() where id = %s returning *",
            (limit, target["id"]),
        ).fetchone()
        return _budget(row)

    def _lock_scopes(
        self, conn: psycopg.Connection, production_id: str, scene_id: str | None
    ) -> list[dict[str, Any]]:
        keys = [PRODUCTION_SCOPE] + ([scope_key(scene_id)] if scene_id else [])
        return conn.execute(
            """
            select * from budgets
            where production_id = %s and scope_key = any(%s)
            order by scope_key
            for update
            """,
            (production_id, keys),
        ).fetchall()

    # ------------------------------------------------------------------ ledger
    def _event_by_key(self, conn: psycopg.Connection, key: str) -> LedgerEvent | None:
        row = conn.execute(
            f"select {_LEDGER_COLUMNS} from cost_ledger where idempotency_key = %s", (key,)
        ).fetchone()
        return _event(row) if row else None

    def reserve(self, request: ReservationRequest) -> LedgerEvent:
        requested = money(request.estimated_cost)
        with connection(self.database_url) as conn:
            existing = self._event_by_key(conn, request.idempotency_key)
            if existing is not None:
                return existing
            scopes = self._lock_scopes(conn, request.production_id, request.scene_id)
            if not any(s["scope_key"] == PRODUCTION_SCOPE for s in scopes):
                raise BudgetExceededError(
                    production_id=request.production_id,
                    scene_id=None,
                    requested=requested,
                    available=Decimal(0),
                )
            # Re-check under the lock: a concurrent caller with the same key may have won.
            existing = self._event_by_key(conn, request.idempotency_key)
            if existing is not None:
                return existing
            for scope in scopes:
                used = scope["reserved_amount"] + scope["actual_amount"]
                if used + requested > scope["limit_amount"]:
                    raise BudgetExceededError(
                        production_id=request.production_id,
                        scene_id=scope["scene_id"],
                        requested=requested,
                        available=money(max(Decimal(0), scope["limit_amount"] - used)),
                    )
            conn.execute(
                """
                update budgets set reserved_amount = reserved_amount + %s, updated_at = now()
                where id = any(%s)
                """,
                (requested, [s["id"] for s in scopes]),
            )
            row = conn.execute(
                f"""
                insert into cost_ledger (
                    event_id, tenant_id, production_id, scene_id, shot_id, agent_id, provider,
                    model, capability, usage_units, usage_unit, unit_price_version,
                    estimated_cost, reserved_cost, actual_cost, currency, status, attempt,
                    retry_reason, idempotency_key)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, %s,
                        'reserved', %s, %s, %s)
                on conflict (idempotency_key) do nothing
                returning {_LEDGER_COLUMNS}
                """,
                (new_id("ledger"), request.tenant_id, request.production_id, request.scene_id,
                 request.shot_id, request.agent_id.value, request.provider, request.model,
                 request.capability.value, request.usage_units, request.usage_unit.value,
                 request.unit_price_version, money(request.estimated_cost), requested,
                 scopes[0]["currency"], request.attempt, request.retry_reason,
                 request.idempotency_key),
            ).fetchone()  # fmt: skip
            if row is None:
                raise RuntimeError(
                    f"idempotency key {request.idempotency_key!r} already used by another "
                    "production's ledger"
                )
            return _event(row)

    def _lock_event(self, conn: psycopg.Connection, event_id: str) -> dict[str, Any]:
        """Lock the event's budget scopes, then the ledger row (global lock order)."""
        head = conn.execute(
            "select production_id, scene_id from cost_ledger where event_id = %s", (event_id,)
        ).fetchone()
        if head is None:
            raise LookupError(f"ledger event {event_id} not found")
        self._lock_scopes(conn, head["production_id"], head["scene_id"])
        return conn.execute(
            f"select {_LEDGER_COLUMNS} from cost_ledger where event_id = %s for update",
            (event_id,),
        ).fetchone()

    def _settle(self, conn: psycopg.Connection, event: dict[str, Any], actual: Decimal) -> None:
        for scope in self._lock_scopes(conn, event["production_id"], event["scene_id"]):
            reserved = max(Decimal(0), scope["reserved_amount"] - event["reserved_cost"])
            applied = capped_actual(
                limit=scope["limit_amount"],
                reserved=reserved,
                actual=scope["actual_amount"],
                amount=actual,
            )
            conn.execute(
                """
                update budgets
                set reserved_amount = %s, actual_amount = actual_amount + %s, updated_at = now()
                where id = %s
                """,
                (reserved, applied, scope["id"]),
            )

    def commit(
        self,
        event_id: str,
        *,
        actual_cost: Decimal,
        usage_units: Decimal | None = None,
        provider_request_id: str | None = None,
        cache_hit: bool = False,
        credits_used: Decimal | None = None,
    ) -> LedgerEvent:
        actual = money(actual_cost)
        with connection(self.database_url) as conn:
            event = self._lock_event(conn, event_id)
            if event["status"] == LedgerStatus.COMMITTED:
                return _event(event)
            if event["status"] != LedgerStatus.RESERVED:
                raise ValueError(f"ledger event {event_id} is {event['status']}, cannot commit")
            reason = overspend_reason(reserved=event["reserved_cost"], actual=actual)
            if reason:
                log.warning("ledger %s %s", event_id, reason)
            self._settle(conn, event, actual)
            row = conn.execute(
                f"""
                update cost_ledger
                set status = 'committed', status_reason = %s, actual_cost = %s,
                    usage_units = coalesce(%s, usage_units), provider_request_id = %s,
                    cache_hit = %s, credits_used = %s, updated_at = now()
                where event_id = %s
                returning {_LEDGER_COLUMNS}
                """,
                (reason, actual, usage_units, provider_request_id, cache_hit, credits_used,
                 event_id),
            ).fetchone()  # fmt: skip
            if credits_used:
                start = self._initial_credits.get(event["provider"], Decimal(0))
                conn.execute(
                    """
                    insert into credit_balances (tenant_id, provider, balance, is_estimated)
                    values (%s, %s, %s, true)
                    on conflict (tenant_id, provider) do update
                    set balance = credit_balances.balance - %s, updated_at = now()
                    """,
                    (event["tenant_id"], event["provider"], start - credits_used, credits_used),
                )
            return _event(row)

    def release(
        self, event_id: str, *, reason: str, failed: bool = False, actual_cost: Decimal = Decimal(0)
    ) -> LedgerEvent:
        actual = money(actual_cost)
        with connection(self.database_url) as conn:
            event = self._lock_event(conn, event_id)
            if event["status"] in (LedgerStatus.RELEASED, LedgerStatus.FAILED):
                return _event(event)
            if event["status"] == LedgerStatus.COMMITTED:
                raise ValueError(f"ledger event {event_id} is committed, cannot release")
            self._settle(conn, event, actual)
            status = LedgerStatus.FAILED if failed else LedgerStatus.RELEASED
            row = conn.execute(
                f"""
                update cost_ledger
                set status = %s, status_reason = %s, actual_cost = %s, updated_at = now()
                where event_id = %s
                returning {_LEDGER_COLUMNS}
                """,
                (status.value, reason, actual, event_id),
            ).fetchone()
            log.info("ledger %s %s: %s", event_id, status, reason)
            return _event(row)

    def ledger(self, production_id: str) -> list[LedgerEvent]:
        with connection(self.database_url) as conn:
            found = conn.execute(
                f"""
                select {_LEDGER_COLUMNS} from cost_ledger where production_id = %s
                order by "timestamp", event_id
                """,
                (production_id,),
            ).fetchall()
            return [_event(r) for r in found]

    # ------------------------------------------------------------------ reports
    def _grouped(
        self, conn: psycopg.Connection, expr: str, where: str, arg: str
    ) -> dict[str, Totals]:
        found = conn.execute(
            f"select {expr} as key, {_AGGREGATES} from cost_ledger where {where} = %s group by 1",
            (arg,),
        ).fetchall()
        return {r["key"]: _totals(r) for r in found}

    def _stats(self, conn: psycopg.Connection, where: str, arg: str) -> dict[str, Any]:
        return conn.execute(
            f"""
            select {_AGGREGATES},
                   count(*) filter (where attempt > 1) as retries,
                   count(*) filter (where cache_hit) as cache_hits,
                   coalesce(bool_and(provider like 'mock-%%'), true) as simulated
            from cost_ledger where {where} = %s
            """,
            (arg,),
        ).fetchone()

    def summary(self, production_id: str, *, estimate: CostEstimate | None = None) -> CostSummary:
        with connection(self.database_url) as conn:
            budget_row = conn.execute(
                "select * from budgets where production_id = %s and scope_key = %s",
                (production_id, PRODUCTION_SCOPE),
            ).fetchone()
            stats = self._stats(conn, "production_id", production_id)
            where = "production_id"
            by_scene = self._grouped(conn, "coalesce(scene_id, 'production')", where, production_id)
            by_agent = self._grouped(conn, "agent_id", where, production_id)
            by_provider = self._grouped(conn, "provider", where, production_id)
        return build_summary(
            production_id=production_id,
            budget=_budget(budget_row) if budget_row else None,
            totals=_totals(stats),
            by_scene=by_scene,
            by_agent=by_agent,
            by_provider=by_provider,
            retry_count=stats["retries"],
            cache_hits=stats["cache_hits"],
            simulated=stats["simulated"],
            estimate=estimate,
        )

    def overview(self, tenant_id: str) -> CostOverview:
        with connection(self.database_url) as conn:
            productions = conn.execute(
                """
                select p.id,
                       coalesce(b.limit_amount, p.budget_limit) as limit_amount,
                       coalesce((p.manifest -> 'budget' ->> 'estimated')::numeric, 0)
                           as manifest_estimated
                from productions p
                left join budgets b on b.production_id = p.id and b.scope_key = 'production'
                where p.tenant_id = %s
                """,
                (tenant_id,),
            ).fetchall()
            stats = self._stats(conn, "tenant_id", tenant_id)
            per_production = self._grouped(conn, "production_id", "tenant_id", tenant_id)
            by_provider = self._grouped(conn, "provider", "tenant_id", tenant_id)
            by_agent = self._grouped(conn, "agent_id", "tenant_id", tenant_id)
        total_limit = Decimal(0)
        total_estimated = Decimal(0)
        for p in productions:
            totals = per_production.setdefault(p["id"], Totals())
            # Prefer the preflight estimate recorded on the manifest over ledger estimates.
            if p["manifest_estimated"] > 0:
                totals.estimated = p["manifest_estimated"]
            total_limit += p["limit_amount"]
            total_estimated += totals.estimated
        return CostOverview(
            tenant_id=tenant_id,
            production_count=len(productions),
            total_limit=money(total_limit),
            total_estimated=money(total_estimated),
            total_reserved=money(stats["reserved"]),
            total_actual=money(stats["actual"]),
            by_production=rows(per_production, str),
            by_provider=rows(by_provider, str),
            by_agent=rows(by_agent, agent_label),
            retry_count=stats["retries"],
            credit_balances=self.credit_balances(tenant_id),
            simulated=stats["simulated"],
        )

    # ------------------------------------------------------------------ credits
    def credit_balances(self, tenant_id: str) -> list[CreditBalance]:
        with connection(self.database_url) as conn:
            found = conn.execute(
                "select * from credit_balances where tenant_id = %s", (tenant_id,)
            ).fetchall()
        stored = {r["provider"]: CreditBalance.model_validate(r) for r in found}
        return with_default_balances(tenant_id, stored, self._initial_credits)
