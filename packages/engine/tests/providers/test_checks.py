from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.api import ProviderTestResult
from cineforge.providers.checks import check_provider
from cineforge.providers.factory import build_provider_registry
from cineforge.providers.settings_store import (
    InMemoryProviderSettingsRepository,
    MemorySecretStore,
)
from provider_fakes import Recorder, json_response, wikimedia_handler

T = "tenant_demo"
KEY = "fake-ant-check-key-00005555"


def _registry(handler=wikimedia_handler, **settings):
    settings.setdefault("persistence_backend", "memory")
    cfg = Settings(**settings)
    rec = Recorder(handler)
    secrets = MemorySecretStore()
    registry = build_provider_registry(
        cfg,
        secrets=secrets,
        provider_settings=InMemoryProviderSettingsRepository(),
        http_client=rec.client(cfg),
    )
    return registry, rec, secrets


def test_mock_planned_and_unknown() -> None:
    registry, rec, _ = _registry()
    mock = check_provider(registry, "mock-llm", T)
    assert isinstance(mock, ProviderTestResult)
    assert (mock.ok, mock.detail, mock.paid_call) == (True, "mock provider (offline)", False)
    planned = check_provider(registry, "runway", T)
    assert planned.ok is False and "Phase 2" in planned.detail
    unknown = check_provider(registry, "nope", T)
    assert unknown.ok is False and unknown.detail == "unknown provider"
    assert rec.requests == []


def test_free_providers_call_their_check() -> None:
    def handler(request):
        if request.url.host == "api.openverse.org":
            return json_response(200, "openverse_search.json")
        return wikimedia_handler(request)

    registry, rec, _ = _registry(handler)
    for name in ("wikipedia", "wikimedia-commons", "openverse"):
        result = check_provider(registry, name, T)
        assert result.ok is True, result.detail
        assert result.provider == name and result.paid_call is False
        assert result.latency_ms >= 0
    assert [r.url.host for r in rec.requests] == [
        "en.wikipedia.org",
        "commons.wikimedia.org",
        "api.openverse.org",
    ]


def test_anthropic_check_uses_registry_key_and_is_free() -> None:
    def handler(request):
        assert request.url.path == "/v1/models"
        if request.headers.get("x-api-key") == KEY:
            return json_response(200, "anthropic_models.json")
        return json_response(401, "anthropic_401.json")

    registry, rec, secrets = _registry(handler)
    missing = check_provider(registry, "anthropic", T)
    assert missing.ok is False and "no API key" in missing.detail and rec.requests == []
    secrets.put(T, "anthropic", "fake-ant-wrong-key-000000")
    wrong = check_provider(registry, "anthropic", T)
    assert wrong.ok is False and "invalid or unauthorized API key" in wrong.detail
    secrets.put(T, "anthropic", KEY)
    good = check_provider(registry, "anthropic", T)
    assert good.ok is True and good.paid_call is False
    assert all(r.method == "GET" for r in rec.requests)


def test_check_never_raises() -> None:
    def boom(request):
        raise RuntimeError("transport exploded")

    registry, _, _ = _registry(boom)
    result = check_provider(registry, "wikipedia", T)
    assert result.ok is False and "RuntimeError" in result.detail
