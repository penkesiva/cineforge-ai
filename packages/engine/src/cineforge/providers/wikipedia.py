"""Wikipedia research provider (``web_research``, free, keyless).

``request.prompt`` is the search query. Parameters: ``max_results`` (default 4, max 8)
and ``language`` (default ``en``; ``en-US`` -> ``en``). One ``list=search`` call, then
one ``prop=extracts|info`` call per page (whole-article plain-text extracts are only
served one page at a time; ``exchars`` is capped at 1200 by the API, so the extract is
truncated to ``MAX_EXTRACT_CHARS`` here instead).
"""

from __future__ import annotations

import re
import time
from datetime import date
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
    ResearchSource,
)
from cineforge.providers.http import build_http_client, int_param, local_request_id
from cineforge.providers.mediawiki import mediawiki_get, site_check

NAME = "wikipedia"
MODEL = "mediawiki-action-api"
DEFAULT_MAX_RESULTS = 4
MAX_RESULTS_CAP = 8
MAX_EXTRACT_CHARS = 6000
_LANG = re.compile(r"^[a-z]{2,12}$")


def wiki_language(value: object) -> str:
    lang = str(value or "en").strip().lower().split("-")[0].split("_")[0]
    return lang if _LANG.match(lang) else "en"


def _touched_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


class WikipediaResearchProvider:
    def __init__(self, settings: Settings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self._client = client
        self.info = ProviderInfo(
            name=NAME,
            display_name="Wikipedia",
            capabilities=[ProviderCapability.WEB_RESEARCH],
            models=[MODEL],
            is_mock=False,
            is_paid=False,
            description="Encyclopedia search with plain-text article extracts the research "
            "agent can cite. Free and keyless (rate limited).",
            requires_key=False,
            docs_url="https://www.mediawiki.org/wiki/API:Main_page",
        )

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = build_http_client(self.settings)
        return self._client

    @staticmethod
    def api_url(language: str) -> str:
        return f"https://{wiki_language(language)}.wikipedia.org/w/api.php"

    def _validate(self, request: ProviderRequest) -> str:
        if request.capability != ProviderCapability.WEB_RESEARCH:
            raise ProviderError(f"{NAME} does not support {request.capability}")
        query = (request.prompt or "").strip()
        if not query:
            raise ProviderError(f"{NAME}: empty search query (request.prompt)")
        return query

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        self._validate(request)
        return ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        query = self._validate(request)
        params = request.parameters
        language = wiki_language(params.get("language"))
        limit = int_param(
            params, "max_results", DEFAULT_MAX_RESULTS, low=1, high=MAX_RESULTS_CAP, provider=NAME
        )
        api = self.api_url(language)
        started = time.monotonic()
        found = mediawiki_get(
            self.client,
            api,
            {"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
             "srnamespace": 0, "srprop": ""},
            provider=NAME,
        )  # fmt: skip
        hits = ((found.get("query") or {}).get("search") or [])[:limit]
        sources: list[dict[str, Any]] = []
        for hit in hits:
            source = self._page_source(api, hit)
            if source is not None:
                sources.append(source.model_dump(mode="json"))
        return ProviderResponse(
            provider=NAME,
            model=request.model,
            capability=ProviderCapability.WEB_RESEARCH,
            provider_request_id=local_request_id(NAME, request.idempotency_key),
            output_text="\n".join(s["title"] for s in sources),
            output_data={"sources": sources, "query": query, "language": language},
            usage=ProviderUsage(units=Decimal(1), unit=PriceUnit.REQUEST),
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    def _page_source(self, api: str, hit: dict[str, Any]) -> ResearchSource | None:
        pageid = hit.get("pageid")
        if pageid is None:
            return None
        body = mediawiki_get(
            self.client,
            api,
            {"action": "query", "prop": "extracts|info", "pageids": pageid, "explaintext": 1,
             "inprop": "url"},
            provider=NAME,
        )  # fmt: skip
        pages = (body.get("query") or {}).get("pages") or []
        page = pages[0] if pages else None
        if not page or page.get("missing") or not page.get("extract"):
            return None
        url = page.get("canonicalurl") or page.get("fullurl")
        if not url:
            return None
        return ResearchSource(
            url=str(url),
            title=str(page.get("title") or hit.get("title") or ""),
            publisher="Wikipedia",
            extract=str(page["extract"]).strip()[:MAX_EXTRACT_CHARS],
            published_at=_touched_date(page.get("touched")),
            retrieved_at=utcnow(),
        )

    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        return site_check(self.client, self.api_url("en"), provider=NAME)
