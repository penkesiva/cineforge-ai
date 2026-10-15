"""Higgsfield sign-in routes: start, callback redirect, status, disconnect. The auth
server is faked; tokens never appear in responses."""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cineforge.providers import factory
from cineforge.providers.oauth import McpOAuth

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "packages/engine/tests/providers"))
from test_higgsfield_connector import MCP, FakeAuthServer


@pytest.fixture
def server(monkeypatch) -> FakeAuthServer:
    fake = FakeAuthServer()

    def build(settings, secrets, http=None) -> McpOAuth:
        return McpOAuth(
            provider="higgsfield",
            resource_url=MCP,
            redirect_uri=f"{settings.api_public_url}/api/v1/providers/higgsfield/oauth/callback",
            secrets=secrets,
            http=httpx.Client(transport=httpx.MockTransport(fake.handler)),
        )

    monkeypatch.setattr(factory, "build_higgsfield_auth", build)
    from cineforge_api.routers import connectors

    monkeypatch.setattr(connectors, "build_higgsfield_auth", build)
    return fake


def test_sign_in_round_trip(api, server) -> None:
    status = api.client.get("/api/v1/providers/higgsfield/connection").json()
    assert status["connected"] is False

    start = api.client.post("/api/v1/providers/higgsfield/oauth/start")
    assert start.status_code == 200
    url = start.json()["authorize_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    assert "127.0.0.1:8000" in parse_qs(urlsplit(url).query)["redirect_uri"][0]

    done = api.client.get(
        "/api/v1/providers/higgsfield/oauth/callback",
        params={"code": "abc", "state": state},
        follow_redirects=False,
    )
    assert done.status_code == 303
    assert done.headers["location"].endswith("/sources?connected=higgsfield")

    status = api.client.get("/api/v1/providers/higgsfield/connection").json()
    assert status["connected"] is True
    assert "access" not in str(status)
    assert "access-1" in (api.rt.secrets.get(api.rt.settings.default_tenant_id, "higgsfield"))

    assert api.client.delete("/api/v1/providers/higgsfield/oauth").json()["connected"] is False


def test_callback_with_bad_state_redirects_with_error(api, server) -> None:
    api.client.post("/api/v1/providers/higgsfield/oauth/start")
    done = api.client.get(
        "/api/v1/providers/higgsfield/oauth/callback",
        params={"code": "abc", "state": "forged"},
        follow_redirects=False,
    )
    assert "connect_error=" in done.headers["location"]
    assert api.client.get("/api/v1/providers/higgsfield/connection").json()["connected"] is False


def test_unknown_sign_in_provider_is_404(api, server) -> None:
    assert api.client.post("/api/v1/providers/anthropic/oauth/start").status_code == 404
