from __future__ import annotations

from decimal import Decimal

import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import (
    PriceUnit,
    Provider,
    ProviderCapability,
    ProviderError,
    ProviderRegistry,
    ProviderRequest,
    UnsupportedCapabilityError,
)
from cineforge.cost.factory import load_price_catalog
from cineforge.providers.factory import build_provider_registry
from cineforge.providers.mock import MOCK_SPECS, MockProvider, build_mock_providers
from cineforge.providers.registry import InMemoryProviderRegistry

C = ProviderCapability


def _req(cap: C, model: str, key: str = "prod_x:GENERATING:a7:shot:1", **kw) -> ProviderRequest:
    return ProviderRequest(
        tenant_id="tenant_demo",
        production_id="prod_x",
        capability=cap,
        model=model,
        idempotency_key=key,
        **kw,
    )


def _provider(name: str, failure_rate: float = 0.0) -> MockProvider:
    return next(p for p in build_mock_providers(failure_rate=failure_rate) if p.info.name == name)


def test_every_catalog_entry_has_a_mock() -> None:
    catalog = load_price_catalog(Settings())
    providers = {p.info.name: p for p in build_mock_providers()}
    for entry in catalog.entries():
        provider = providers[entry.provider]
        assert entry.model in provider.info.models
        assert entry.capability in provider.info.capabilities
        params = {"duration_sec": 2} if entry.unit == PriceUnit.VIDEO_SECOND else {}
        usage = provider.estimate_usage(
            _req(entry.capability, entry.model, prompt="hello", parameters=params)
        )
        assert usage.unit == entry.unit
    assert len(providers) == len(MOCK_SPECS) == 9
    assert all(p.info.is_mock and not p.info.is_paid for p in providers.values())
    assert all(isinstance(p, Provider) for p in providers.values())


def test_usage_rules() -> None:
    llm = _provider("mock-llm")
    usage = llm.estimate_usage(
        _req(C.LLM_TEXT, "mock-llm-standard", prompt="x" * 400, parameters={"max_tokens": 600})
    )
    assert usage.units == Decimal("0.7")  # (100 + 600) tokens / 1000
    default = llm.estimate_usage(_req(C.LLM_TEXT, "mock-llm-standard", prompt=""))
    assert default.units == Decimal("0.8")

    video = _provider("mock-video")
    req = _req(C.VIDEO_GENERATION, "mock-video-cinematic", parameters={"duration_sec": 4.5})
    assert video.estimate_usage(req).units == Decimal("4.5")
    with pytest.raises(ProviderError):
        video.estimate_usage(_req(C.IMAGE_TO_VIDEO, "mock-video-draft"))

    tts = _provider("mock-voice")
    assert tts.estimate_usage(_req(C.VOICE_TTS, "mock-tts-v1", prompt="a" * 250)).units == Decimal(
        "0.25"
    )
    assert (
        _provider("mock-music").estimate_usage(_req(C.MUSIC_GENERATION, "mock-music-v1")).units == 1
    )
    assert (
        _provider("mock-image").estimate_usage(_req(C.IMAGE_GENERATION, "mock-image-v1")).units == 1
    )
    lip = _provider("mock-lipsync").estimate_usage(
        _req(C.LIP_SYNC, "mock-lipsync-v1", parameters={"duration_sec": 3})
    )
    assert lip.units == 3 and lip.credits == Decimal("24")


def test_invoke_is_deterministic_and_bounded() -> None:
    llm = _provider("mock-llm")
    req = _req(C.LLM_TEXT, "mock-llm-standard", prompt="Tell me about 1889")
    a, b = llm.invoke(req), llm.invoke(req)
    assert a == b.model_copy(update={})
    assert a.provider_request_id.startswith("mockreq_")
    assert a.output_data["mock"] is True
    other = llm.invoke(req.model_copy(update={"idempotency_key": "other"}))
    assert other.provider_request_id != a.provider_request_id
    estimate = llm.estimate_usage(req).units
    for i in range(50):
        r = llm.invoke(req.model_copy(update={"idempotency_key": f"k{i}"}))
        assert estimate * Decimal("0.9") - Decimal("0.000001") <= r.usage.units
        assert r.usage.units <= estimate * Decimal("1.05") + Decimal("0.000001")
    # Counted units never vary.
    music = _provider("mock-music").invoke(_req(C.MUSIC_GENERATION, "mock-music-v1"))
    assert music.usage.units == 1


def test_invalid_model_or_capability() -> None:
    video = _provider("mock-video")
    with pytest.raises(ProviderError) as info:
        video.invoke(_req(C.VIDEO_GENERATION, "nope", parameters={"duration_sec": 1}))
    assert info.value.retryable is False
    with pytest.raises(ProviderError):
        video.invoke(_req(C.LLM_TEXT, "mock-video-draft"))


def test_failure_injection() -> None:
    assert _provider("mock-video", 0.0).invoke(
        _req(C.IMAGE_TO_VIDEO, "mock-video-draft", parameters={"duration_sec": 1})
    )
    flaky = _provider("mock-video", 0.5)
    outcomes = {}
    for attempt in range(1, 41):
        key = f"prod_x:GENERATING:a7:shot_01:{attempt}:mock-video:mock-video-draft"
        req = _req(C.IMAGE_TO_VIDEO, "mock-video-draft", key=key, parameters={"duration_sec": 1})
        try:
            flaky.invoke(req)
            outcomes[key] = "ok"
        except ProviderError as exc:
            assert exc.retryable is True
            outcomes[key] = "fail"
        # Same key always behaves the same.
        try:
            flaky.invoke(req)
            again = "ok"
        except ProviderError:
            again = "fail"
        assert again == outcomes[key]
    assert 5 < list(outcomes.values()).count("fail") < 35
    assert "ok" in outcomes.values()
    # Non-media providers never fail.
    llm = _provider("mock-llm", 0.5)
    for i in range(20):
        llm.invoke(_req(C.LLM_TEXT, "mock-llm-standard", key=f"k{i}"))


def test_registry_routing() -> None:
    registry = build_provider_registry(Settings(persistence_backend="memory"))
    assert isinstance(registry, ProviderRegistry)
    assert registry.for_capability(C.IMAGE_TO_VIDEO).info.name == "mock-video"
    assert registry.for_capability(C.LLM_TEXT).info.name == "mock-llm"
    assert registry.get("mock-voice").info.capabilities == [C.VOICE_TTS]
    assert len(registry.list()) == 9
    with pytest.raises(UnsupportedCapabilityError):
        registry.for_capability(C.TRANSCRIPTION)
    with pytest.raises(LookupError):
        registry.get("nope")
    with pytest.raises(ValueError):
        registry.register(_provider("mock-llm"))


def test_registry_first_registered_wins() -> None:
    a, b = _provider("mock-video"), _provider("mock-image")
    b.info = b.info.model_copy(update={"name": "mock-video-2", "capabilities": [C.IMAGE_TO_VIDEO]})
    registry = InMemoryProviderRegistry([a, b])
    assert registry.for_capability(C.IMAGE_TO_VIDEO) is a
    empty = InMemoryProviderRegistry()
    with pytest.raises(UnsupportedCapabilityError):
        empty.for_capability(C.LLM_TEXT)


def test_failure_rate_from_settings() -> None:
    registry = build_provider_registry(Settings(mock_failure_rate=0.25))
    assert registry.get("mock-video").failure_rate == Decimal("0.25")
