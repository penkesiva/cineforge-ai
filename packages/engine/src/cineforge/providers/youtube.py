"""YouTube Data API v3 discovery, plus an offline mock with the same shape.

Chart mode uses videos.list mostPopular. Recent mode uses search.list ordered by
date, then hydrates IDs with videos.list. No scraping, downloads, or ranking.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from cineforge.config import Settings
from cineforge.contracts.common import utcnow
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from cineforge.providers.http import build_http_client

NAME = "youtube"
MOCK_NAME = "mock-youtube"
MODEL = "youtube-data-v3"
MOCK_MODEL = "mock-youtube-v1"
API = "https://www.googleapis.com/youtube/v3"
_DURATION = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"}
_DISABLED_REASONS = {"accessNotConfigured", "forbidden", "insufficientPermissions"}
_KEY_REASONS = {"keyInvalid", "badRequest", "ipRefererBlocked", "apiKeyInvalid"}

Reserve = Callable[[str], None]
Sleeper = Callable[[float], None]
_RESERVE: ContextVar[Reserve | None] = ContextVar("youtube_reserve", default=None)


def bind_reserve(reserve: Reserve) -> object:
    return _RESERVE.set(reserve)


def reset_reserve(token: object) -> None:
    _RESERVE.reset(token)  # type: ignore[arg-type]


def _active_reserve(fallback: Reserve) -> Reserve:
    return _RESERVE.get() or fallback


class QuotaExhausted(ProviderError):
    def __init__(self, method: str) -> None:
        super().__init__(
            f"YouTube {method} allowance for today is used up. Raise it only up to the "
            "Cloud project's real quota, or wait until tomorrow.",
            retryable=False,
        )
        self.method = method


def credential_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def parse_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = _DURATION.fullmatch(value)
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def _count(stats: dict[str, Any], name: str) -> int | None:
    raw = stats.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def candidate_from_video(
    item: dict[str, Any], *, mode: str, retrieved_at: datetime
) -> dict[str, Any] | None:
    video_id = str(item.get("id") or "")
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    if not video_id or not snippet:
        return None
    stats = item.get("statistics") if isinstance(item.get("statistics"), dict) else {}
    details = item.get("contentDetails") if isinstance(item.get("contentDetails"), dict) else {}
    thumbs = snippet.get("thumbnails") if isinstance(snippet.get("thumbnails"), dict) else {}
    thumb = None
    for key in ("medium", "high", "default"):
        row = thumbs.get(key)
        if isinstance(row, dict) and row.get("url"):
            thumb = str(row["url"])
            break
    return {
        "platform": "youtube",
        "video_id": video_id,
        "watch_url": watch_url(video_id),
        "title": str(snippet.get("title") or ""),
        "channel_id": str(snippet.get("channelId") or ""),
        "channel_name": str(snippet.get("channelTitle") or ""),
        "published_at": _published(snippet.get("publishedAt")),
        "duration_sec": parse_duration(
            details.get("duration") if isinstance(details, dict) else None
        ),
        "category_id": snippet.get("categoryId"),
        "thumbnail_url": thumb,
        "view_count": _count(stats, "viewCount"),
        "like_count": _count(stats, "likeCount"),
        "comment_count": _count(stats, "commentCount"),
        "retrieved_at": retrieved_at,
        "source_mode": mode,
    }


def _redact(text: str) -> str:
    return re.sub(r"key=[^&\s]+", "key=REDACTED", text)


class _YouTubeHttp:
    def __init__(
        self, settings: Settings, *, client: httpx.Client | None, sleeper: Sleeper
    ) -> None:
        self.settings = settings
        self._client = client
        self.sleeper = sleeper

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_http_client(self.settings)
        return self._client

    def get(
        self, method: str, path: str, params: dict[str, Any], *, reserve: Reserve
    ) -> dict[str, Any]:
        last: ProviderError | None = None
        for attempt in range(3):
            reserve(method)
            try:
                response = self.client.get(f"{API}/{path}", params=params)
            except httpx.TimeoutException:
                last = ProviderError("youtube: request timed out", retryable=True)
            except httpx.TransportError as exc:
                last = ProviderError(
                    f"youtube: connection error ({type(exc).__name__})", retryable=True
                )
            else:
                if response.status_code < 400:
                    try:
                        body = response.json()
                    except ValueError as exc:
                        raise ProviderError(
                            "youtube: response is not JSON", retryable=False
                        ) from exc
                    if not isinstance(body, dict):
                        raise ProviderError("youtube: unexpected JSON payload", retryable=False)
                    return body
                last = _http_error(response)
            if last is None or not last.retryable or attempt == 2:
                raise last
            self.sleeper(min(2.0, 0.25 * (2**attempt)))
        raise last or ProviderError("youtube: request failed", retryable=False)


def _http_error(response: httpx.Response) -> ProviderError:
    reasons: list[str] = []
    message = ""
    try:
        body = response.json()
    except ValueError:
        body = None
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            for row in error.get("errors") or []:
                if isinstance(row, dict) and row.get("reason"):
                    reasons.append(str(row["reason"]))
    status = response.status_code
    if any(reason in _QUOTA_REASONS for reason in reasons):
        return ProviderError(
            "YouTube quota is exhausted for this Cloud project. It is not a bad key.",
            retryable=False,
        )
    if status in (401, 403) and any(reason in _DISABLED_REASONS for reason in reasons):
        return ProviderError(
            "YouTube Data API is disabled or blocked for this key.",
            retryable=False,
        )
    if status in (400, 401, 403) and (
        any(reason in _KEY_REASONS for reason in reasons) or "API key" in message
    ):
        return ProviderError("YouTube rejected the API key.", retryable=False)
    if status == 429 or status >= 500:
        return ProviderError(f"youtube: HTTP {status}", retryable=True)
    detail = _redact(message)[:180]
    suffix = f": {detail}" if detail else ""
    return ProviderError(f"youtube: HTTP {status}{suffix}", retryable=False)


class YouTubeProvider:
    def __init__(
        self,
        settings: Settings,
        *,
        key_resolver: Callable[[str], str | None],
        client: httpx.Client | None = None,
        sleeper: Sleeper | None = None,
        reserve: Reserve | None = None,
    ) -> None:
        self.settings = settings
        self.key_resolver = key_resolver
        self.http = _YouTubeHttp(settings, client=client, sleeper=sleeper or time.sleep)
        self.reserve = reserve or (lambda _method: None)
        self.info = ProviderInfo(
            name=NAME,
            display_name="YouTube",
            capabilities=[ProviderCapability.VIDEO_DISCOVERY],
            models=[MODEL],
            is_mock=False,
            is_paid=False,
            description="YouTube Data API chart and recent-video search. No USD charge. "
            "Daily search and videos quotas still apply. Test spends one videos request.",
            requires_key=True,
            key_env_var="YOUTUBE_API_KEY",
            docs_url="https://developers.google.com/youtube/v3",
        )

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        if request.capability != ProviderCapability.VIDEO_DISCOVERY:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        if request.capability != ProviderCapability.VIDEO_DISCOVERY:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        key = self.key_resolver(request.tenant_id)
        if not key:
            raise ProviderError(f"{NAME}: no API key. Add one on Sources or set YOUTUBE_API_KEY")
        operation = str(request.parameters.get("operation") or "")
        started = time.monotonic()
        if operation == "popular":
            data = self._videos(key, _popular_params(request.parameters))
            payload = _video_page(data, mode="popular")
        elif operation == "search":
            data = self.http.get(
                "search",
                "search",
                _search_params(request.parameters, key),
                reserve=_active_reserve(self.reserve),
            )
            ids = [
                str(row.get("id", {}).get("videoId"))
                for row in data.get("items") or []
                if isinstance(row, dict)
                and isinstance(row.get("id"), dict)
                and row["id"].get("videoId")
            ]
            payload = {"ids": ids, "next_page_token": data.get("nextPageToken")}
        elif operation == "hydrate":
            ids = [str(item) for item in request.parameters.get("ids") or []]
            data = self._videos(
                key, {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}
            )
            payload = _video_page(data, mode=str(request.parameters.get("mode") or "recent"))
        else:
            raise ProviderError(f"{NAME}: unknown operation {operation!r}")
        return ProviderResponse(
            provider=NAME,
            model=MODEL,
            capability=ProviderCapability.VIDEO_DISCOVERY,
            provider_request_id=hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:20],
            output_data=payload,
            usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _videos(self, key: str, params: dict[str, Any]) -> dict[str, Any]:
        return self.http.get(
            "videos", "videos", {**params, "key": key}, reserve=_active_reserve(self.reserve)
        )

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        key = self.key_resolver(tenant_id or "")
        if not key:
            return False, "no API key: add one on the Sources page or set YOUTUBE_API_KEY"
        try:
            self._videos(
                key,
                {"part": "id", "chart": "mostPopular", "regionCode": "US", "maxResults": 1},
            )
        except ProviderError as exc:
            return False, str(exc)
        return True, "key valid (one videos.list request)"


def _popular_params(params: dict[str, Any]) -> dict[str, Any]:
    query = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": params.get("region_code") or "US",
        "maxResults": int(params.get("page_size") or 25),
    }
    if params.get("video_category_id"):
        query["videoCategoryId"] = params["video_category_id"]
    if params.get("page_token"):
        query["pageToken"] = params["page_token"]
    return query


def _search_params(params: dict[str, Any], key: str) -> dict[str, Any]:
    query = {
        "part": "snippet",
        "type": "video",
        "order": "date",
        "q": params.get("query") or "",
        "regionCode": params.get("region_code") or "US",
        "publishedAfter": params.get("published_after") or "",
        "maxResults": int(params.get("page_size") or 25),
        "key": key,
    }
    if params.get("relevance_language"):
        query["relevanceLanguage"] = params["relevance_language"]
    if params.get("page_token"):
        query["pageToken"] = params["page_token"]
    return query


def _video_page(data: dict[str, Any], *, mode: str) -> dict[str, Any]:
    now = utcnow()
    items = []
    warnings: list[str] = []
    for row in data.get("items") or []:
        if not isinstance(row, dict):
            warnings.append("skipped a malformed video record")
            continue
        candidate = candidate_from_video(row, mode=mode, retrieved_at=now)
        if candidate is None:
            warnings.append("skipped a video with no id")
            continue
        details = row.get("contentDetails") if isinstance(row.get("contentDetails"), dict) else {}
        raw_duration = details.get("duration") if isinstance(details, dict) else None
        if raw_duration and candidate["duration_sec"] is None:
            warnings.append(f"unreadable duration for {candidate['video_id']}")
        items.append(candidate)
    return {"items": items, "next_page_token": data.get("nextPageToken"), "warnings": warnings}


class MockYouTubeProvider:
    """Deterministic chart and search. Never touches the network."""

    def __init__(self) -> None:
        self.info = ProviderInfo(
            name=MOCK_NAME,
            display_name="Mock YouTube",
            capabilities=[ProviderCapability.VIDEO_DISCOVERY],
            models=[MOCK_MODEL],
            is_mock=True,
            is_paid=False,
            description="Offline YouTube chart and recent-search fixtures. Clearly not live data.",
            requires_key=False,
        )

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        operation = str(request.parameters.get("operation") or "popular")
        now = utcnow()
        if operation == "search":
            query = str(request.parameters.get("query") or "").lower()
            ids = [row["video_id"] for row in _MOCK if query in row["title"].lower()]
            token = (
                None if request.parameters.get("page_token") else ("mock-page-2" if ids else None)
            )
            if request.parameters.get("page_token") == "mock-page-2":
                ids = [f"{item}-b" for item in ids[:1]]
                token = None
            return _mock_response(request, {"ids": ids, "next_page_token": token})
        if operation == "hydrate":
            wanted = [str(item) for item in request.parameters.get("ids") or []]
            items = []
            for video_id in wanted:
                base_id = video_id.removesuffix("-b")
                found = next((row for row in _MOCK if row["video_id"] == base_id), None)
                if found is None:
                    continue
                item = dict(found)
                item["video_id"] = video_id
                item["watch_url"] = watch_url(video_id)
                item["retrieved_at"] = now
                item["source_mode"] = request.parameters.get("mode") or "recent"
                if video_id.endswith("-b"):
                    item["title"] = f"{item['title']} (older)"
                items.append(item)
            return _mock_response(
                request, {"items": items, "next_page_token": None, "warnings": []}
            )
        token = None if request.parameters.get("page_token") else "mock-page-2"
        rows = [dict(row) for row in _MOCK]
        if request.parameters.get("page_token") == "mock-page-2":
            rows = [dict(_MOCK[0])]
            rows[0]["video_id"] = "mockVidExtra01"
            rows[0]["title"] = "Extra mock popular clip"
            rows[0]["watch_url"] = watch_url("mockVidExtra01")
            token = None
        for row in rows:
            row["retrieved_at"] = now
            row["source_mode"] = "popular"
        return _mock_response(request, {"items": rows, "next_page_token": token, "warnings": []})

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        return True, "mock provider (offline)"


def _mock_response(request: ProviderRequest, payload: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        provider=MOCK_NAME,
        model=MOCK_MODEL,
        capability=ProviderCapability.VIDEO_DISCOVERY,
        provider_request_id=hashlib.sha256(request.idempotency_key.encode()).hexdigest()[:20],
        output_data=payload,
        usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST),
    )


_MOCK: list[dict[str, Any]] = [
    {
        "platform": "youtube",
        "video_id": "mockVidPopular1",
        "watch_url": watch_url("mockVidPopular1"),
        "title": "Mock popular: temple bells at dawn",
        "channel_id": "mockChannelA",
        "channel_name": "Mock Archive",
        "published_at": datetime.fromisoformat("2026-10-01T12:00:00+00:00"),
        "duration_sec": 48,
        "category_id": "22",
        "thumbnail_url": "https://i.ytimg.com/vi/mockVidPopular1/mqdefault.jpg",
        "view_count": 1200,
        "like_count": None,
        "comment_count": 4,
        "retrieved_at": datetime.fromisoformat("2026-10-17T00:00:00+00:00"),
        "source_mode": "popular",
    },
    {
        "platform": "youtube",
        "video_id": "mockVidPopular2",
        "watch_url": watch_url("mockVidPopular2"),
        "title": "Mock popular: stone pillar close-up",
        "channel_id": "mockChannelB",
        "channel_name": "Mock Travel",
        "published_at": datetime.fromisoformat("2026-10-02T12:00:00+00:00"),
        "duration_sec": None,
        "category_id": "19",
        "thumbnail_url": "https://i.ytimg.com/vi/mockVidPopular2/mqdefault.jpg",
        "view_count": None,
        "like_count": None,
        "comment_count": None,
        "retrieved_at": datetime.fromisoformat("2026-10-17T00:00:00+00:00"),
        "source_mode": "popular",
    },
]
