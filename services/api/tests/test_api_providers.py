"""Sources page API over the real provider registry (offline: no provider is invoked)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import ProviderCapability
from cineforge.runtime import Runtime, set_runtime
from cineforge_api.main import create_app
from fastapi.testclient import TestClient

FAKE_KEY = "sk-ant-test-0000000000000000wxyz"


def _client(**overrides) -> Iterator[TestClient]:
    settings = Settings(
        **(
            {
                "persistence_backend": "memory",
                "queue_backend": "inline",
                "anthropic_api_key": "",
                "allow_paid_providers": False,
            }
            | overrides
        )
    )
    rt = Runtime(settings)
    set_runtime(rt)
    with TestClient(create_app(settings)) as client:
        yield client
    set_runtime(None)


@pytest.fixture
def client() -> Iterator[TestClient]:
    yield from _client(provider_mode="mock")


@pytest.fixture
def live_client() -> Iterator[TestClient]:
    yield from _client(provider_mode="live")


def _group(overview: dict, capability: str) -> dict:
    return next(g for g in overview["groups"] if g["capability"] == capability)


def _entry(overview: dict, name: str) -> dict:
    return next(p for g in overview["groups"] for p in g["providers"] if p["name"] == name)


def test_overview_in_mock_mode(client: TestClient) -> None:
    body = client.get("/api/v1/providers").json()
    assert body["provider_mode"] == "mock"
    assert body["paid_providers_allowed"] is False
    assert body["secrets_backend"] == "memory"
    order = [g["capability"] for g in body["groups"]]
    assert order == [c.value for c in ProviderCapability if c.value in order]
    llm = _group(body, "llm_text")
    assert llm["label"] == "Reasoning (LLM)"
    assert llm["active_provider"] == "mock-llm"
    assert llm["providers"][0]["status"] == "ready"
    assert _entry(body, "anthropic")["status"] == "blocked_mock_mode"
    assert _entry(body, "wikipedia")["status"] == "blocked_mock_mode"
    assert _entry(body, "pexels")["status"] == "planned"
    assert _group(body, "web_research")["active_provider"] == "mock-research"


def test_live_mode_routes_free_sources_and_gates_paid(live_client: TestClient) -> None:
    body = live_client.get("/api/v1/providers").json()
    assert _group(body, "web_research")["active_provider"] == "wikipedia"
    assert _group(body, "media_search")["active_provider"] in {"wikimedia-commons", "openverse"}
    anthropic = _entry(body, "anthropic")
    # Paid providers are off by default even with a key.
    assert anthropic["enabled"] is False and anthropic["status"] == "disabled"
    assert _group(body, "llm_text")["active_provider"] == "mock-llm"

    enabled = live_client.patch("/api/v1/providers/anthropic", json={"enabled": True}).json()
    assert enabled["status"] == "blocked_paid_off"


def test_enable_disable_and_priority(client: TestClient) -> None:
    res = client.patch("/api/v1/providers/mock-llm", json={"enabled": False})
    assert res.status_code == 200
    assert res.json()["status"] == "disabled"
    body = client.get("/api/v1/providers").json()
    assert _group(body, "llm_text")["active_provider"] is None
    res = client.patch("/api/v1/providers/mock-llm", json={"enabled": True, "priority": 5})
    assert res.json()["enabled"] is True and res.json()["priority"] == 5
    assert client.patch("/api/v1/providers/mock-llm", json={"priority": 5000}).status_code == 422
    assert client.patch("/api/v1/providers/pexels", json={"enabled": True}).status_code == 409
    assert client.patch("/api/v1/providers/nope", json={"enabled": True}).status_code == 404


def test_keys_are_write_only(live_client: TestClient) -> None:
    res = live_client.put("/api/v1/providers/anthropic/key", json={"api_key": FAKE_KEY})
    assert res.status_code == 200
    assert FAKE_KEY not in res.text
    entry = res.json()
    assert entry["key_source"] == "stored" and entry["key_hint"] == "...wxyz"
    overview = live_client.get("/api/v1/providers").text
    assert FAKE_KEY not in overview

    cleared = live_client.delete("/api/v1/providers/anthropic/key").json()
    assert cleared["key_source"] == "none" and cleared["key_hint"] is None

    no_key = live_client.put("/api/v1/providers/wikipedia/key", json={"api_key": FAKE_KEY})
    assert no_key.status_code == 422
    short = live_client.put("/api/v1/providers/anthropic/key", json={"api_key": "short"})
    assert short.status_code == 422
    assert (
        live_client.put("/api/v1/providers/pexels/key", json={"api_key": FAKE_KEY}).status_code
        == 409
    )


def test_connectivity_checks_offline(client: TestClient) -> None:
    mock = client.post("/api/v1/providers/mock-llm/test").json()
    assert mock["ok"] is True and mock["paid_call"] is False
    planned = client.post("/api/v1/providers/pexels/test").json()
    assert planned["ok"] is False and "planned" in planned["detail"]
    assert client.post("/api/v1/providers/nope/test").status_code == 404
