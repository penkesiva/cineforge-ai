"""Bounded YouTube discovery. Routes validate. This module fetches, caches, and pages."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from cineforge.contracts.common import new_id, utcnow
from cineforge.contracts.discovery import (
    DiscoveryFilters,
    DiscoveryMode,
    DiscoveryRun,
    Freshness,
    TrendCandidate,
)
from cineforge.contracts.providers import (
    Provider,
    ProviderCapability,
    ProviderError,
    ProviderRequest,
    ProviderStatus,
)
from cineforge.discovery.cursor import CursorError, sign, verify
from cineforge.discovery.store import MemoryDiscoveryStore, PostgresDiscoveryStore
from cineforge.providers.youtube import (
    MOCK_NAME,
    NAME,
    QuotaExhausted,
    bind_reserve,
    credential_hash,
    reset_reserve,
)
from cineforge.runtime import Runtime

CANDIDATE_CAP = 100
SEARCH_PAGE_CAP = 2
Store = MemoryDiscoveryStore | PostgresDiscoveryStore


class DiscoveryRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class DiscoveryService:
    def __init__(self, runtime: Runtime, store: Store, *, now=utcnow) -> None:
        self.rt = runtime
        self.store = store
        self.now = now

    def purge(self) -> int:
        return self.store.purge(self.now(), hours=self.rt.settings.youtube_retention_hours)

    def start(
        self, tenant_id: str, filters: DiscoveryFilters, idempotency_key: str
    ) -> DiscoveryRun:
        self.purge()
        existing = self.store.find_idempotent(tenant_id, idempotency_key)
        if existing is not None:
            return existing
        cached = self.store.cache_get(tenant_id, _cache_key(filters, ""), self.now())
        if cached is not None:
            run = _run_from_cache(tenant_id, filters, idempotency_key, cached, self.now())
            run.next_cursor = self._next_cursor(run, cached.get("next_page_token"))
            return self.store.insert(run)
        provider = self._provider(tenant_id)
        page = self._fetch(provider, tenant_id, filters, upstream_token=None, run_id="pending")
        run = DiscoveryRun(
            tenant_id=tenant_id,
            filters=filters,
            provider=provider.info.name,
            is_mock=provider.info.is_mock,
            freshness=Freshness.FRESH,
            partial=bool(page["warnings"]),
            warnings=page["warnings"],
            candidates=_dedupe([], page["items"])[0][:CANDIDATE_CAP],
            idempotency_key=idempotency_key,
            retrieved_at=self.now(),
            search_pages=1 if filters.mode == DiscoveryMode.RECENT else 0,
        )
        run.next_cursor = self._next_cursor(run, page["next_page_token"])
        page["is_mock"] = provider.info.is_mock
        page["provider"] = provider.info.name
        self.store.cache_put(
            tenant_id,
            _cache_key(filters, ""),
            page,
            self.now() + timedelta(seconds=self.rt.settings.youtube_cache_ttl_sec),
        )
        return self.store.insert(run)

    def get(self, tenant_id: str, run_id: str) -> DiscoveryRun:
        self.purge()
        run = self.store.get(tenant_id, run_id)
        if run is None:
            raise DiscoveryRejected(404, "discovery run not found")
        return run

    def page(self, tenant_id: str, run_id: str, cursor: str) -> DiscoveryRun:
        run = self.get(tenant_id, run_id)
        try:
            payload = verify(cursor, self.rt.settings.discovery_cursor_secret)
        except CursorError as exc:
            raise DiscoveryRejected(400, str(exc)) from exc
        if payload.get("run") != run.id:
            raise DiscoveryRejected(400, "cursor does not belong to this run")
        if cursor in run.seen_cursors:
            return run
        if cursor != run.next_cursor:
            raise DiscoveryRejected(400, "cursor is not the next page")
        if len(run.candidates) >= CANDIDATE_CAP:
            raise DiscoveryRejected(400, "this run already has the maximum of 100 videos")
        if run.filters.mode == DiscoveryMode.RECENT and run.search_pages >= SEARCH_PAGE_CAP:
            raise DiscoveryRejected(400, "recent search is limited to two pages")
        upstream = str(payload.get("up") or "")
        cached = self.store.cache_get(tenant_id, _cache_key(run.filters, upstream), self.now())
        provider = self._provider(tenant_id)
        if cached is None:
            page = self._fetch(
                provider, tenant_id, run.filters, upstream_token=upstream, run_id=run.id
            )
            page["is_mock"] = provider.info.is_mock
            page["provider"] = provider.info.name
            self.store.cache_put(
                tenant_id,
                _cache_key(run.filters, upstream),
                page,
                self.now() + timedelta(seconds=self.rt.settings.youtube_cache_ttl_sec),
            )
            freshness = Freshness.FRESH
        else:
            page = cached
            freshness = Freshness.CACHED
        merged, trimmed = _dedupe(run.candidates, page["items"])
        if len(merged) > CANDIDATE_CAP:
            merged = merged[:CANDIDATE_CAP]
            trimmed = True
        run.candidates = merged
        run.seen_cursors = [*run.seen_cursors, cursor]
        run.partial = run.partial or bool(page["warnings"]) or trimmed
        run.warnings = [*run.warnings, *page["warnings"]]
        if trimmed:
            run.warnings.append("stopped at 100 videos")
        if run.filters.mode == DiscoveryMode.RECENT:
            run.search_pages += 1
        stop = trimmed or (
            run.filters.mode == DiscoveryMode.RECENT and run.search_pages >= SEARCH_PAGE_CAP
        )
        run.next_cursor = None if stop else self._next_cursor(run, page["next_page_token"])
        run.freshness = freshness
        self.store.save(run)
        return run

    def _provider(self, tenant_id: str) -> Provider:
        name = MOCK_NAME if self.rt.settings.provider_mode == "mock" else NAME
        provider = self.rt.providers.get(name)
        status, detail = self.rt.providers.status(name, tenant_id)
        if status != ProviderStatus.READY:
            raise DiscoveryRejected(409, detail or f"{name} is not ready")
        return provider

    def _fetch(
        self,
        provider: Provider,
        tenant_id: str,
        filters: DiscoveryFilters,
        *,
        upstream_token: str | None,
        run_id: str,
    ) -> dict[str, Any]:
        if filters.mode == DiscoveryMode.POPULAR:
            data = self._invoke(
                provider,
                tenant_id,
                run_id,
                "videos",
                {
                    "operation": "popular",
                    "region_code": filters.region_code,
                    "video_category_id": filters.video_category_id,
                    "page_size": filters.page_size,
                    "page_token": upstream_token,
                },
            )
            return _page(data)
        published_after = (
            (self.now() - timedelta(days=int(filters.lookback_days or 7)))
            .astimezone(UTC)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        found = self._invoke(
            provider,
            tenant_id,
            run_id,
            "search",
            {
                "operation": "search",
                "query": filters.query,
                "region_code": filters.region_code,
                "relevance_language": filters.relevance_language,
                "published_after": published_after,
                "page_size": filters.page_size,
                "page_token": upstream_token,
            },
        )
        ids = [str(item) for item in found.get("ids") or []]
        warnings = ["search results are recent references, not a trending chart"]
        if not ids:
            return {
                "items": [],
                "next_page_token": found.get("next_page_token"),
                "warnings": warnings,
            }
        try:
            hydrated = self._invoke(
                provider,
                tenant_id,
                run_id,
                "videos",
                {"operation": "hydrate", "ids": ids, "mode": "recent"},
            )
        except ProviderError as exc:
            warnings.append(str(exc))
            return {"items": [], "next_page_token": None, "warnings": warnings}
        page = _page(hydrated)
        ordered = _order(ids, page["items"])
        missing = len(ids) - len(ordered)
        if missing:
            warnings.append(f"{missing} video(s) could not be hydrated")
        page["items"] = ordered
        page["warnings"] = [*warnings, *page["warnings"]]
        page["next_page_token"] = found.get("next_page_token")
        return page

    def _invoke(
        self,
        provider: Provider,
        tenant_id: str,
        run_id: str,
        method: str,
        parameters: dict[str, Any],
    ) -> dict[str, Any]:
        request = ProviderRequest(
            tenant_id=tenant_id,
            production_id=f"discovery:{run_id}",
            capability=ProviderCapability.VIDEO_DISCOVERY,
            model=provider.info.models[0],
            parameters=parameters,
            idempotency_key=new_id("ydc"),
        )

        def reserve(called: str) -> None:
            if provider.info.is_mock:
                return
            key = self.rt.providers.resolve_key(provider.info.name, tenant_id)[0] or ""
            allowance = (
                self.rt.settings.youtube_search_daily_allowance
                if called == "search"
                else self.rt.settings.youtube_videos_daily_allowance
            )
            self.store.reserve(credential_hash(key), called, self.now().date(), allowance)

        token = bind_reserve(reserve)
        try:
            response, _cost = self.rt.paid_calls.preproduction(provider, request)
        except QuotaExhausted as exc:
            raise DiscoveryRejected(429, str(exc)) from exc
        except ProviderError as exc:
            raise DiscoveryRejected(502, str(exc)) from exc
        finally:
            reset_reserve(token)
        return response.output_data

    def _next_cursor(self, run: DiscoveryRun, upstream: Any) -> str | None:
        if not upstream:
            return None
        if len(run.candidates) >= CANDIDATE_CAP:
            return None
        if run.filters.mode == DiscoveryMode.RECENT and run.search_pages >= SEARCH_PAGE_CAP:
            return None
        return sign(
            {"run": run.id, "up": str(upstream)},
            self.rt.settings.discovery_cursor_secret,
        )


def _cache_key(filters: DiscoveryFilters, upstream: str) -> str:
    raw = json.dumps({"filters": filters.model_dump(mode="json"), "up": upstream}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()


def _run_from_cache(
    tenant_id: str,
    filters: DiscoveryFilters,
    idempotency_key: str,
    page: dict[str, Any],
    now: datetime,
) -> DiscoveryRun:
    items = [TrendCandidate.model_validate(row) for row in page.get("items") or []]
    return DiscoveryRun(
        tenant_id=tenant_id,
        filters=filters,
        provider=str(page.get("provider") or NAME),
        is_mock=bool(page.get("is_mock")),
        freshness=Freshness.CACHED,
        partial=bool(page.get("warnings")),
        warnings=list(page.get("warnings") or []),
        candidates=items,
        idempotency_key=idempotency_key,
        retrieved_at=now,
        search_pages=1 if filters.mode == DiscoveryMode.RECENT else 0,
    )


def _page(data: dict[str, Any]) -> dict[str, Any]:
    items = []
    warnings = list(data.get("warnings") or [])
    for row in data.get("items") or []:
        try:
            items.append(TrendCandidate.model_validate(row).model_dump(mode="json"))
        except ValueError:
            warnings.append("skipped a video that failed validation")
    return {
        "items": items,
        "next_page_token": data.get("next_page_token"),
        "warnings": warnings,
        "is_mock": False,
    }


def _dedupe(
    current: list[TrendCandidate], extra: list[dict[str, Any]]
) -> tuple[list[TrendCandidate], bool]:
    seen = {(row.platform, row.video_id) for row in current}
    merged = list(current)
    for row in extra:
        candidate = TrendCandidate.model_validate(row)
        key = (candidate.platform, candidate.video_id)
        if key in seen:
            continue
        seen.add(key)
        merged.append(candidate)
    return merged, False


def _order(ids: list[str], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(row.get("video_id")): row for row in items}
    return [by_id[video_id] for video_id in ids if video_id in by_id]
