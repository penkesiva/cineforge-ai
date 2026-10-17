"""Gemini on Sources: key check is free, and it does not take video routing."""

from __future__ import annotations

from decimal import Decimal

import pytest
from cineforge.contracts.providers import (
    KeySource,
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderRequest,
    ProviderStatus,
)
from cineforge.providers.checks import check_provider
from cineforge.providers.gemini import MODEL, NAME
from provider_fakes import json_response
from test_checks import _registry
from test_registry_routing import Env

T = "tenant_demo"
KEY = "fake-gemini-key-0000001234"
C = ProviderCapability


def _request() -> ProviderRequest:
    return ProviderRequest(
        tenant_id=T,
        production_id="prod_x",
        capability=C.VIDEO_GENERATION,
        model=MODEL,
        prompt="a pillar",
        parameters={"duration_sec": 6},
        idempotency_key="gemini-estimate-1",
    )


def test_gemini_starts_off_and_stays_behind_mock_video() -> None:
    env = Env(
        provider_mode="live",
        allow_paid_providers=True,
        gemini_api_key=KEY,
    )
    entry = env.entry(NAME)
    assert entry.display_name == "Google Gemini"
    assert entry.enabled is False
    assert entry.status == ProviderStatus.DISABLED
    assert entry.priority == 200
    assert entry.key_source == KeySource.ENVIRONMENT
    assert entry.key_hint == "...1234"
    assert KEY not in entry.model_dump_json()
    assert C.VIDEO_GENERATION in entry.capabilities
    assert env.registry.route(C.VIDEO_GENERATION, tenant_id=T).info.name == "mock-video"

    env.set(NAME, enabled=True, priority=200)
    ready = env.entry(NAME)
    assert ready.status == ProviderStatus.READY
    assert env.names(C.VIDEO_GENERATION)[0] == "mock-video"
    assert NAME in env.names(C.VIDEO_GENERATION)


def test_gemini_check_lists_models_and_does_not_spend() -> None:
    def handler(request):
        assert request.url.path == "/v1beta/models"
        assert request.headers.get("x-goog-api-key") == KEY
        assert request.method == "GET"
        return json_response(
            200,
            {
                "models": [
                    {"name": "models/veo-3.1-generate-preview"},
                    {"name": "models/gemini-2.5-flash"},
                ]
            },
        )

    registry, rec, _ = _registry(handler, gemini_api_key="")
    missing = check_provider(registry, NAME, T)
    assert missing.ok is False and "no API key" in missing.detail and rec.requests == []

    def denied(_request):
        return json_response(401, {"error": {"message": "API key not valid"}})

    registry, rec, secrets = _registry(denied, gemini_api_key="")
    secrets.put(T, NAME, "fake-gemini-wrong-key-000")
    bad = check_provider(registry, NAME, T)
    assert bad.ok is False and "invalid or unauthorized" in bad.detail
    assert bad.paid_call is False

    registry, rec, _ = _registry(handler, gemini_api_key=KEY)
    good = check_provider(registry, NAME, T)
    assert good.ok is True and good.paid_call is False
    assert "veo-3.1-generate-preview" in good.detail
    assert all(r.method == "GET" for r in rec.requests)


def test_gemini_estimate_is_seconds_and_invoke_is_blocked() -> None:
    registry, _, _ = _registry(gemini_api_key=KEY)
    provider = registry.get(NAME)
    usage = provider.estimate_usage(_request())
    assert usage.unit == PriceUnit.VIDEO_SECOND
    assert usage.units == Decimal(6)
    with pytest.raises(ProviderError, match="not switched"):
        provider.invoke(_request())
