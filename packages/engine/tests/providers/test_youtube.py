"""YouTube Data API mapping: quota is not an invalid key, retries are bounded."""

from __future__ import annotations

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import ProviderCapability, ProviderError, ProviderRequest
from cineforge.providers.youtube import (
    MODEL,
    YouTubeProvider,
    parse_duration,
)

KEY = "yt-test-key-not-real"


def _provider(handler, *, sleeper=lambda _s: None) -> YouTubeProvider:
    calls = {"n": 0}

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.url.params.get("key") == KEY
        return handler(request, calls["n"])

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return YouTubeProvider(
        Settings(),
        key_resolver=lambda _t: KEY,
        client=client,
        sleeper=sleeper,
    )


def _req(**params) -> ProviderRequest:
    return ProviderRequest(
        tenant_id="tenant_demo",
        production_id="discovery:run",
        capability=ProviderCapability.VIDEO_DISCOVERY,
        model=MODEL,
        parameters=params,
        idempotency_key="yt-1",
    )


def test_duration_and_missing_counts() -> None:
    assert parse_duration("PT1H2M3S") == 3723
    assert parse_duration("P1D") is None
    body = {
        "items": [
            {
                "id": "abcdefghijk",
                "snippet": {
                    "title": "Bells",
                    "channelId": "ch",
                    "channelTitle": "Archive",
                    "publishedAt": "2026-10-01T00:00:00Z",
                    "categoryId": "22",
                    "thumbnails": {"medium": {"url": "https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg"}},
                },
                "statistics": {"viewCount": "10"},
                "contentDetails": {"duration": "not-iso"},
            }
        ]
    }

    def handler(_request, _n):
        return httpx.Response(200, json=body)

    response = _provider(handler).invoke(_req(operation="popular", region_code="US", page_size=5))
    item = response.output_data["items"][0]
    assert item["view_count"] == 10
    assert item["like_count"] is None
    assert item["duration_sec"] is None
    assert response.output_data["warnings"] == ["unreadable duration for abcdefghijk"]


def test_quota_403_is_not_an_invalid_key() -> None:
    def handler(_request, _n):
        return httpx.Response(
            403,
            json={"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}},
        )

    with pytest.raises(ProviderError, match="quota") as raised:
        _provider(handler).invoke(_req(operation="popular"))
    assert raised.value.retryable is False
    assert "invalid" not in str(raised.value).lower()


def test_retries_count_and_then_stop() -> None:
    seen: list[int] = []

    def handler(_request, n):
        seen.append(n)
        if n < 3:
            return httpx.Response(500, json={"error": {"message": "down"}})
        return httpx.Response(200, json={"items": []})

    response = _provider(handler).invoke(_req(operation="popular"))
    assert response.output_data["items"] == []
    assert seen == [1, 2, 3]
