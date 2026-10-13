"""Shared BudgetService suite: runs against memory and (integration) Postgres."""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal

import pytest
from cineforge.config import Settings
from cineforge.configuration import load_mode_policies
from cineforge.contracts.common import AgentId, ProductionMode
from cineforge.contracts.cost import (
    BudgetExceededError,
    BudgetService,
    LedgerStatus,
    ReservationRequest,
)
from cineforge.contracts.providers import PriceUnit, ProviderCapability
from cineforge.cost.credits import SIMULATED_CREDIT_BALANCES
from cineforge.cost.factory import build_budget_service, build_cost_estimator, load_price_catalog
from cineforge.cost.memory import InMemoryBudgetService
from cineforge.testing import sample_manifest

D = Decimal


def _req(
    backend,
    production_id: str,
    cost: str,
    *,
    scene_id: str | None = None,
    key: str | None = None,
    attempt: int = 1,
    provider: str = "mock-video",
    agent: AgentId = AgentId.VISUAL_PRODUCTION,
    tenant_id: str | None = None,
) -> ReservationRequest:
    return ReservationRequest(
        tenant_id=tenant_id or backend.tenant_id,
        production_id=production_id,
        scene_id=scene_id,
        shot_id=f"{scene_id}_shot_01" if scene_id else None,
        agent_id=agent,
        provider=provider,
        model="mock-video-draft",
        capability=ProviderCapability.IMAGE_TO_VIDEO,
        usage_units=D("1"),
        usage_unit=PriceUnit.VIDEO_SECOND,
        unit_price_version="mock-2026-10",
        estimated_cost=D(cost),
        attempt=attempt,
        retry_reason="flaky" if attempt > 1 else None,
        idempotency_key=key or f"key_{uuid.uuid4().hex}",
    )


def test_protocol(backend) -> None:
    assert isinstance(backend.service, BudgetService)


def test_reserve_commit_release_math(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    a = svc.reserve(_req(backend, pid, "2.00"))
    b = svc.reserve(_req(backend, pid, "3.00"))
    assert a.status == LedgerStatus.RESERVED and a.reserved_cost == D("2")
    budget = svc.get_budget(pid)
    assert budget.reserved_amount == D("5") and budget.actual_amount == 0
    assert budget.available == D("5")

    committed = svc.commit(
        a.event_id,
        actual_cost=D("1.50"),
        usage_units=D("30"),
        provider_request_id="mockreq_1",
        cache_hit=True,
    )
    assert committed.status == LedgerStatus.COMMITTED
    assert committed.actual_cost == D("1.5") and committed.usage_units == D("30")
    assert committed.provider_request_id == "mockreq_1" and committed.cache_hit
    budget = svc.get_budget(pid)
    assert budget.reserved_amount == D("3") and budget.actual_amount == D("1.5")

    released = svc.release(b.event_id, reason="cancelled")
    assert released.status == LedgerStatus.RELEASED
    budget = svc.get_budget(pid)
    assert budget.reserved_amount == 0 and budget.actual_amount == D("1.5")

    c = svc.reserve(_req(backend, pid, "1.00"))
    failed = svc.release(c.event_id, reason="provider 500", failed=True, actual_cost=D("0.25"))
    assert failed.status == LedgerStatus.FAILED and failed.actual_cost == D("0.25")
    budget = svc.get_budget(pid)
    assert budget.reserved_amount == 0 and budget.actual_amount == D("1.75")

    # Commit and release are idempotent; mixing them is an error.
    assert svc.commit(a.event_id, actual_cost=D("9")).actual_cost == D("1.5")
    assert svc.release(b.event_id, reason="again").status == LedgerStatus.RELEASED
    with pytest.raises(ValueError):
        svc.release(a.event_id, reason="too late")
    with pytest.raises(ValueError):
        svc.commit(b.event_id, actual_cost=D("1"))
    with pytest.raises(LookupError):
        svc.commit("ledger_missing", actual_cost=D("1"))
    assert [e.event_id for e in svc.ledger(pid)] == [a.event_id, b.event_id, c.event_id]


def test_idempotent_reserve(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    req = _req(backend, pid, "4.00", key=f"{pid}:GENERATING:a7:shot:1:mock-video:draft")
    first = svc.reserve(req)
    second = svc.reserve(req)
    assert first.event_id == second.event_id
    assert svc.get_budget(pid).reserved_amount == D("4")
    assert len(svc.ledger(pid)) == 1
    svc.commit(first.event_id, actual_cost=D("4"))
    replay = svc.reserve(req)
    assert replay.event_id == first.event_id and replay.status == LedgerStatus.COMMITTED
    assert svc.get_budget(pid).reserved_amount == 0


def test_budget_exceeded_leaves_state_unchanged(backend) -> None:
    svc = backend.service
    pid = backend.new_production("5.00")
    svc.reserve(_req(backend, pid, "4.00"))
    before = svc.get_budget(pid)
    with pytest.raises(BudgetExceededError) as info:
        svc.reserve(_req(backend, pid, "1.50"))
    assert info.value.available == D("1") and info.value.requested == D("1.5")
    assert info.value.scene_id is None
    after = svc.get_budget(pid)
    assert (after.reserved_amount, after.actual_amount) == (
        before.reserved_amount,
        before.actual_amount,
    )
    assert len(svc.ledger(pid)) == 1
    # Exactly up to the limit is allowed.
    svc.reserve(_req(backend, pid, "1.00"))
    assert svc.get_budget(pid).available == 0


def test_no_budget_fails_closed(backend) -> None:
    pid = backend.new_production("1.00")
    with pytest.raises(BudgetExceededError):
        backend.service.reserve(_req(backend, pid + "_missing", "0.01"))


def test_scene_budget_enforced(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00", scene_limits={"scene_01": D("2.00")})
    scene = svc.get_budget(pid, "scene_01")
    assert scene is not None and scene.scene_id == "scene_01" and scene.limit_amount == D("2")
    svc.reserve(_req(backend, pid, "1.50", scene_id="scene_01"))
    with pytest.raises(BudgetExceededError) as info:
        svc.reserve(_req(backend, pid, "1.00", scene_id="scene_01"))
    assert info.value.scene_id == "scene_01" and info.value.available == D("0.5")
    # Other scenes (no scene scope) only consume the production budget.
    svc.reserve(_req(backend, pid, "5.00", scene_id="scene_02"))
    assert svc.get_budget(pid).reserved_amount == D("6.5")
    assert svc.get_budget(pid, "scene_01").reserved_amount == D("1.5")
    assert svc.get_budget(pid, "scene_02") is None


def test_new_scene_scope_inherits_history(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    ev = svc.reserve(_req(backend, pid, "1.00", scene_id="scene_03"))
    with pytest.raises(ValueError):
        svc.set_limit(pid, D("0.50"), scene_id="scene_03")
    scope = svc.set_limit(pid, D("3.00"), scene_id="scene_03")
    assert scope.reserved_amount == D("1") and scope.limit_amount == D("3")
    svc.commit(ev.event_id, actual_cost=D("0.80"))
    scope = svc.get_budget(pid, "scene_03")
    assert scope.reserved_amount == 0 and scope.actual_amount == D("0.8")


def test_set_limit(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    ev = svc.reserve(_req(backend, pid, "3.00"))
    svc.commit(ev.event_id, actual_cost=D("3.00"))
    svc.reserve(_req(backend, pid, "2.00"))
    with pytest.raises(ValueError):
        svc.set_limit(pid, D("4.99"))
    assert svc.set_limit(pid, D("5.00")).limit_amount == D("5")
    assert svc.set_limit(pid, D("20")).limit_amount == D("20")
    with pytest.raises(LookupError):
        svc.set_limit(pid + "_missing", D("1"))
    # create_budget on an existing production updates the limit (idempotent create).
    again = svc.create_budget(tenant_id=backend.tenant_id, production_id=pid, limit=D("12"))
    assert again.limit_amount == D("12") and again.reserved_amount == D("2")


def test_commit_overage_is_recorded_but_scope_capped(backend) -> None:
    svc = backend.service
    pid = backend.new_production("1.00")
    ev = svc.reserve(_req(backend, pid, "0.90"))
    committed = svc.commit(ev.event_id, actual_cost=D("1.20"))
    assert committed.actual_cost == D("1.2")  # ledger keeps the real spend
    budget = svc.get_budget(pid)
    assert budget.actual_amount == D("1") and budget.reserved_amount == 0
    with pytest.raises(BudgetExceededError):
        svc.reserve(_req(backend, pid, "0.01"))
    summary = svc.summary(pid)
    assert summary.actual == D("1.2") and summary.remaining == 0


def test_summary_numbers(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    e1 = svc.reserve(_req(backend, pid, "1.00", scene_id="scene_01"))
    svc.commit(e1.event_id, actual_cost=D("0.90"), cache_hit=True)
    e2 = svc.reserve(_req(backend, pid, "1.00", scene_id="scene_01", attempt=2))
    svc.release(e2.event_id, reason="boom", failed=True)
    svc.reserve(_req(backend, pid, "0.50", scene_id="scene_02"))
    e4 = svc.reserve(_req(backend, pid, "0.20", provider="mock-llm", agent=AgentId.SCRIPTWRITER))
    svc.commit(e4.event_id, actual_cost=D("0.10"))

    s = svc.summary(pid)
    assert s.limit == D("10")
    assert s.estimated == D("2.7")
    assert s.reserved == D("0.5")
    assert s.actual == D("1.0")
    assert s.remaining == D("8.5")
    assert s.event_count == 4 and s.retry_count == 1 and s.cache_hits == 1
    assert s.simulated is True
    scenes = {r.key: r for r in s.by_scene}
    assert set(scenes) == {"production", "scene_01", "scene_02"}
    assert scenes["scene_01"].actual == D("0.9") and scenes["scene_01"].event_count == 2
    assert scenes["scene_02"].reserved == D("0.5")
    assert scenes["production"].label == "Production-level"
    agents = {r.key: r for r in s.by_agent}
    assert agents["a5_scriptwriter"].actual == D("0.1")
    assert agents["a7_visual_production"].label == "Visual Production Agent"
    providers = {r.key: r for r in s.by_provider}
    assert providers["mock-video"].event_count == 3 and providers["mock-llm"].actual == D("0.1")


def test_summary_with_estimate(backend) -> None:
    svc = backend.service
    pid = backend.new_production("10.00")
    settings = Settings()
    estimator = build_cost_estimator(settings, load_price_catalog(settings))
    policy = load_mode_policies(settings.configurations_dir)[ProductionMode.BALANCED]
    estimate = estimator.estimate(sample_manifest(production_id=pid), policy)
    svc.reserve(_req(backend, pid, "0.30", scene_id="scene_01"))
    s = svc.summary(pid, estimate=estimate)
    assert s.estimated == estimate.total_estimated
    scenes = {r.key: r for r in s.by_scene}
    assert scenes["scene_01"].estimated == estimate.by_scene["scene_01"]
    assert scenes["scene_01"].reserved == D("0.3")
    assert len([k for k in scenes if k.startswith("scene_")]) == 5
    assert sum(r.estimated for r in s.by_provider) == estimate.total_estimated


def test_summary_of_unknown_production(backend) -> None:
    s = backend.service.summary("prod_unknown_" + uuid.uuid4().hex)
    assert s.limit == 0 and s.event_count == 0 and s.remaining == 0


def test_overview_and_credits(backend) -> None:
    svc = backend.service
    tenant = backend.new_tenant()
    p1 = backend.new_production("10.00", tenant_id=tenant)
    p2 = backend.new_production("5.00", tenant_id=tenant)
    other = backend.new_production("7.00")  # different tenant, must not leak
    e1 = svc.reserve(_req(backend, p1, "2.00", tenant_id=tenant))
    svc.commit(e1.event_id, actual_cost=D("1.50"), credits_used=D("15"))
    svc.reserve(_req(backend, p2, "1.00", tenant_id=tenant, attempt=2))
    svc.reserve(_req(backend, other, "3.00"))

    o = svc.overview(tenant)
    assert o.tenant_id == tenant
    assert o.production_count == 2
    assert o.total_limit == D("15")
    assert o.total_estimated == D("3")
    assert o.total_reserved == D("1")
    assert o.total_actual == D("1.5")
    assert o.retry_count == 1
    assert {r.key for r in o.by_production} == {p1, p2}
    assert {r.key for r in o.by_provider} == {"mock-video"}
    balances = {b.provider: b for b in o.credit_balances}
    assert set(balances) == set(SIMULATED_CREDIT_BALANCES)
    assert balances["mock-video"].balance == SIMULATED_CREDIT_BALANCES["mock-video"] - 15
    assert balances["mock-llm"].balance == SIMULATED_CREDIT_BALANCES["mock-llm"]
    assert all(b.is_estimated for b in balances.values())

    e3 = svc.reserve(_req(backend, p1, "1.00", tenant_id=tenant))
    svc.commit(e3.event_id, actual_cost=D("1.00"), credits_used=D("5"))
    after = {b.provider: b.balance for b in svc.credit_balances(tenant)}
    assert after["mock-video"] == SIMULATED_CREDIT_BALANCES["mock-video"] - 20
    untouched = {b.provider: b.balance for b in svc.credit_balances(backend.tenant_id)}
    assert untouched["mock-video"] == SIMULATED_CREDIT_BALANCES["mock-video"]


def test_concurrent_reservations_never_overspend(backend) -> None:
    """ENG-06: 25 threads reserve $1.00 each against a $10.00 cap."""
    svc = backend.service
    pid = backend.new_production("10.00")
    barrier = threading.Barrier(25)
    successes: list[str] = []
    failures: list[BaseException] = []
    lock = threading.Lock()

    def worker(i: int) -> None:
        req = _req(backend, pid, "1.00", key=f"{pid}:conc:{i}")
        barrier.wait()
        try:
            ev = svc.reserve(req)
        except BaseException as exc:
            with lock:
                failures.append(exc)
        else:
            with lock:
                successes.append(ev.event_id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert len(successes) == 10
    assert len(failures) == 15
    assert all(isinstance(f, BudgetExceededError) for f in failures)
    budget = svc.get_budget(pid)
    assert budget.reserved_amount == D("10.00")
    assert budget.actual_amount == 0
    assert len(svc.ledger(pid)) == 10


def test_factory_selects_backend() -> None:
    svc = build_budget_service(Settings(persistence_backend="memory"))
    assert isinstance(svc, InMemoryBudgetService)
    from cineforge.cost.postgres import PostgresBudgetService

    assert isinstance(build_budget_service(Settings()), PostgresBudgetService)
