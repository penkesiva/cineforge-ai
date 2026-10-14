from __future__ import annotations

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import ProviderError
from cineforge.providers.http import build_http_client, int_param, request_json
from cineforge.providers.mediawiki import mediawiki_get
from provider_fakes import Recorder

URL = "https://api.example.test/v1/thing"


def _client(status: int, body: object = None, *, raise_exc: Exception | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if raise_exc is not None:
            raise raise_exc
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body if body is not None else {})

    return Recorder(handler)


def test_client_sends_user_agent_and_uses_timeout() -> None:
    settings = Settings(http_user_agent="CineForgeTest/1.0 (test@example.com)", http_timeout_sec=7)
    rec = _client(200, {"ok": True})
    client = rec.client(settings)
    assert client.timeout.read == 7
    assert request_json(client, "GET", URL, provider="x") == {"ok": True}
    assert rec.requests[0].headers["user-agent"] == "CineForgeTest/1.0 (test@example.com)"
    assert isinstance(build_http_client(settings), httpx.Client)


@pytest.mark.parametrize(
    ("status", "retryable", "fragment"),
    [
        (429, True, "rate limited"),
        (500, True, "HTTP 500"),
        (503, True, "HTTP 503"),
        (529, True, "overloaded"),
        (401, False, "invalid or unauthorized API key"),
        (403, False, "invalid or unauthorized API key"),
        (400, False, "HTTP 400"),
        (404, False, "HTTP 404"),
    ],
)
def test_status_mapping(status: int, retryable: bool, fragment: str) -> None:
    rec = _client(status, {"type": "error", "error": {"type": "x", "message": "upstream says no"}})
    with pytest.raises(ProviderError) as info:
        request_json(rec.client(), "POST", URL, provider="vendor", headers={"x-api-key": "sk-1"})
    assert info.value.retryable is retryable
    assert fragment in str(info.value) and "upstream says no" in str(info.value)
    assert str(info.value).startswith("vendor:")
    assert "sk-1" not in str(info.value)


def test_timeout_and_connection_errors_are_retryable() -> None:
    for exc in (httpx.ReadTimeout("slow"), httpx.ConnectError("refused")):
        rec = _client(200, raise_exc=exc)
        with pytest.raises(ProviderError) as info:
            request_json(rec.client(), "GET", URL, provider="vendor")
        assert info.value.retryable is True


def test_non_json_body_is_not_retryable() -> None:
    rec = _client(200, "<html>oops</html>")
    with pytest.raises(ProviderError, match="not JSON") as info:
        request_json(rec.client(), "GET", URL, provider="vendor")
    assert info.value.retryable is False


def test_mediawiki_api_errors() -> None:
    rec = _client(200, {"error": {"code": "maxlag", "info": "Waiting for a database server"}})
    with pytest.raises(ProviderError, match="maxlag") as info:
        mediawiki_get(rec.client(), URL, {"action": "query"}, provider="wikipedia")
    assert info.value.retryable is True
    rec = _client(200, {"error": {"code": "badvalue", "info": "Unrecognized value"}})
    with pytest.raises(ProviderError) as info:
        mediawiki_get(rec.client(), URL, {"action": "query"}, provider="wikipedia")
    assert info.value.retryable is False
    assert rec.requests[0].url.params["format"] == "json"
    assert rec.requests[0].url.params["formatversion"] == "2"


def test_int_param() -> None:
    assert int_param({}, "n", 4, low=1, high=8, provider="p") == 4
    assert int_param({"n": "99"}, "n", 4, low=1, high=8, provider="p") == 8
    assert int_param({"n": 0}, "n", 4, low=1, high=8, provider="p") == 1
    with pytest.raises(ProviderError):
        int_param({"n": "lots"}, "n", 4, low=1, high=8, provider="p")
