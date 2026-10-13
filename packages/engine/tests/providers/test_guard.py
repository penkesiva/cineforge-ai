from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from cineforge.config import Settings
from cineforge.contracts.common import AgentId, money
from cineforge.contracts.cost import (
    BudgetExceededError,
    LedgerStatus,
    PriceCatalog,
    UnknownPriceError,
)
from cineforge.contracts.providers import (
    PaidCallGuard,
    PaidProviderNotAllowedError,
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from cineforge.cost.catalog import YamlPriceCatalog
from cineforge.cost.factory import load_price_catalog
from cineforge.cost.memory import InMemoryBudgetService
from cineforge.providers.factory import build_paid_call_guard
from cineforge.providers.mock import build_mock_providers

C = ProviderCapability
PID = "prod_guard_test"


class SpyBudget:
    """Wraps the memory budget and records the call sequence."""

    def __init__(self, calls: list[str]) -> None:
        self.inner = InMemoryBudgetService()
        self.calls = calls

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self.inner, name)
        if name in {"reserve", "commit", "release"}:

            def wrapped(*args: Any, **kwargs: Any) -> Any:
                self.calls.append(name)
                return attr(*args, **kwargs)

            return wrapped
        return attr


class SpyProvider:
    def __init__(self, inner: Any, calls: list[str], *, error: BaseException | None = None):
        self.inner = inner
        self.info = inner.info
        self.calls = calls
        self.error = error

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        self.calls.append("estimate")
        return self.inner.estimate_usage(request)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append("invoke")
        if self.error is not None:
            raise self.error
        return self.inner.invoke(request)


class FakePaidProvider:
    """A 'real' vendor stand-in: is_paid=True, no network."""

    info = ProviderInfo(
        name="paid-vendor",
        display_name="Paid Vendor",
        capabilities=[C.IMAGE_GENERATION],
        models=["pv-1"],
        is_mock=False,
        is_paid=True,
    )

    def __init__(self) -> None:
        self.invocations = 0

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.IMAGE)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        self.invocations += 1
        return ProviderResponse(
            provider="paid-vendor",
            model="pv-1",
            capability=C.IMAGE_GENERATION,
            provider_request_id="pv_1",
            usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.IMAGE),
        )


def _mock(name: str, failure_rate: float = 0.0):
    return next(p for p in build_mock_providers(failure_rate=failure_rate) if p.info.name == name)


def _video_request(key: str = f"{PID}:GENERATING:a7:shot_01:1:mock-video:mock-video-draft"):
    return ProviderRequest(
        tenant_id="tenant_demo",
        production_id=PID,
        scene_id="scene_01",
        shot_id="scene_01_shot_01",
        capability=C.IMAGE_TO_VIDEO,
        model="mock-video-draft",
        parameters={"duration_sec": 4},
        idempotency_key=key,
    )


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def budget(calls: list[str]) -> SpyBudget:
    spy = SpyBudget(calls)
    spy.inner.create_budget(tenant_id="tenant_demo", production_id=PID, limit=Decimal("10"))
    return spy


@pytest.fixture
def catalog() -> PriceCatalog:
    return load_price_catalog(Settings())


def _guard(budget, catalog, **settings: Any) -> PaidCallGuard:
    return build_paid_call_guard(Settings(**settings), budget, catalog)


def test_reserves_before_invoke_and_commits(budget, catalog, calls) -> None:
    guard = _guard(budget, catalog)
    assert isinstance(guard, PaidCallGuard)
    provider = SpyProvider(_mock("mock-video"), calls)
    response, event = guard.call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert calls == ["estimate", "reserve", "invoke", "commit"]
    assert event.status == LedgerStatus.COMMITTED
    assert event.estimated_cost == Decimal("0.2")  # 4 s x $0.05
    assert event.actual_cost == money(response.usage.units * Decimal("0.05"))
    assert event.provider_request_id == response.provider_request_id
    assert event.credits_used == response.usage.credits
    assert event.unit_price_version == "mock-2026-10"
    assert event.scene_id == "scene_01" and event.shot_id == "scene_01_shot_01"
    b = budget.get_budget(PID)
    assert b.reserved_amount == 0 and b.actual_amount == event.actual_cost


def test_budget_exceeded_never_invokes(budget, catalog, calls) -> None:
    budget.inner.set_limit(PID, Decimal("0.10"))
    provider = SpyProvider(_mock("mock-video"), calls)
    with pytest.raises(BudgetExceededError):
        _guard(budget, catalog).call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert "invoke" not in calls
    assert budget.ledger(PID) == []


def test_provider_error_releases_as_failed(budget, catalog, calls) -> None:
    provider = SpyProvider(
        _mock("mock-video"), calls, error=ProviderError("upstream 503", retryable=True)
    )
    with pytest.raises(ProviderError):
        _guard(budget, catalog).call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert calls == ["estimate", "reserve", "invoke", "release"]
    (event,) = budget.ledger(PID)
    assert event.status == LedgerStatus.FAILED
    assert budget.get_budget(PID).reserved_amount == 0


def test_other_exception_releases(budget, catalog, calls) -> None:
    provider = SpyProvider(_mock("mock-video"), calls, error=RuntimeError("bug"))
    with pytest.raises(RuntimeError):
        _guard(budget, catalog).call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    (event,) = budget.ledger(PID)
    assert event.status == LedgerStatus.RELEASED
    assert budget.get_budget(PID).reserved_amount == 0


def test_injected_failure_then_retry_succeeds(budget, catalog) -> None:
    guard = _guard(budget, catalog)
    provider = _mock("mock-video", failure_rate=0.5)
    outcomes = []
    for attempt in range(1, 11):
        key = f"{PID}:GENERATING:a7:shot_01:{attempt}:mock-video:mock-video-draft"
        try:
            guard.call(
                provider,
                _video_request(key),
                agent_id=AgentId.VISUAL_PRODUCTION,
                attempt=attempt,
                retry_reason="transient" if attempt > 1 else None,
            )
            outcomes.append("ok")
        except ProviderError:
            outcomes.append("fail")
    assert "ok" in outcomes and "fail" in outcomes
    statuses = [e.status for e in budget.ledger(PID)]
    assert statuses.count(LedgerStatus.FAILED) == outcomes.count("fail")
    assert budget.summary(PID).retry_count == 9


def test_paid_provider_blocked_by_default(budget, catalog, calls) -> None:
    paid = FakePaidProvider()
    req = ProviderRequest(
        tenant_id="tenant_demo",
        production_id=PID,
        capability=C.IMAGE_GENERATION,
        model="pv-1",
        idempotency_key="k-paid",
    )
    with pytest.raises(PaidProviderNotAllowedError):
        _guard(budget, catalog).call(paid, req, agent_id=AgentId.VISUAL_PRODUCTION)
    assert paid.invocations == 0 and calls == []


def test_paid_provider_allowed_when_enabled(budget, calls) -> None:
    catalog = YamlPriceCatalog.from_mapping(
        {
            "version": "test-paid",
            "effective_from": "2026-10-01",
            "simulated": False,
            "entries": [
                {"provider": "paid-vendor", "model": "pv-1", "capability": "image_generation",
                 "unit": "image", "unit_price": 0.5},
            ],
        }
    )  # fmt: skip
    paid = FakePaidProvider()
    req = ProviderRequest(
        tenant_id="tenant_demo",
        production_id=PID,
        capability=C.IMAGE_GENERATION,
        model="pv-1",
        idempotency_key="k-paid",
    )
    response, event = _guard(budget, catalog, allow_paid_providers=True).call(
        paid, req, agent_id=AgentId.VISUAL_PRODUCTION
    )
    assert paid.invocations == 1
    assert event.actual_cost == Decimal("0.5") and calls == ["reserve", "commit"]
    assert response.provider_request_id == "pv_1"


def test_unknown_price_means_no_call(budget, calls) -> None:
    empty = YamlPriceCatalog([], version="empty")
    provider = SpyProvider(_mock("mock-video"), calls)
    with pytest.raises(UnknownPriceError):
        _guard(budget, empty).call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert calls == ["estimate"]
    assert budget.ledger(PID) == []


def test_idempotent_replay_does_not_invoke_twice(budget, catalog, calls) -> None:
    guard = _guard(budget, catalog)
    provider = SpyProvider(_mock("mock-video"), calls)
    first, ev1 = guard.call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    second, ev2 = guard.call(provider, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert calls.count("invoke") == 1
    assert ev1.event_id == ev2.event_id
    assert second.cached is True and second.provider_request_id == first.provider_request_id
    assert second.usage.units == first.usage.units
    assert len(budget.ledger(PID)) == 1


def test_replay_of_failed_attempt_is_refused(budget, catalog, calls) -> None:
    guard = _guard(budget, catalog)
    failing = SpyProvider(_mock("mock-video"), calls, error=ProviderError("x", retryable=True))
    with pytest.raises(ProviderError):
        guard.call(failing, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    ok = SpyProvider(_mock("mock-video"), calls)
    with pytest.raises(ProviderError, match="new attempt key"):
        guard.call(ok, _video_request(), agent_id=AgentId.VISUAL_PRODUCTION)
    assert calls.count("invoke") == 1


def test_capability_mismatch_rejected(budget, catalog, calls) -> None:
    req = _video_request().model_copy(update={"capability": C.LLM_TEXT})
    with pytest.raises(LookupError):
        _guard(budget, catalog).call(
            SpyProvider(_mock("mock-video"), calls), req, agent_id=AgentId.VISUAL_PRODUCTION
        )
    assert calls == []
