"""Minimal MediaWiki Action API helper shared by Wikipedia and Wikimedia Commons."""

from __future__ import annotations

from typing import Any

import httpx

from cineforge.contracts.providers import ProviderError
from cineforge.providers.http import request_json

# API-level error codes (HTTP 200 with an "error" object) worth retrying later.
RETRYABLE_CODES = frozenset({"maxlag", "ratelimited", "readonly", "internal_api_error"})


def mediawiki_get(
    client: httpx.Client, api_url: str, params: dict[str, Any], *, provider: str
) -> dict[str, Any]:
    query = {"format": "json", "formatversion": "2", **params}
    body = request_json(client, "GET", api_url, provider=provider, params=query)
    error = body.get("error")
    if isinstance(error, dict):
        code = str(error.get("code") or "error")
        retryable = code in RETRYABLE_CODES or code.startswith("internal_api_error")
        raise ProviderError(
            f"{provider}: API error {code}: {error.get('info', '')}".rstrip(": "),
            retryable=retryable,
        )
    return body


def site_check(client: httpx.Client, api_url: str, *, provider: str) -> tuple[bool, str]:
    try:
        body = mediawiki_get(
            client,
            api_url,
            {"action": "query", "meta": "siteinfo", "siprop": "general"},
            provider=provider,
        )
    except ProviderError as exc:
        return False, str(exc)
    general = (body.get("query") or {}).get("general") or {}
    return True, f"reachable ({general.get('sitename') or api_url})"
