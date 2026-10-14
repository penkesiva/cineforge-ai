"""Shared HTTP plumbing for real providers (sync ``httpx``).

Error mapping (drives the agents' bounded retries):

- timeouts, connection errors, HTTP 429, 5xx and Anthropic 529 -> ``retryable=True``
- 401 / 403 -> ``retryable=False``, "invalid or unauthorized API key"
- any other 4xx, or a non-JSON body -> ``retryable=False``

Messages never contain request headers (API keys live there).
"""

from __future__ import annotations

import hashlib
from typing import Any

import httpx

from cineforge.config import Settings
from cineforge.contracts.providers import ProviderError

MAX_ERROR_DETAIL = 300


def build_http_client(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """One client per process is enough: ``httpx.Client`` is thread-safe and pools
    connections. Tests pass ``transport=httpx.MockTransport(handler)``."""
    return httpx.Client(
        timeout=httpx.Timeout(settings.http_timeout_sec),
        headers={"User-Agent": settings.http_user_agent},
        transport=transport,
        follow_redirects=True,
    )


def local_request_id(provider: str, idempotency_key: str) -> str:
    """Stable ledger request id for APIs that do not return one."""
    digest = hashlib.sha256(f"{provider}:{idempotency_key}".encode()).hexdigest()
    return f"{provider}_{digest[:20]}"


def int_param(
    params: dict[str, Any], key: str, default: int, *, low: int, high: int, provider: str
) -> int:
    """Integer request parameter clamped to [low, high]; garbage is a non-retryable error."""
    try:
        value = int(params.get(key, default))
    except (TypeError, ValueError):
        raise ProviderError(f"{provider}: parameter {key!r} must be an integer") from None
    return max(low, min(value, high))


def is_retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()[:MAX_ERROR_DETAIL]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("info") or error.get("type")
            if message:
                return str(message)[:MAX_ERROR_DETAIL]
        elif isinstance(error, str):
            return error[:MAX_ERROR_DETAIL]
        for key in ("detail", "message"):
            if body.get(key):
                return str(body[key])[:MAX_ERROR_DETAIL]
    return response.text.strip()[:MAX_ERROR_DETAIL]


def raise_for_status(provider: str, response: httpx.Response) -> None:
    status = response.status_code
    if status < 400:
        return
    detail = _error_detail(response)
    if status in (401, 403):
        raise ProviderError(
            f"{provider}: HTTP {status} invalid or unauthorized API key ({detail})",
            retryable=False,
        )
    suffix = f": {detail}" if detail else ""
    if is_retryable_status(status):
        label = "overloaded" if status == 529 else "rate limited" if status == 429 else "error"
        raise ProviderError(f"{provider}: HTTP {status} {label}{suffix}", retryable=True)
    raise ProviderError(f"{provider}: HTTP {status}{suffix}", retryable=False)


def request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    provider: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a request and return the decoded JSON object, mapping failures to
    ``ProviderError``."""
    try:
        response = client.request(method, url, params=params, headers=headers, json=json)
    except httpx.TimeoutException as exc:
        raise ProviderError(
            f"{provider}: request timed out ({type(exc).__name__})", retryable=True
        ) from None
    except httpx.TransportError as exc:
        raise ProviderError(
            f"{provider}: connection error ({type(exc).__name__}: {exc})", retryable=True
        ) from None
    raise_for_status(provider, response)
    try:
        body = response.json()
    except ValueError:
        raise ProviderError(
            f"{provider}: response is not JSON (HTTP {response.status_code})", retryable=False
        ) from None
    if not isinstance(body, dict):
        raise ProviderError(f"{provider}: unexpected JSON payload", retryable=False)
    return body
