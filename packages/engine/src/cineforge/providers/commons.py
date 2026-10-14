"""Wikimedia Commons media search (``media_search``, free, keyless).

Returns metadata only (``MediaSearchItem`` with ``LicenseInfo`` from ``extmetadata``);
files are never downloaded here. Query: ``parameters["query"]`` or ``request.prompt``;
``parameters["limit"]`` (default 8, max 50).
"""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from pathlib import PurePosixPath
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
from cineforge.providers.http import build_http_client, int_param, local_request_id
from cineforge.providers.licenses import build_license_info, normalize_open_license, strip_html
from cineforge.providers.mediawiki import mediawiki_get, site_check

NAME = "wikimedia-commons"
MODEL = "mediawiki-action-api"
API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_LIMIT = 8
MAX_LIMIT = 50
THUMB_WIDTH = 640
MAX_DESCRIPTION_CHARS = 500


def _meta(extmetadata: dict[str, Any], key: str) -> str:
    entry = extmetadata.get(key)
    value = entry.get("value") if isinstance(entry, dict) else entry
    return "" if value is None else str(value).strip()


def file_title(page_title: str) -> str:
    """'File:Tour Eiffel at sunrise.jpg' -> 'Tour Eiffel at sunrise'."""
    name = page_title.split(":", 1)[1] if page_title.startswith("File:") else page_title
    return PurePosixPath(name).stem or name


def commons_license(
    extmetadata: dict[str, Any],
    *,
    title: str,
    source_url: str | None,
    retrieved_at: datetime | None = None,
) -> LicenseInfo:
    """Map Commons ``extmetadata`` to ``LicenseInfo`` (see ``providers/licenses.py``)."""
    short_name = _meta(extmetadata, "LicenseShortName")
    code = _meta(extmetadata, "License")
    lic = normalize_open_license(code)
    if not lic.recognized:
        lic = normalize_open_license(short_name or _meta(extmetadata, "UsageTerms") or code)
    artist = strip_html(_meta(extmetadata, "Artist"))
    required_raw = _meta(extmetadata, "AttributionRequired").lower()
    required = {"true": True, "false": False}.get(required_raw)
    restrictions = [r.strip() for r in _meta(extmetadata, "Restrictions").split("|") if r.strip()]
    label = short_name or lic.license_type
    credit = f"{title} by {artist}" if artist else title
    return build_license_info(
        lic,
        source_provider=NAME,
        source_url=source_url,
        license_url=_meta(extmetadata, "LicenseUrl") or None,
        author=artist or None,
        attribution_text=f"{credit}, {label}, via Wikimedia Commons",
        attribution_required=required,
        restrictions=restrictions,
        retrieved_at=retrieved_at,
    )


class CommonsMediaProvider:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client
        self.info = ProviderInfo(
            name=NAME,
            display_name="Wikimedia Commons",
            capabilities=[ProviderCapability.MEDIA_SEARCH],
            models=[MODEL],
            is_mock=False,
            is_paid=False,
            description="Freely licensed photos with per-file license, author and "
            "restrictions metadata. Free and keyless.",
            requires_key=False,
            docs_url="https://commons.wikimedia.org/wiki/Commons:API",
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

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        self._query(request)
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        query = self._query(request)
        limit = int_param(
            request.parameters, "limit", DEFAULT_LIMIT, low=1, high=MAX_LIMIT, provider=NAME
        )
        started = time.monotonic()
        body = mediawiki_get(
            self.client,
            API_URL,
            {"action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
             "gsrnamespace": 6, "gsrlimit": limit, "prop": "imageinfo",
             "iiprop": "url|size|mime|extmetadata", "iiurlwidth": THUMB_WIDTH},
            provider=NAME,
        )  # fmt: skip
        pages = sorted(
            (body.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 0)
        )
        retrieved_at = utcnow()
        items = [
            item.model_dump(mode="json")
            for page in pages
            if (item := self._item(page, retrieved_at)) is not None
        ]
        return ProviderResponse(
            provider=NAME,
            model=request.model,
            capability=ProviderCapability.MEDIA_SEARCH,
            provider_request_id=local_request_id(NAME, request.idempotency_key),
            output_data={"items": items, "query": query},
            usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    @staticmethod
    def _item(page: dict[str, Any], retrieved_at: datetime) -> MediaSearchItem | None:
        infos = page.get("imageinfo") or []
        if not infos:
            return None
        info = infos[0]
        source_url = info.get("descriptionurl")
        if not source_url:
            return None
        meta = info.get("extmetadata") or {}
        title = file_title(str(page.get("title") or ""))
        description = strip_html(_meta(meta, "ImageDescription"), limit=MAX_DESCRIPTION_CHARS)
        return MediaSearchItem(
            provider=NAME,
            media_type="image",
            title=title,
            source_url=str(source_url),
            file_url=info.get("url"),
            thumbnail_url=info.get("thumburl"),
            width=info.get("width"),
            height=info.get("height"),
            description=description or None,
            license=commons_license(
                meta, title=title, source_url=str(source_url), retrieved_at=retrieved_at
            ),
        )

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        return site_check(self.client, API_URL, provider=NAME)
