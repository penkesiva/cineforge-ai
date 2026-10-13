"""Workstream D test support: contract fakes (repositories, queue) and Postgres helpers.

The real ProductionRepository / AgentRunRepository / TaskQueue belong to Workstream B;
these fakes implement only the frozen Protocols so D can be tested in isolation.
"""

from __future__ import annotations

import os
import threading
import uuid
from contextlib import suppress
from typing import Any

import psycopg
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus
from cineforge.contracts.common import DEMO_TENANT_ID, money, utcnow
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.repositories import NotFoundError
from cineforge.contracts.workflow import ProductionEvent, ProductionState, assert_transition
from cineforge.db import ping
from cineforge.runtime import Repositories, Runtime
from cineforge.testing import sample_manifest
from psycopg.types.json import Jsonb

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
)


def db_available() -> bool:
    return ping(DATABASE_URL)


# --------------------------------------------------------------------------- fakes
class FakeProductions:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.items: dict[str, ProductionManifest] = {}
        self.event_log: list[ProductionEvent] = []
        self.saves = 0

    def create(
        self, manifest: ProductionManifest, *, idempotency_key: str | None = None
    ) -> ProductionManifest:
        with self._lock:
            self.items.setdefault(manifest.production_id, manifest.model_copy(deep=True))
            return self.items[manifest.production_id].model_copy(deep=True)

    def get(self, production_id: str, tenant_id: str) -> ProductionManifest | None:
        with self._lock:
            m = self.items.get(production_id)
            if m is None or m.tenant_id != tenant_id:
                return None
            return m.model_copy(deep=True)

    def list(self, tenant_id: str, *, limit: int = 50) -> list[ProductionManifest]:
        with self._lock:
            return [
                m.model_copy(deep=True) for m in self.items.values() if m.tenant_id == tenant_id
            ]

    def save(self, manifest: ProductionManifest) -> ProductionManifest:
        with self._lock:
            if manifest.production_id not in self.items:
                raise NotFoundError(manifest.production_id)
            stored = manifest.model_copy(deep=True)
            stored.updated_at = utcnow()
            self.items[manifest.production_id] = stored
            self.saves += 1
            return stored.model_copy(deep=True)

    def transition(
        self,
        production_id: str,
        tenant_id: str,
        to_state: ProductionState,
        *,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> ProductionManifest:
        with self._lock:
            m = self.items.get(production_id)
            if m is None or m.tenant_id != tenant_id:
                raise NotFoundError(production_id)
            assert_transition(m.state, to_state)
            self.event_log.append(
                ProductionEvent(
                    production_id=production_id,
                    tenant_id=tenant_id,
                    event_type="state_changed",
                    from_state=m.state,
                    to_state=to_state,
                    message=reason,
                    payload=payload or {},
                )
            )
            m.state = to_state
            return m.model_copy(deep=True)

    def add_event(self, event: ProductionEvent) -> ProductionEvent:
        self.event_log.append(event)
        return event

    def events(self, production_id: str, tenant_id: str) -> list[ProductionEvent]:
        return [e for e in self.event_log if e.production_id == production_id]


class FakeAgentRuns:
    def __init__(self) -> None:
        self.runs: dict[str, AgentRun] = {}

    def start(self, run: AgentRun) -> AgentRun:
        for existing in self.runs.values():
            if (
                existing.idempotency_key == run.idempotency_key
                and existing.status == AgentRunStatus.SUCCEEDED
            ):
                return existing.model_copy(deep=True)
        stored = run.model_copy(update={"status": AgentRunStatus.RUNNING})
        self.runs[stored.id] = stored
        return stored.model_copy(deep=True)

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
        run = self.runs[run_id]
        run.status = status
        run.output = output
        run.output_model = output_model
        run.error = error
        if actual_cost is not None:
            run.actual_cost = money(actual_cost)
        run.finished_at = utcnow()
        return run.model_copy(deep=True)

    def get_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None:
        found = [r for r in self.runs.values() if r.idempotency_key == idempotency_key]
        return found[-1].model_copy(deep=True) if found else None

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AgentRun]:
        return [
            r.model_copy(deep=True)
            for r in self.runs.values()
            if r.production_id == production_id and r.tenant_id == tenant_id
        ]


class FakeQueue:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, str, dict[str, Any], str]] = []

    def enqueue(
        self, queue: str, job_path: str, kwargs: dict[str, Any], *, job_id: str | None = None
    ) -> str:
        job_id = job_id or f"job_{uuid.uuid4().hex[:12]}"
        if not any(j[3] == job_id for j in self.jobs):
            self.jobs.append((queue, job_path, dict(kwargs), job_id))
        return job_id


def fake_runtime(settings: Settings | None = None) -> Runtime:
    """Runtime with memory D services and B fakes injected (cached_property override)."""
    rt = Runtime(settings or Settings(persistence_backend="memory", queue_backend="inline"))
    rt.__dict__["repositories"] = Repositories(
        productions=FakeProductions(), agent_runs=FakeAgentRuns()
    )
    rt.__dict__["queue"] = FakeQueue()
    return rt


# --------------------------------------------------------------------------- postgres
class PgScratch:
    """Creates uniquely named tenants/productions in the shared DB and removes them."""

    def __init__(self, url: str = DATABASE_URL) -> None:
        self.url = url
        self.tenants: list[str] = []
        self.tenant_id = self.add_tenant()

    def _exec(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(sql, params)

    def add_tenant(self) -> str:
        tenant_id = f"tenant_test_{uuid.uuid4().hex[:12]}"
        self._exec("insert into tenants (id, name) values (%s, %s)", (tenant_id, "D test tenant"))
        self.tenants.append(tenant_id)
        return tenant_id

    def add_production(self, *, tenant_id: str | None = None, budget_limit: float = 10.0) -> str:
        tenant_id = tenant_id or self.tenant_id
        production_id = f"prod_test_{uuid.uuid4().hex[:16]}"
        manifest = sample_manifest(
            production_id=production_id, tenant_id=tenant_id, budget_limit=budget_limit
        )
        self._exec(
            """
            insert into productions (id, tenant_id, theme_id, theme_version, mode, state, title,
                                     topic, manifest, budget_limit)
            values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (production_id, tenant_id, manifest.theme_profile.id, manifest.theme_profile.version,
             manifest.mode.value, manifest.state.value, manifest.title,
             manifest.creative_brief.topic, Jsonb(manifest.model_dump(mode="json")),
             money(budget_limit)),
        )  # fmt: skip
        return production_id

    def cleanup(self) -> None:
        for tenant_id in self.tenants:
            with suppress(psycopg.Error):
                self._exec("delete from assets where tenant_id = %s", (tenant_id,))
                self._exec("delete from productions where tenant_id = %s", (tenant_id,))
                self._exec("delete from credit_balances where tenant_id = %s", (tenant_id,))
                self._exec("delete from tenants where id = %s", (tenant_id,))


__all__ = [
    "DATABASE_URL",
    "DEMO_TENANT_ID",
    "FakeAgentRuns",
    "FakeProductions",
    "FakeQueue",
    "PgScratch",
    "db_available",
    "fake_runtime",
]
