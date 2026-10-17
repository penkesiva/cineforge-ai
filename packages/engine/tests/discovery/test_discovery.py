"""Discovery bounds, cache, quota, and the inspiration hand-off."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from cineforge.config import Settings
from cineforge.contracts.api import CreateProductionRequest
from cineforge.contracts.common import ProductionMode
from cineforge.contracts.discovery import (
    DiscoveryFilters,
    DiscoveryMode,
    InspirationReference,
    StartDiscoveryRequest,
)
from cineforge.discovery.service import DiscoveryRejected, DiscoveryService
from cineforge.discovery.store import MemoryDiscoveryStore
from cineforge.providers.youtube import QuotaExhausted
from cineforge.runtime import Runtime


def _runtime() -> Runtime:
    return Runtime(
        Settings(persistence_backend="memory", provider_mode="mock", secrets_backend="memory")
    )


def _start(service: DiscoveryService, **overrides) -> object:
    body = StartDiscoveryRequest(idempotency_key="idem-discovery-1", **overrides)
    return service.start("tenant_demo", body.to_filters(), body.idempotency_key)


def test_mock_chart_pages_cache_and_replay() -> None:
    service = DiscoveryService(_runtime(), MemoryDiscoveryStore())
    first = _start(service)
    assert first.is_mock is True
    assert first.freshness.value == "fresh"
    assert [row.video_id for row in first.candidates] == ["mockVidPopular1", "mockVidPopular2"]
    assert first.candidates[1].view_count is None
    again = _start(service)
    assert again.id == first.id
    cached = service.start("tenant_demo", first.filters, "idem-discovery-2")
    assert cached.freshness.value == "cached"
    assert cached.id != first.id
    cursor = first.next_cursor or ""
    page = service.page("tenant_demo", first.id, cursor)
    assert [row.video_id for row in page.candidates] == [
        "mockVidPopular1",
        "mockVidPopular2",
        "mockVidExtra01",
    ]
    replay = service.page("tenant_demo", first.id, cursor)
    assert [row.video_id for row in replay.candidates] == [row.video_id for row in page.candidates]
    with pytest.raises(DiscoveryRejected) as missing:
        service.get("other_tenant", first.id)
    assert missing.value.status == 404
    with pytest.raises(DiscoveryRejected) as bad:
        service.page("tenant_demo", first.id, "tampered.cursor")
    assert bad.value.status == 400


def test_popular_rejects_search_filters() -> None:
    with pytest.raises(ValueError, match="popular"):
        StartDiscoveryRequest(idempotency_key="idem-discovery-9", query="bells").to_filters()


def test_recent_search_is_labeled_and_ordered() -> None:
    service = DiscoveryService(_runtime(), MemoryDiscoveryStore())
    filters = DiscoveryFilters(mode=DiscoveryMode.RECENT, query="pillar")
    run = service.start("tenant_demo", filters, "idem-recent-1")
    assert run.candidates[0].video_id == "mockVidPopular2"
    assert any("not a trending chart" in warning for warning in run.warnings)


def test_quota_fails_closed_under_contention() -> None:
    store = MemoryDiscoveryStore()
    errors: list[QuotaExhausted] = []
    day = datetime.now(UTC).date()

    def reserve() -> None:
        try:
            store.reserve("hash", "videos", day, 1)
        except QuotaExhausted as exc:
            errors.append(exc)

    threads = [threading.Thread(target=reserve) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(errors) == 3
    assert store.quota[("hash", "videos", day)] == 1


def test_purge_deletes_old_runs() -> None:
    store = MemoryDiscoveryStore()
    service = DiscoveryService(_runtime(), store, now=lambda: datetime.now(UTC) - timedelta(days=3))
    old = _start(service)
    service.now = lambda: datetime.now(UTC)
    assert service.purge() >= 1
    with pytest.raises(DiscoveryRejected):
        service.get(old.tenant_id, old.id)


def test_inspiration_is_identity_only() -> None:
    ref = InspirationReference(
        video_id="abcdefghijk",
        watch_url="https://www.youtube.com/watch?v=abcdefghijk",
        retrieved_at=datetime.now(UTC),
    )
    request = CreateProductionRequest(
        theme_id="time-traveler",
        topic="A stone pillar",
        mode=ProductionMode.BALANCED,
        reference=ref,
    )
    assert request.auto_approve is False
    assert "title" not in request.reference.model_dump()
    with pytest.raises(ValueError):
        InspirationReference(
            video_id="abcdefghijk",
            watch_url="https://youtu.be/abcdefghijk",
            retrieved_at=datetime.now(UTC),
        )
