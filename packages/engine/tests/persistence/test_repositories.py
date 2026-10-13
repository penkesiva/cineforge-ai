"""Repository contract tests, run against the memory and (integration) Postgres backends."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus
from cineforge.contracts.common import DEMO_TENANT_ID, AgentId, money
from cineforge.contracts.repositories import (
    AgentRunRepository,
    NotFoundError,
    ProductionRepository,
)
from cineforge.contracts.review import ReviewFinding, ReviewGate, Severity
from cineforge.contracts.workflow import (
    InvalidStateTransitionError,
    ProductionEvent,
    ProductionState,
)
from cineforge.persistence.factory import build_repositories
from cineforge.persistence.memory import InMemoryAgentRunRepository, InMemoryProductionRepository
from cineforge.testing import sample_manifest

S = ProductionState
DB_URL = Settings().database_url


@dataclass
class Backend:
    productions: ProductionRepository
    agent_runs: AgentRunRepository
    tenant_a: str
    tenant_b: str
    created: list[str] = field(default_factory=list)

    def new_manifest(self, tenant_id: str | None = None, **kwargs):
        pid = f"prod_btest{uuid.uuid4().hex[:12]}"
        self.created.append(pid)
        return sample_manifest(production_id=pid, tenant_id=tenant_id or self.tenant_a, **kwargs)


def _memory_backend() -> Backend:
    return Backend(
        InMemoryProductionRepository(), InMemoryAgentRunRepository(), DEMO_TENANT_ID, "tenant_other"
    )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def backend(request: pytest.FixtureRequest) -> Iterator[Backend]:
    if request.param == "memory":
        yield _memory_backend()
        return
    from cineforge.db import connection, ping

    if not ping(DB_URL):
        pytest.skip("Postgres not reachable")
    repos = build_repositories(Settings(persistence_backend="postgres", database_url=DB_URL))
    tenant_b = f"tenant_btest_{uuid.uuid4().hex[:8]}"
    b = Backend(repos.productions, repos.agent_runs, DEMO_TENANT_ID, tenant_b)
    try:
        yield b
    finally:
        with connection(DB_URL) as conn:
            if b.created:
                conn.execute("delete from public.productions where id = any(%s)", (b.created,))
            conn.execute("delete from public.tenants where id = %s", (tenant_b,))


# --------------------------------------------------------------------------- productions
def test_create_get_and_list(backend: Backend) -> None:
    first = backend.productions.create(backend.new_manifest())
    second = backend.productions.create(backend.new_manifest())
    got = backend.productions.get(first.production_id, backend.tenant_a)
    assert got is not None
    assert got.production_id == first.production_id
    assert got.state == S.DRAFT
    assert len(got.scenes) == 5
    listed = [m.production_id for m in backend.productions.list(backend.tenant_a, limit=500)]
    assert first.production_id in listed and second.production_id in listed


def test_list_is_newest_first(backend: Backend) -> None:
    from datetime import UTC, datetime, timedelta

    base = datetime(2030, 1, 1, tzinfo=UTC)
    tenant = backend.tenant_b
    ids = []
    for offset in (0, 2, 1):
        m = backend.new_manifest(tenant_id=tenant).model_copy(
            update={"created_at": base + timedelta(minutes=offset)}
        )
        ids.append(backend.productions.create(m).production_id)
    listed = [m.production_id for m in backend.productions.list(tenant)]
    assert listed == [ids[1], ids[2], ids[0]]


def test_idempotent_create_returns_existing(backend: Backend) -> None:
    key = f"idem-{uuid.uuid4().hex}"
    first = backend.productions.create(backend.new_manifest(), idempotency_key=key)
    again = backend.productions.create(backend.new_manifest(), idempotency_key=key)
    assert again.production_id == first.production_id


def test_tenant_isolation(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest(tenant_id=backend.tenant_b))
    assert backend.productions.get(m.production_id, backend.tenant_a) is None
    assert m.production_id not in [
        x.production_id for x in backend.productions.list(backend.tenant_a, limit=500)
    ]
    assert backend.productions.events(m.production_id, backend.tenant_a) == []
    with pytest.raises(NotFoundError):
        backend.productions.transition(m.production_id, backend.tenant_a, S.CANCELLED, reason="x")
    with pytest.raises(NotFoundError):
        backend.productions.save(m.model_copy(update={"tenant_id": backend.tenant_a}))


def test_save_persists_changes_but_never_state(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest())
    m.title = "Renamed"
    m.state = S.READY  # must be ignored
    m.review_findings.append(
        ReviewFinding(gate=ReviewGate.MASTER, severity=Severity.CRITICAL, message="no master")
    )
    saved = backend.productions.save(m)
    assert saved.state == S.DRAFT
    assert saved.updated_at != m.updated_at
    got = backend.productions.get(m.production_id, backend.tenant_a)
    assert got is not None
    assert got.title == "Renamed"
    assert got.state == S.DRAFT
    assert got.review_findings[0].blocking is True


def test_save_unknown_production_raises(backend: Backend) -> None:
    with pytest.raises(NotFoundError):
        backend.productions.save(backend.new_manifest())


def test_transition_validates_and_records_event(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest())
    moved = backend.productions.transition(
        m.production_id, backend.tenant_a, S.RESEARCHING, reason="run", payload={"by": "test"}
    )
    assert moved.state == S.RESEARCHING
    assert backend.productions.get(m.production_id, backend.tenant_a).state == S.RESEARCHING
    with pytest.raises(InvalidStateTransitionError):
        backend.productions.transition(m.production_id, backend.tenant_a, S.READY, reason="skip")
    events = backend.productions.events(m.production_id, backend.tenant_a)
    assert [(e.event_type, e.from_state, e.to_state) for e in events] == [
        ("state_changed", S.DRAFT, S.RESEARCHING)
    ]
    assert events[0].payload == {"by": "test"}
    assert events[0].message == "run"


def test_add_event_and_order(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest())
    for name in ("created", "approved", "budget_paused"):
        backend.productions.add_event(
            ProductionEvent(
                production_id=m.production_id,
                tenant_id=backend.tenant_a,
                event_type=name,
                payload={"requested": 1.5},
            )
        )
    events = backend.productions.events(m.production_id, backend.tenant_a)
    assert [e.event_type for e in events] == ["created", "approved", "budget_paused"]
    assert all(e.id is not None for e in events)
    assert events[2].payload == {"requested": 1.5}
    with pytest.raises(NotFoundError):
        backend.productions.add_event(
            ProductionEvent(production_id=m.production_id, tenant_id="nope", event_type="x")
        )


@pytest.mark.integration
def test_postgres_save_upserts_review_findings_and_columns() -> None:
    from cineforge.db import connection, ping

    if not ping(DB_URL):
        pytest.skip("Postgres not reachable")
    repos = build_repositories(Settings(persistence_backend="postgres", database_url=DB_URL))
    pid = f"prod_btest{uuid.uuid4().hex[:12]}"
    try:
        m = repos.productions.create(sample_manifest(production_id=pid))
        keep = ReviewFinding(gate=ReviewGate.MASTER, severity=Severity.CRITICAL, message="a")
        drop = ReviewFinding(gate=ReviewGate.SCENE, severity=Severity.MINOR, message="b")
        m.review_findings = [keep, drop]
        m.budget.limit = money(12)
        m = repos.productions.save(m)
        m.review_findings = [keep.model_copy(update={"message": "a2"})]
        repos.productions.save(m)
        repos.productions.transition(pid, DEMO_TENANT_ID, S.RESEARCHING, reason="go")
        with connection(DB_URL) as conn:
            rows = conn.execute(
                "select id, message, severity from public.review_findings where production_id = %s",
                (pid,),
            ).fetchall()
            prod = conn.execute(
                "select state, budget_limit, lock_version, manifest->>'state' as mstate "
                "from public.productions where id = %s",
                (pid,),
            ).fetchone()
        assert rows == [{"id": keep.id, "message": "a2", "severity": "critical"}]
        assert prod["state"] == "RESEARCHING" and prod["mstate"] == "RESEARCHING"
        assert prod["budget_limit"] == money(12)
        assert prod["lock_version"] == 4
    finally:
        with connection(DB_URL) as conn:
            conn.execute("delete from public.productions where id = %s", (pid,))


def test_memory_repo_returns_copies() -> None:
    b = _memory_backend()
    m = b.productions.create(b.new_manifest())
    got = b.productions.get(m.production_id, b.tenant_a)
    got.scenes.clear()
    got.title = "mutated"
    again = b.productions.get(m.production_id, b.tenant_a)
    assert len(again.scenes) == 5
    assert again.title != "mutated"


# --------------------------------------------------------------------------- agent runs
def _run(production_id: str, tenant_id: str, key: str) -> AgentRun:
    return AgentRun(
        id=f"run_{uuid.uuid4().hex[:16]}",
        production_id=production_id,
        tenant_id=tenant_id,
        agent_id=AgentId.RESEARCH,
        step=S.RESEARCHING,
        status=AgentRunStatus.QUEUED,
        idempotency_key=key,
        prompt_template_id="a2_research",
        prompt_template_version=1,
        input_summary={"topic": "x"},
        estimated_cost=money("0.01"),
    )


def test_agent_run_lifecycle_and_idempotency(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest())
    key = f"{m.production_id}:RESEARCHING:a2_research:production:1"
    started = backend.agent_runs.start(_run(m.production_id, backend.tenant_a, key))
    assert started.status == AgentRunStatus.RUNNING

    # A crashed run is restarted on the same row.
    restarted = backend.agent_runs.start(_run(m.production_id, backend.tenant_a, key))
    assert restarted.id == started.id
    assert restarted.status == AgentRunStatus.RUNNING

    done = backend.agent_runs.finish(
        started.id,
        status=AgentRunStatus.SUCCEEDED,
        output={"topic": "x", "claims": []},
        output_model="ResearchBrief",
        actual_cost=money("0.004"),
    )
    assert done.status == AgentRunStatus.SUCCEEDED
    assert done.actual_cost == money("0.004")
    assert done.finished_at is not None

    again = backend.agent_runs.start(_run(m.production_id, backend.tenant_a, key))
    assert again.id == started.id
    assert again.status == AgentRunStatus.SUCCEEDED
    assert again.output == {"topic": "x", "claims": []}

    by_key = backend.agent_runs.get_by_idempotency_key(key)
    assert by_key is not None and by_key.output_model == "ResearchBrief"
    assert backend.agent_runs.get_by_idempotency_key(key + "-missing") is None
    runs = backend.agent_runs.list_for_production(m.production_id, backend.tenant_a)
    assert [r.id for r in runs] == [started.id]
    assert backend.agent_runs.list_for_production(m.production_id, backend.tenant_b) == []


def test_agent_run_failure_then_retry(backend: Backend) -> None:
    m = backend.productions.create(backend.new_manifest())
    key = f"{m.production_id}:GENERATING:a7_visual_production:scene_01_shot_01:1"
    run = backend.agent_runs.start(_run(m.production_id, backend.tenant_a, key))
    failed = backend.agent_runs.finish(run.id, status=AgentRunStatus.FAILED, error="boom")
    assert failed.error == "boom"
    retried = backend.agent_runs.start(_run(m.production_id, backend.tenant_a, key))
    assert retried.status == AgentRunStatus.RUNNING
    assert retried.error is None


def test_finish_unknown_run_raises(backend: Backend) -> None:
    with pytest.raises(NotFoundError):
        backend.agent_runs.finish("run_missing", status=AgentRunStatus.FAILED)


def test_factory_selects_memory() -> None:
    repos = build_repositories(Settings(persistence_backend="memory"))
    assert isinstance(repos.productions, InMemoryProductionRepository)
    assert isinstance(repos.agent_runs, InMemoryAgentRunRepository)
