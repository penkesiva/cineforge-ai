"""Cross-workstream end-to-end test with REAL components (no fakes).

API (B) + workflow/agents (B) + budget/guard/mock providers (D) + rights gate (D)
+ local storage (D) + FFmpeg render job (D), wired by cineforge.runtime with the
memory persistence backend and the inline queue. Proves the Phase 0 vertical slice
in one process without Docker, credentials or paid calls.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from cineforge.config import Settings
from cineforge.contracts.common import AgentId
from cineforge.media.edit import END_CARD_SEC
from cineforge.runtime import Runtime, set_runtime
from fastapi.testclient import TestClient

pytestmark = [
    pytest.mark.ffmpeg,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed"),
]

TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"


def _client(tmp_path: Path, failure_rate: float) -> Iterator[TestClient]:
    from cineforge_api.main import create_app

    settings = Settings(
        persistence_backend="memory",
        queue_backend="inline",
        storage_backend="local",
        storage_local_root=tmp_path / "media",
        mock_step_delay_sec=0,
        mock_failure_rate=failure_rate,
        allow_paid_providers=False,
    )
    set_runtime(Runtime(settings))
    with TestClient(create_app(settings)) as test_client:
        yield test_client
    set_runtime(None)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    yield from _client(tmp_path, failure_rate=0.0)


@pytest.fixture
def flaky_client(tmp_path: Path) -> Iterator[TestClient]:
    yield from _client(tmp_path, failure_rate=0.3)


def _detail(client: TestClient, production_id: str) -> dict:
    response = client.get(f"/api/v1/productions/{production_id}")
    assert response.status_code == 200, response.text
    return response.json()


def test_full_mock_production_reaches_delivered(client: TestClient, tmp_path: Path) -> None:
    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["paid_providers_enabled"] is False
    assert len(client.get("/api/v1/agents").json()) == 10

    created = client.post("/api/v1/productions", json={"theme_id": "time-traveler", "topic": TOPIC})
    assert created.status_code == 201, created.text
    production_id = created.json()["summary"]["id"]
    assert created.json()["summary"]["state"] == "DRAFT"

    assert client.post(f"/api/v1/productions/{production_id}/run").status_code == 202
    detail = _detail(client, production_id)
    assert detail["summary"]["state"] == "AWAITING_APPROVAL"
    manifest = detail["manifest"]
    assert 4 <= len(manifest["scenes"]) <= 6
    assert sum(s["duration_sec"] for s in manifest["scenes"]) == pytest.approx(45, abs=0.05)
    artifacts = detail["artifacts"]
    for name in ("plan", "treatment", "research", "media", "script", "cost_plan"):
        assert artifacts[name] is not None, name
    # Rights gate fails closed: unknown / non-commercial candidates are blocked.
    assert artifacts["media"]["blocked"], "expected blocked asset candidates"
    estimate = Decimal(str(detail["cost"]["estimated"]))
    assert Decimal(0) < estimate <= Decimal(str(detail["cost"]["limit"]))

    approved = client.post(
        f"/api/v1/productions/{production_id}/approve", json={"approved_by": "e2e"}
    )
    assert approved.status_code == 202, approved.text
    detail = _detail(client, production_id)
    assert detail["summary"]["state"] == "READY", detail["events"][-3:]

    # Every shot generated; every one of the 10 logical agents ran.
    shots = [shot for scene in detail["manifest"]["scenes"] for shot in scene["shots"]]
    assert shots and all(shot["status"] == "complete" for shot in shots)
    ran = {run["agent_id"] for run in detail["agent_runs"] if run["status"] == "succeeded"}
    assert ran == {a.value for a in AgentId}

    # Mock cost accounting: committed ledger, simulated, within the hard cap.
    cost = detail["cost"]
    assert cost["simulated"] is True
    assert 0 < cost["actual"] <= cost["limit"]
    assert cost["reserved"] == pytest.approx(0, abs=1e-6)
    ledger = client.get(f"/api/v1/productions/{production_id}/ledger").json()
    assert ledger and {e["status"] for e in ledger} <= {"committed", "failed"}
    assert all(e["provider"].startswith("mock-") for e in ledger)

    # Master render exists, passed QC and is downloadable (Range supported).
    master = detail["artifacts"]["master"]
    assert master["width"] == 1080 and master["height"] == 1920
    assert master["duration_sec"] == pytest.approx(45 + END_CARD_SEC, abs=0.5)
    assert detail["artifacts"]["review"]["passed"] is True
    asset_id = detail["manifest"]["master_render_asset_id"]
    content = client.get(f"/api/v1/assets/{asset_id}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "video/mp4"
    assert content.content[4:8] == b"ftyp"
    ranged = client.get(f"/api/v1/assets/{asset_id}/content", headers={"Range": "bytes=0-99"})
    assert ranged.status_code == 206 and len(ranged.content) == 100
    # Media lives in the storage root, not the repository.
    assert list((tmp_path / "media").rglob("*.mp4"))

    # Tenant isolation on assets.
    other = client.get(f"/api/v1/assets/{asset_id}/content", headers={"X-Tenant-Id": "other"})
    assert other.status_code == 404

    delivered = client.post(f"/api/v1/productions/{production_id}/deliver")
    assert delivered.status_code == 200, delivered.text
    assert _detail(client, production_id)["summary"]["state"] == "DELIVERED"
    assert client.post(f"/api/v1/productions/{production_id}/deliver").status_code == 409


def test_budget_gate_pauses_then_resumes_with_raised_cap(client: TestClient) -> None:
    created = client.post(
        "/api/v1/productions",
        json={"topic": TOPIC, "budget_limit_usd": 0.25, "auto_approve": True},
    )
    production_id = created.json()["summary"]["id"]
    client.post(f"/api/v1/productions/{production_id}/run")
    detail = _detail(client, production_id)
    assert detail["summary"]["state"] == "PAUSED_BUDGET"
    assert detail["cost"]["actual"] <= 0.25

    resumed = client.post(
        f"/api/v1/productions/{production_id}/approve",
        json={"approved_by": "e2e", "raise_budget_to_usd": 25},
    )
    assert resumed.status_code == 202, resumed.text
    detail = _detail(client, production_id)
    assert detail["summary"]["state"] == "READY"
    assert detail["cost"]["actual"] <= 25


def test_transient_provider_failures_are_retried_and_bounded(flaky_client: TestClient) -> None:
    """At a 30% simulated failure rate, retries happen and every outcome is a valid one:
    READY, or FAILED with an attempts-exhausted event (never a stuck production)."""
    created = flaky_client.post("/api/v1/productions", json={"topic": TOPIC, "auto_approve": True})
    production_id = created.json()["summary"]["id"]
    flaky_client.post(f"/api/v1/productions/{production_id}/run")
    detail = _detail(flaky_client, production_id)
    assert detail["summary"]["state"] in {"READY", "FAILED"}
    assert detail["cost"]["retry_count"] > 0
    attempts = [len(s["attempts"]) for sc in detail["manifest"]["scenes"] for s in sc["shots"]]
    assert max(attempts) <= 3  # balanced max_attempts_per_shot
    if detail["summary"]["state"] == "FAILED":
        assert any(e["event_type"] == "failed" for e in detail["events"])
    assert detail["cost"]["actual"] <= detail["cost"]["limit"]


def test_cost_overview_and_catalog(client: TestClient) -> None:
    created = client.post("/api/v1/productions", json={"topic": TOPIC, "auto_approve": True})
    client.post(f"/api/v1/productions/{created.json()['summary']['id']}/run")
    overview = client.get("/api/v1/costs/overview").json()
    assert overview["production_count"] == 1
    assert overview["total_actual"] > 0 and overview["simulated"] is True
    assert overview["credit_balances"]
    pricing = client.get("/api/v1/pricing").json()
    assert len([p for p in pricing if p["version"] == "mock-2026-10"]) == 11
