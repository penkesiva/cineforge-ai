"""Postgres repositories (psycopg 3 via ``cineforge.db``). Every query is tenant-scoped."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from cineforge.contracts.agents import AgentRun, AgentRunStatus
from cineforge.contracts.common import money, utcnow
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.repositories import NotFoundError
from cineforge.contracts.workflow import ProductionEvent, ProductionState, assert_transition
from cineforge.db import connection
from cineforge.persistence.serde import dump, load

_EVENT_COLUMNS = (
    "id, production_id, tenant_id, event_type, from_state, to_state, message, payload, created_at"
)
_RUN_COLUMNS = (
    "id, production_id, tenant_id, agent_id, step, status, attempt, idempotency_key, "
    "prompt_template_id, prompt_template_version, input_summary, output, output_model, error, "
    "estimated_cost, actual_cost, started_at, finished_at"
)


def _manifest_from_row(row: dict[str, Any]) -> ProductionManifest:
    manifest = load(ProductionManifest, row["manifest"])
    # The state column is authoritative (it is what transition() locks and updates).
    return manifest.model_copy(update={"state": ProductionState(row["state"])})


def _event_from_row(row: dict[str, Any]) -> ProductionEvent:
    return ProductionEvent.model_validate(row)


def _run_from_row(row: dict[str, Any]) -> AgentRun:
    return AgentRun.model_validate(row)


class PostgresProductionRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _write_columns(self, manifest: ProductionManifest) -> dict[str, Any]:
        return {
            "id": manifest.production_id,
            "tenant_id": manifest.tenant_id,
            "theme_id": manifest.theme_profile.id,
            "theme_version": manifest.theme_profile.version,
            "mode": manifest.mode.value,
            "state": manifest.state.value,
            "title": manifest.title,
            "topic": manifest.creative_brief.topic,
            "manifest": Jsonb(dump(manifest)),
            "currency": manifest.budget.currency,
            "budget_limit": manifest.budget.limit,
            "created_at": manifest.created_at,
            "updated_at": manifest.updated_at,
        }

    def create(
        self, manifest: ProductionManifest, *, idempotency_key: str | None = None
    ) -> ProductionManifest:
        cols = self._write_columns(manifest) | {"idempotency_key": idempotency_key}
        with connection(self.database_url) as conn:
            # Tenants are auto-provisioned (Phase 0 has no tenant admin API).
            conn.execute(
                "insert into public.tenants (id, name) values (%s, %s) on conflict (id) do nothing",
                (manifest.tenant_id, manifest.tenant_id),
            )
            row = conn.execute(
                """
                insert into public.productions
                    (id, tenant_id, theme_id, theme_version, mode, state, title, topic, manifest,
                     currency, budget_limit, idempotency_key, lock_version, created_at, updated_at)
                values
                    (%(id)s, %(tenant_id)s, %(theme_id)s, %(theme_version)s, %(mode)s, %(state)s,
                     %(title)s, %(topic)s, %(manifest)s, %(currency)s, %(budget_limit)s,
                     %(idempotency_key)s, 1, %(created_at)s, %(updated_at)s)
                on conflict (idempotency_key) do nothing
                returning state, manifest
                """,
                cols,
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "select tenant_id, state, manifest from public.productions "
                    "where idempotency_key = %s",
                    (idempotency_key,),
                ).fetchone()
                if row is None:  # pragma: no cover - concurrent delete
                    raise NotFoundError("idempotent production vanished")
                if row["tenant_id"] != manifest.tenant_id:
                    raise ValueError("idempotency key already used by another tenant")
            return _manifest_from_row(row)

    def get(self, production_id: str, tenant_id: str) -> ProductionManifest | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select state, manifest from public.productions where id = %s and tenant_id = %s",
                (production_id, tenant_id),
            ).fetchone()
        return _manifest_from_row(row) if row else None

    def list(self, tenant_id: str, *, limit: int = 50) -> list[ProductionManifest]:
        with connection(self.database_url) as conn:
            rows = conn.execute(
                "select state, manifest from public.productions where tenant_id = %s "
                "order by created_at desc, id desc limit %s",
                (tenant_id, limit),
            ).fetchall()
        return [_manifest_from_row(r) for r in rows]

    def save(self, manifest: ProductionManifest) -> ProductionManifest:
        with connection(self.database_url) as conn:
            current = conn.execute(
                "select state from public.productions where id = %s and tenant_id = %s for update",
                (manifest.production_id, manifest.tenant_id),
            ).fetchone()
            if current is None:
                raise NotFoundError(f"production {manifest.production_id} not found")
            # State only changes through transition(); keep the stored state.
            updated = manifest.model_copy(
                update={"state": ProductionState(current["state"]), "updated_at": utcnow()}
            )
            cols = self._write_columns(updated)
            conn.execute(
                """
                update public.productions set
                    theme_id = %(theme_id)s, theme_version = %(theme_version)s, mode = %(mode)s,
                    title = %(title)s, topic = %(topic)s, manifest = %(manifest)s,
                    currency = %(currency)s, budget_limit = %(budget_limit)s,
                    updated_at = %(updated_at)s, lock_version = lock_version + 1
                where id = %(id)s and tenant_id = %(tenant_id)s
                """,
                cols,
            )
            self._sync_findings(conn, updated)
        return updated

    def _sync_findings(self, conn: psycopg.Connection, manifest: ProductionManifest) -> None:
        ids = [f.id for f in manifest.review_findings]
        conn.execute(
            "delete from public.review_findings "
            "where production_id = %s and tenant_id = %s and not (id = any(%s))",
            (manifest.production_id, manifest.tenant_id, ids),
        )
        for finding in manifest.review_findings:
            conn.execute(
                """
                insert into public.review_findings
                    (id, production_id, tenant_id, gate, severity, message, evidence,
                     affected_artifact_ids, recommended_fix, retry_scope, created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                on conflict (id) do update set
                    gate = excluded.gate, severity = excluded.severity,
                    message = excluded.message, evidence = excluded.evidence,
                    affected_artifact_ids = excluded.affected_artifact_ids,
                    recommended_fix = excluded.recommended_fix,
                    retry_scope = excluded.retry_scope
                """,
                (
                    finding.id,
                    manifest.production_id,
                    manifest.tenant_id,
                    finding.gate.value,
                    finding.severity.value,
                    finding.message,
                    Jsonb(finding.evidence),
                    Jsonb(finding.affected_artifact_ids),
                    finding.recommended_fix,
                    finding.retry_scope.value,
                    finding.created_at,
                ),
            )

    def transition(
        self,
        production_id: str,
        tenant_id: str,
        to_state: ProductionState,
        *,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> ProductionManifest:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select state, manifest from public.productions "
                "where id = %s and tenant_id = %s for update",
                (production_id, tenant_id),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"production {production_id} not found")
            manifest = _manifest_from_row(row)
            from_state = manifest.state
            assert_transition(from_state, to_state)
            updated = manifest.model_copy(update={"state": to_state, "updated_at": utcnow()})
            conn.execute(
                """
                update public.productions set
                    state = %s, manifest = %s, updated_at = %s, lock_version = lock_version + 1
                where id = %s and tenant_id = %s
                """,
                (
                    to_state.value,
                    Jsonb(dump(updated)),
                    updated.updated_at,
                    production_id,
                    tenant_id,
                ),
            )
            conn.execute(
                """
                insert into public.production_events
                    (production_id, tenant_id, event_type, from_state, to_state, message, payload)
                values (%s, %s, 'state_changed', %s, %s, %s, %s)
                """,
                (
                    production_id,
                    tenant_id,
                    from_state.value,
                    to_state.value,
                    reason,
                    Jsonb(payload or {}),
                ),
            )
        return updated

    def add_event(self, event: ProductionEvent) -> ProductionEvent:
        with connection(self.database_url) as conn:
            owned = conn.execute(
                "select 1 from public.productions where id = %s and tenant_id = %s",
                (event.production_id, event.tenant_id),
            ).fetchone()
            if owned is None:
                raise NotFoundError(f"production {event.production_id} not found")
            row = conn.execute(
                f"""
                insert into public.production_events
                    (production_id, tenant_id, event_type, from_state, to_state, message, payload,
                     created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning {_EVENT_COLUMNS}
                """,
                (
                    event.production_id,
                    event.tenant_id,
                    event.event_type,
                    event.from_state.value if event.from_state else None,
                    event.to_state.value if event.to_state else None,
                    event.message,
                    Jsonb(event.model_dump(mode="json")["payload"]),
                    event.created_at,
                ),
            ).fetchone()
        return _event_from_row(row)

    def events(self, production_id: str, tenant_id: str) -> list[ProductionEvent]:
        with connection(self.database_url) as conn:
            rows = conn.execute(
                f"select {_EVENT_COLUMNS} from public.production_events "
                "where production_id = %s and tenant_id = %s order by id",
                (production_id, tenant_id),
            ).fetchall()
        return [_event_from_row(r) for r in rows]


class PostgresAgentRunRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def start(self, run: AgentRun) -> AgentRun:
        with connection(self.database_url) as conn:
            row = conn.execute(
                f"""
                insert into public.agent_runs
                    (id, production_id, tenant_id, agent_id, step, status, attempt,
                     idempotency_key, prompt_template_id, prompt_template_version, input_summary,
                     estimated_cost, actual_cost, started_at)
                values (%s, %s, %s, %s, %s, 'running', %s, %s, %s, %s, %s, %s, 0, %s)
                on conflict (idempotency_key) do nothing
                returning {_RUN_COLUMNS}
                """,
                (
                    run.id,
                    run.production_id,
                    run.tenant_id,
                    run.agent_id.value,
                    run.step.value,
                    run.attempt,
                    run.idempotency_key,
                    run.prompt_template_id,
                    run.prompt_template_version,
                    Jsonb(run.model_dump(mode="json")["input_summary"]),
                    run.estimated_cost,
                    run.started_at,
                ),
            ).fetchone()
            if row is not None:
                return _run_from_row(row)
            existing = conn.execute(
                f"select {_RUN_COLUMNS} from public.agent_runs "
                "where idempotency_key = %s for update",
                (run.idempotency_key,),
            ).fetchone()
            if existing is None:  # pragma: no cover - concurrent delete
                raise NotFoundError(f"agent run {run.idempotency_key} vanished")
            if existing["status"] == AgentRunStatus.SUCCEEDED.value:
                return _run_from_row(existing)
            # Re-run of a failed/interrupted invocation: reuse the row.
            row = conn.execute(
                f"""
                update public.agent_runs set
                    status = 'running', input_summary = %s, output = null, output_model = null,
                    error = null, estimated_cost = %s, actual_cost = 0, started_at = now(),
                    finished_at = null
                where id = %s
                returning {_RUN_COLUMNS}
                """,
                (
                    Jsonb(run.model_dump(mode="json")["input_summary"]),
                    run.estimated_cost,
                    existing["id"],
                ),
            ).fetchone()
        return _run_from_row(row)

    def finish(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        output: dict[str, Any] | None = None,
        output_model: str | None = None,
        error: str | None = None,
        actual_cost: Any = None,
    ) -> AgentRun:
        cost = money(Decimal(str(actual_cost))) if actual_cost is not None else None
        with connection(self.database_url) as conn:
            row = conn.execute(
                f"""
                update public.agent_runs set
                    status = %s, output = %s, output_model = %s, error = %s,
                    actual_cost = coalesce(%s, actual_cost), finished_at = now()
                where id = %s
                returning {_RUN_COLUMNS}
                """,
                (
                    status.value,
                    Jsonb(output) if output is not None else None,
                    output_model,
                    error,
                    cost,
                    run_id,
                ),
            ).fetchone()
        if row is None:
            raise NotFoundError(f"agent run {run_id} not found")
        return _run_from_row(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                f"select {_RUN_COLUMNS} from public.agent_runs where idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
        return _run_from_row(row) if row else None

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AgentRun]:
        with connection(self.database_url) as conn:
            rows = conn.execute(
                f"select {_RUN_COLUMNS} from public.agent_runs "
                "where production_id = %s and tenant_id = %s order by started_at, id",
                (production_id, tenant_id),
            ).fetchall()
        return [_run_from_row(r) for r in rows]
