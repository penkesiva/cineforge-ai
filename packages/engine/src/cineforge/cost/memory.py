"""Process-local BudgetService for unit tests and PERSISTENCE_BACKEND=memory.

All state lives behind one lock, so reservations are atomic within the process.
Semantics mirror ``PostgresBudgetService`` exactly (shared test suite).
"""

from __future__ import annotations

import logging
import threading
from decimal import Decimal

from cineforge.contracts.common import DEFAULT_CURRENCY, money, utcnow
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
    group_events,
    is_simulated_provider,
    rows,
    scene_group_key,
    scope_key,
)

log = logging.getLogger(__name__)


class InMemoryBudgetService:
    def __init__(self, initial_credits: dict[str, Decimal] | None = None) -> None:
        self._lock = threading.Lock()
        self._budgets: dict[tuple[str, str], Budget] = {}
        self._events: dict[str, LedgerEvent] = {}
        self._by_key: dict[str, str] = {}
        self._credits: dict[tuple[str, str], CreditBalance] = {}
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
        with self._lock:
            key = (production_id, PRODUCTION_SCOPE)
            if key in self._budgets:
                self._set_limit_locked(production_id, limit, None)
            else:
                self._budgets[key] = Budget(
                    tenant_id=tenant_id,
                    production_id=production_id,
                    currency=currency,
                    limit_amount=money(limit),
                )
            for scene_id, scene_limit in (scene_limits or {}).items():
                self._set_limit_locked(production_id, scene_limit, scene_id)
            return self._budgets[key].model_copy()

    def get_budget(self, production_id: str, scene_id: str | None = None) -> Budget | None:
        with self._lock:
            budget = self._budgets.get((production_id, scope_key(scene_id)))
            return budget.model_copy() if budget else None

    def set_limit(self, production_id: str, limit: Decimal, scene_id: str | None = None) -> Budget:
        with self._lock:
            return self._set_limit_locked(production_id, limit, scene_id).model_copy()

    def _set_limit_locked(self, production_id: str, limit: Decimal, scene_id: str | None) -> Budget:
        limit = money(limit)
        key = (production_id, scope_key(scene_id))
        budget = self._budgets.get(key)
        if budget is None:
            production = self._budgets.get((production_id, PRODUCTION_SCOPE))
            if production is None or scene_id is None:
                raise LookupError(f"no production budget for {production_id}; create it first")
            # A new scene scope inherits the ledger history already booked for the scene.
            history = [
                e
                for e in self._events.values()
                if e.production_id == production_id and e.scene_id == scene_id
            ]
            totals = group_events(history, lambda e: "all").get("all", Totals())
            budget = Budget(
                tenant_id=production.tenant_id,
                production_id=production_id,
                scene_id=scene_id,
                currency=production.currency,
                limit_amount=limit,
                reserved_amount=money(totals.reserved),
                actual_amount=money(totals.actual),
            )
            if budget.committed_and_reserved > limit:
                raise ValueError(
                    f"limit {limit} is below reserved+actual {budget.committed_and_reserved}"
                )
            self._budgets[key] = budget
            return budget
        if limit < budget.committed_and_reserved:
            raise ValueError(
                f"limit {limit} is below reserved+actual {budget.committed_and_reserved}"
            )
        budget.limit_amount = limit
        budget.updated_at = utcnow()
        return budget

    def _scopes(self, production_id: str, scene_id: str | None) -> list[Budget]:
        scopes = [self._budgets[(production_id, PRODUCTION_SCOPE)]]
        if scene_id and (production_id, scope_key(scene_id)) in self._budgets:
            scopes.append(self._budgets[(production_id, scope_key(scene_id))])
        return scopes

    # ------------------------------------------------------------------ ledger
    def reserve(self, request: ReservationRequest) -> LedgerEvent:
        requested = money(request.estimated_cost)
        with self._lock:
            existing = self._by_key.get(request.idempotency_key)
            if existing is not None:
                return self._events[existing].model_copy()
            if (request.production_id, PRODUCTION_SCOPE) not in self._budgets:
                raise BudgetExceededError(
                    production_id=request.production_id,
                    scene_id=None,
                    requested=requested,
                    available=Decimal(0),
                )
            scopes = self._scopes(request.production_id, request.scene_id)
            for scope in scopes:
                if scope.committed_and_reserved + requested > scope.limit_amount:
                    raise BudgetExceededError(
                        production_id=request.production_id,
                        scene_id=scope.scene_id,
                        requested=requested,
                        available=money(scope.available),
                    )
            now = utcnow()
            for scope in scopes:
                scope.reserved_amount = money(scope.reserved_amount + requested)
                scope.updated_at = now
            event = LedgerEvent(
                tenant_id=request.tenant_id,
                production_id=request.production_id,
                scene_id=request.scene_id,
                shot_id=request.shot_id,
                agent_id=request.agent_id,
                provider=request.provider,
                model=request.model,
                capability=request.capability,
                usage_units=request.usage_units,
                usage_unit=request.usage_unit,
                unit_price_version=request.unit_price_version,
                estimated_cost=money(request.estimated_cost),
                reserved_cost=requested,
                currency=scopes[0].currency,
                status=LedgerStatus.RESERVED,
                attempt=request.attempt,
                retry_reason=request.retry_reason,
                idempotency_key=request.idempotency_key,
                timestamp=now,
                updated_at=now,
            )
            self._events[event.event_id] = event
            self._by_key[event.idempotency_key] = event.event_id
            return event.model_copy()

    def _settle(self, event: LedgerEvent, actual: Decimal) -> None:
        for scope in self._scopes(event.production_id, event.scene_id):
            scope.reserved_amount = money(
                max(Decimal(0), scope.reserved_amount - event.reserved_cost)
            )
            scope.actual_amount = money(
                scope.actual_amount
                + capped_actual(
                    limit=scope.limit_amount,
                    reserved=scope.reserved_amount,
                    actual=scope.actual_amount,
                    amount=actual,
                )
            )
            scope.updated_at = utcnow()

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
        with self._lock:
            event = self._get_event(event_id)
            if event.status == LedgerStatus.COMMITTED:
                return event.model_copy()
            if event.status != LedgerStatus.RESERVED:
                raise ValueError(f"ledger event {event_id} is {event.status}, cannot commit")
            if actual > event.reserved_cost:
                log.warning(
                    "ledger %s overran reservation: reserved %s, actual %s",
                    event_id,
                    event.reserved_cost,
                    actual,
                )
            self._settle(event, actual)
            event.status = LedgerStatus.COMMITTED
            event.actual_cost = actual
            if usage_units is not None:
                event.usage_units = usage_units
            event.provider_request_id = provider_request_id
            event.cache_hit = cache_hit
            event.credits_used = credits_used
            event.updated_at = utcnow()
            if credits_used:
                self._debit_credits(event.tenant_id, event.provider, credits_used)
            return event.model_copy()

    def release(
        self, event_id: str, *, reason: str, failed: bool = False, actual_cost: Decimal = Decimal(0)
    ) -> LedgerEvent:
        actual = money(actual_cost)
        with self._lock:
            event = self._get_event(event_id)
            if event.status in (LedgerStatus.RELEASED, LedgerStatus.FAILED):
                return event.model_copy()
            if event.status == LedgerStatus.COMMITTED:
                raise ValueError(f"ledger event {event_id} is committed, cannot release")
            self._settle(event, actual)
            event.status = LedgerStatus.FAILED if failed else LedgerStatus.RELEASED
            event.actual_cost = actual
            event.updated_at = utcnow()
            log.info("ledger %s %s: %s", event_id, event.status, reason)
            return event.model_copy()

    def _get_event(self, event_id: str) -> LedgerEvent:
        try:
            return self._events[event_id]
        except KeyError:
            raise LookupError(f"ledger event {event_id} not found") from None

    def ledger(self, production_id: str) -> list[LedgerEvent]:
        with self._lock:
            return [
                e.model_copy() for e in self._events.values() if e.production_id == production_id
            ]

    # ------------------------------------------------------------------ reports
    def summary(self, production_id: str, *, estimate: CostEstimate | None = None) -> CostSummary:
        with self._lock:
            events = [e for e in self._events.values() if e.production_id == production_id]
            budget = self._budgets.get((production_id, PRODUCTION_SCOPE))
            budget = budget.model_copy() if budget else None
        return build_summary(
            production_id=production_id,
            budget=budget,
            totals=group_events(events, lambda e: "all").get("all", Totals()),
            by_scene=group_events(events, lambda e: scene_group_key(e.scene_id)),
            by_agent=group_events(events, lambda e: e.agent_id.value),
            by_provider=group_events(events, lambda e: e.provider),
            retry_count=sum(1 for e in events if e.attempt > 1),
            cache_hits=sum(1 for e in events if e.cache_hit),
            simulated=all(is_simulated_provider(e.provider) for e in events),
            estimate=estimate,
        )

    def overview(self, tenant_id: str) -> CostOverview:
        with self._lock:
            budgets = [
                b
                for (_, scope), b in self._budgets.items()
                if scope == PRODUCTION_SCOPE and b.tenant_id == tenant_id
            ]
            ids = {b.production_id for b in budgets}
            events = [e for e in self._events.values() if e.production_id in ids]
            total_limit = sum((b.limit_amount for b in budgets), Decimal(0))
        per_production = group_events(events, lambda e: e.production_id)
        for production_id in ids:
            per_production.setdefault(production_id, Totals())
        totals = group_events(events, lambda e: "all").get("all", Totals())
        return CostOverview(
            tenant_id=tenant_id,
            production_count=len(ids),
            total_limit=money(total_limit),
            total_estimated=money(totals.estimated),
            total_reserved=money(totals.reserved),
            total_actual=money(totals.actual),
            by_production=rows(per_production, str),
            by_provider=rows(group_events(events, lambda e: e.provider), str),
            by_agent=rows(group_events(events, lambda e: e.agent_id.value), agent_label),
            retry_count=sum(1 for e in events if e.attempt > 1),
            credit_balances=self.credit_balances(tenant_id),
            simulated=all(is_simulated_provider(e.provider) for e in events),
        )

    # ------------------------------------------------------------------ credits
    def credit_balances(self, tenant_id: str) -> list[CreditBalance]:
        with self._lock:
            stored = {p: b for (t, p), b in self._credits.items() if t == tenant_id}
            return with_default_balances(tenant_id, stored, self._initial_credits)

    def _debit_credits(self, tenant_id: str, provider: str, credits: Decimal) -> None:
        key = (tenant_id, provider)
        current = self._credits.get(key)
        start = (
            current.balance
            if current is not None
            else self._initial_credits.get(provider, Decimal(0))
        )
        self._credits[key] = CreditBalance(
            tenant_id=tenant_id, provider=provider, balance=start - credits, is_estimated=True
        )
