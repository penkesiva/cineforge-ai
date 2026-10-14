"""Offline HTTP fakes for real-provider tests (httpx.MockTransport + JSON fixtures)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
from cineforge.config import Settings
from cineforge.contracts.providers import ProviderCapability, ProviderRequest
from cineforge.providers.http import build_http_client

FIXTURES = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "approved" / "providers"

Handler = Callable[[httpx.Request], httpx.Response]


def fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text())


def json_response(status: int, body: dict[str, Any] | str) -> httpx.Response:
    if isinstance(body, str):
        return httpx.Response(status, json=fixture(body))
    return httpx.Response(status, json=body)


class Recorder:
    """MockTransport handler that records requests and delegates to ``handler``."""

    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def client(self, settings: Settings | None = None) -> httpx.Client:
        return build_http_client(settings or Settings(), transport=httpx.MockTransport(self))


def wikimedia_handler(request: httpx.Request) -> httpx.Response:
    """Routes Wikipedia + Commons Action API calls to fixtures."""
    params = request.url.params
    if params.get("meta") == "siteinfo":
        return json_response(200, "wikimedia_siteinfo.json")
    if request.url.host == "commons.wikimedia.org":
        return json_response(200, "commons_search.json")
    if params.get("list") == "search":
        return json_response(200, "wikipedia_search.json")
    pageid = params.get("pageids")
    path = FIXTURES / f"wikipedia_extract_{pageid}.json"
    if path.exists():
        return json_response(200, path.name)
    return json_response(
        200, {"batchcomplete": True, "query": {"pages": [{"pageid": pageid, "missing": True}]}}
    )


def request_for(
    capability: ProviderCapability,
    model: str,
    *,
    prompt: str | None = "Eiffel Tower",
    key: str = "prod_t:RESEARCHING:a2:1",
    **parameters: Any,
) -> ProviderRequest:
    return ProviderRequest(
        tenant_id="tenant_demo",
        production_id="prod_t",
        capability=capability,
        model=model,
        prompt=prompt,
        parameters=parameters,
        idempotency_key=f"{key}:{model}",
    )
