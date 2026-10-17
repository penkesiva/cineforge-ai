"""Discovery HTTP lifecycle stays on the mock provider and can seed a draft."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from cineforge.config import Settings
from cineforge.runtime import Runtime, set_runtime
from cineforge_api.main import create_app
from fastapi.testclient import TestClient


def test_discover_then_create_draft() -> None:
    settings = Settings(
        persistence_backend="memory", provider_mode="mock", secrets_backend="memory"
    )
    set_runtime(Runtime(settings))
    try:
        with TestClient(create_app(settings)) as client:
            started = client.post(
                "/api/v1/discovery/runs",
                headers={"X-Tenant-Id": "tenant_demo"},
                json={"idempotency_key": "api-disc-0001", "region_code": "us"},
            )
            assert started.status_code == 200, started.text
            run = started.json()
            assert run["is_mock"] is True
            video = run["candidates"][0]
            created = client.post(
                "/api/v1/productions",
                headers={"X-Tenant-Id": "tenant_demo"},
                json={
                    "theme_id": "time-traveler",
                    "topic": "A suggested topic from discovery",
                    "mode": "balanced",
                    "auto_approve": False,
                    "reference": {
                        "platform": "youtube",
                        "video_id": video["video_id"],
                        "watch_url": video["watch_url"],
                        "retrieved_at": video["retrieved_at"],
                    },
                },
            )
            assert created.status_code == 201, created.text
            detail = created.json()
            assert detail["summary"]["state"] == "DRAFT"
            inspiration = detail["manifest"]["inspiration"]
            assert inspiration["video_id"] == video["video_id"]
            assert "title" not in inspiration
            assert "view_count" not in inspiration
            rejected = client.post(
                "/api/v1/discovery/runs",
                headers={"X-Tenant-Id": "tenant_demo"},
                json={"idempotency_key": "api-disc-0002", "mode": "popular", "query": "bells"},
            )
            assert rejected.status_code == 422
            other = client.get(
                f"/api/v1/discovery/runs/{run['id']}",
                headers={"X-Tenant-Id": "tenant_other"},
            )
            assert other.status_code == 404
    finally:
        set_runtime(None)


@pytest.mark.integration
def test_postgres_quota_is_atomic() -> None:
    from cineforge.db import ping
    from cineforge.discovery.store import PostgresDiscoveryStore

    settings = Settings()
    if settings.persistence_backend == "memory" or not ping(settings.database_url):
        pytest.skip("Postgres not reachable")
    _ensure_tables(settings.database_url)
    store = PostgresDiscoveryStore(settings.database_url)
    day = datetime.now(UTC).date()
    key = f"test-{datetime.now(UTC).timestamp()}"
    store.reserve(key, "search", day, 1)
    from cineforge.providers.youtube import QuotaExhausted

    with pytest.raises(QuotaExhausted):
        store.reserve(key, "search", day, 1)


def _ensure_tables(url: str) -> None:
    from pathlib import Path

    import psycopg

    sql = Path("supabase/migrations/20261017000000_discovery.sql").read_text()
    with psycopg.connect(url, autocommit=True) as conn:
        if conn.execute("select to_regclass('public.discovery_quota')").fetchone()[0] is None:
            conn.execute(sql)
