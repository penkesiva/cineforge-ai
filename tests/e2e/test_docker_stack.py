"""End-to-end validation against the running Docker Compose stack (`make up`).

Exercises: dashboard (Next.js) -> API proxy -> FastAPI -> Postgres (Supabase) ->
Redis queue -> agent worker -> media worker (FFmpeg) -> persistent media volume.
Run with `make test-e2e`. Skips automatically when the stack is not up.
"""

from __future__ import annotations

import os
import time

import httpx
import pytest

API = os.environ.get("CINEFORGE_E2E_API", "http://localhost:8000")
DASHBOARD = os.environ.get("CINEFORGE_E2E_DASHBOARD", "http://localhost:3000")
TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"
WAIT_STATES = {"AWAITING_APPROVAL", "READY", "PAUSED_BUDGET", "NEEDS_REVIEW", "FAILED"}


def _stack_up() -> bool:
    try:
        return httpx.get(f"{API}/health/live", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(not _stack_up(), reason="Docker stack not running (make up)"),
]


def _wait_for(client: httpx.Client, production_id: str, timeout: float = 240) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        detail = client.get(f"/api/v1/productions/{production_id}").json()
        if detail["summary"]["state"] in WAIT_STATES:
            return detail
        time.sleep(1)
    raise AssertionError(f"timed out; last state {detail['summary']['state']}")


def test_stack_health_and_dashboard_pages() -> None:
    health = httpx.get(f"{API}/health", timeout=10).json()
    assert health["status"] == "ok", health
    assert {c["name"]: c["status"] for c in health["checks"]} == {
        "database": "ok",
        "redis": "ok",
        "storage": "ok",
    }
    assert health["paid_providers_enabled"] is False
    assert httpx.get(f"{API}/docs", timeout=10).status_code == 200
    assert "paths" in httpx.get(f"{API}/openapi.json", timeout=10).json()
    for path in ("/", "/productions", "/agents", "/costs"):
        assert httpx.get(f"{DASHBOARD}{path}", timeout=60).status_code == 200, path
    proxied = httpx.get(f"{DASHBOARD}/api/v1/agents", timeout=30)
    assert proxied.status_code == 200 and len(proxied.json()) == 10


def test_sample_production_through_queue_workers_and_ffmpeg() -> None:
    with httpx.Client(base_url=DASHBOARD, timeout=30) as client:  # via the dashboard proxy
        created = client.post(
            "/api/v1/productions",
            json={"theme_id": "time-traveler", "topic": TOPIC, "title": "E2E Eiffel 1889"},
        )
        assert created.status_code == 201, created.text
        production_id = created.json()["summary"]["id"]
        assert client.post(f"/api/v1/productions/{production_id}/run").status_code == 202

        detail = _wait_for(client, production_id)
        assert detail["summary"]["state"] == "AWAITING_APPROVAL", detail["events"][-3:]
        assert detail["cost"]["estimated"] > 0

        approve = client.post(
            f"/api/v1/productions/{production_id}/approve", json={"approved_by": "e2e"}
        )
        assert approve.status_code == 202, approve.text
        detail = _wait_for(client, production_id)
        assert detail["summary"]["state"] == "READY", detail["events"][-3:]

        runs = {r["agent_id"] for r in detail["agent_runs"] if r["status"] == "succeeded"}
        assert len(runs) == 10
        assert 0 < detail["cost"]["actual"] <= detail["cost"]["limit"]
        assert detail["artifacts"]["review"]["passed"] is True

        asset_id = detail["manifest"]["master_render_asset_id"]
        video = client.get(f"/api/v1/assets/{asset_id}/content", headers={"Range": "bytes=0-15"})
        assert video.status_code == 206 and video.content[4:8] == b"ftyp"

        assert client.post(f"/api/v1/productions/{production_id}/deliver").status_code == 200
        assert (
            client.get(f"/api/v1/productions/{production_id}").json()["summary"]["state"]
            == "DELIVERED"
        )
