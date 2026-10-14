"""Openverse image search (``media_search``, free, anonymous API, rate limited).

The search already filters to licenses allowing commercial use and modification;
the rights gate still evaluates every item. Metadata only, nothing is downloaded.
Query: ``parameters["query"]`` or ``request.prompt``; ``parameters["limit"]``
(default 8, max 20 for anonymous clients).
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx

from cineforge.config import Settings
from cineforge.contracts.common import utcnow
from cineforge.contracts.media import LicenseInfo
from cineforge.contracts.providers import (
    MediaSearchItem,
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)
from cineforge.providers.http import (
    build_http_client,
    int_param,
    local_request_id,
    request_json,
)
from cineforge.providers.licenses import build_license_info, normalize_open_license

NAME = "openverse"
MODEL = "openverse-v1"
API_URL = "https://api.openverse.org/v1/images/"
DEFAULT_LIMIT = 8
MAX_LIMIT = 20


def openverse_license(
    result: dict[str, Any], *, retrieved_at: datetime | None = None
) -> LicenseInfo:
    lic = normalize_open_license(
        str(result.get("license") or ""), str(result.get("license_version") or "")
    )
    return build_license_info(
        lic,
        source_provider=NAME,
        source_url=result.get("foreign_landing_url"),
        license_url=result.get("license_url"),
        author=result.get("creator"),
        attribution_text=result.get("attribution"),
        retrieved_at=retrieved_at,
    )


class OpenverseMediaProvider:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client
        self.info = ProviderInfo(
            name=NAME,
            display_name="Openverse",
            capabilities=[ProviderCapability.MEDIA_SEARCH],
            models=[MODEL],
            is_mock=False,
            is_paid=False,
            description="Openly licensed images aggregated from Flickr, museums and more, "
            "filtered to commercial use + modification. Free, anonymous, rate limited.",
            requires_key=False,
            docs_url="https://api.openverse.org/v1/",
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_http_client(self.settings)
        return self._client

    def _query(self, request: ProviderRequest) -> str:
        if request.capability != ProviderCapability.MEDIA_SEARCH:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        query = str(request.parameters.get("query") or request.prompt or "").strip()
        if not query:
            raise ProviderError(f"{NAME}: empty search query")
        return query

    def _search(self, query: str, limit: int) -> dict[str, Any]:
        return request_json(
            self.client,
            "GET",
            API_URL,
            provider=NAME,
            params={"q": query, "page_size": limit, "license_type": "commercial,modification",
                    "mature": "false"},
        )  # fmt: skip

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        self._query(request)
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        query = self._query(request)
        limit = int_param(
            request.parameters, "limit", DEFAULT_LIMIT, low=1, high=MAX_LIMIT, provider=NAME
        )
        started = time.monotonic()
        body = self._search(query, limit)
        retrieved_at = utcnow()
        items = [
            item.model_dump(mode="json")
            for result in body.get("results") or []
            if isinstance(result, dict) and (item := self._item(result, retrieved_at)) is not None
        ]
        return ProviderResponse(
            provider=NAME,
            model=request.model,
            capability=ProviderCapability.MEDIA_SEARCH,
            provider_request_id=local_request_id(NAME, request.idempotency_key),
            output_data={
                "items": items,
                "query": query,
                "result_count": body.get("result_count"),
            },
            usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _item(result: dict[str, Any], retrieved_at: datetime) -> MediaSearchItem | None:
        landing = result.get("foreign_landing_url")
        if not landing:
            return None
        source = result.get("source") or result.get("provider")
        return MediaSearchItem(
            provider=NAME,
            media_type="image",
            title=str(result.get("title") or "Untitled"),
            source_url=str(landing),
            file_url=result.get("url"),
            thumbnail_url=result.get("thumbnail"),
            width=result.get("width"),
            height=result.get("height"),
            description=f"Source: {source}" if source else None,
            license=openverse_license(result, retrieved_at=retrieved_at),
        )

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        try:
            body = self._search("landscape", 1)
        except ProviderError as exc:
            return False, str(exc)
        return True, f"reachable ({body.get('result_count', 0)} results for a probe query)"
