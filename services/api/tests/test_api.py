"""API tests (TestClient) against memory repos, inline queue and fakes for Workstream D."""

from __future__ import annotations

import pytest
from cineforge.config import Settings
from cineforge.contracts.workflow import ProductionState

S = ProductionState
TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"
OTHER = {"X-Tenant-Id": "tenant_other"}


def _create(api, **body) -> dict:
    res = api.client.post("/api/v1/productions", json={"topic": TOPIC} | body)
    assert res.status_code == 201, res.text
    return res.json()


# --------------------------------------------------------------------------- health + meta
def test_health_live_and_health_ok(api) -> None:
    assert api.client.get("/health/live").json() == {"status": "ok"}
    body = api.client.get("/health").json()
    assert body["status"] == "ok"
    assert body["service"] == "cineforge-api"
    assert body["paid_providers_enabled"] is False
    assert {c["name"]: c["status"] for c in body["checks"]} == {
        "database": "ok",
        "redis": "ok",
        "storage": "ok",
    }
    assert api.fx.storage.objects == {}  # probe cleaned up


def test_health_degraded_when_dependencies_fail(api, monkeypatch: pytest.MonkeyPatch) -> None:
    api.rt.settings = Settings(
        persistence_backend="postgres",
        database_url="postgresql://nobody:nothing@127.0.0.1:1/none",
        queue_backend="redis",
        redis_url="redis://127.0.0.1:1/0",
        allow_paid_providers=True,
    )

    def broken(*_, **__):
        raise OSError("disk full")

    monkeypatch.setattr(api.fx.storage, "put_bytes", broken)
    body = api.client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["paid_providers_enabled"] is True
    assert {c["name"]: c["status"] for c in body["checks"]} == {
        "database": "down",
        "redis": "down",
        "storage": "down",
    }


def test_openapi_and_docs(api) -> None:
    spec = api.client.get("/openapi.json").json()
    assert spec["info"]["title"] == "CineForge AI API"
    assert spec["info"]["version"] == api.rt.settings.app_version
    assert "/api/v1/productions/{production_id}/approve" in spec["paths"]
    assert {t["name"] for t in spec["tags"]} >= {"productions", "costs", "agents", "health"}
    assert api.client.get("/docs").status_code == 200


def test_cors_allows_dashboard_origin(api) -> None:
    res = api.client.options(
        "/api/v1/agents",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert res.headers["access-control-allow-origin"] == "http://localhost:3000"


# --------------------------------------------------------------------------- catalog
def test_agents_themes_modes_pricing(api) -> None:
    agents = api.client.get("/api/v1/agents").json()
    assert [a["code"] for a in agents] == [f"A{i}" for i in range(1, 11)]
    themes = api.client.get("/api/v1/themes").json()
    assert {t["id"] for t in themes} == {"time-traveler", "mystery-explorer", "fascinating-places"}
    theme = api.client.get("/api/v1/themes/time-traveler").json()
    assert theme["narrative"]["story_beats"][0] == "hook"
    missing = api.client.get("/api/v1/themes/nope")
    assert missing.status_code == 404 and missing.json()["error"] == "not_found"
    modes = api.client.get("/api/v1/modes").json()
    assert [m["mode"] for m in modes] == ["economy", "balanced", "premium"]
    pricing = api.client.get("/api/v1/pricing").json()
    assert len(pricing) == len(api.rt.price_catalog.entries())
    assert {p["provider"] for p in pricing} >= {"mock-video", "mock-llm"}


# --------------------------------------------------------------------------- lifecycle
def test_create_run_approve_ready_deliver(api) -> None:
    detail = _create(api, title="Eiffel 1889", mode="balanced")
    pid = detail["summary"]["id"]
    assert detail["summary"]["state"] == "DRAFT"
    assert detail["summary"]["progress_pct"] == 0
    assert detail["summary"]["budget_limit"] == 10.0
    assert detail["cost"]["limit"] == 10.0
    assert [e["event_type"] for e in detail["events"]] == ["created"]
    assert detail["agent_runs"] == []

    run = api.client.post(f"/api/v1/productions/{pid}/run")
    assert run.status_code == 202
    assert run.json()["state"] == "RESEARCHING"
    assert run.json()["job_id"] == f"{pid}:RESEARCHING:1"

    detail = api.client.get(f"/api/v1/productions/{pid}").json()
    assert detail["summary"]["state"] == "AWAITING_APPROVAL"
    assert detail["summary"]["scene_count"] == 5
    assert detail["summary"]["shot_count"] == 10
    assert detail["summary"]["estimated_cost"] > 0
    arts = detail["artifacts"]
    for key in ("plan", "treatment", "research", "media", "script", "cost_plan"):
        assert arts[key] is not None, key
    assert arts["review"] is None and arts["master"] is None
    assert arts["media"]["blocked"]
    assert detail["cost"]["estimated"] == arts["cost_plan"]["estimate"]["total_estimated"]
    assert len(detail["agent_runs"]) == 7

    approve = api.client.post(f"/api/v1/productions/{pid}/approve")  # empty body allowed
    assert approve.status_code == 202
    assert approve.json()["state"] == "GENERATING"

    detail = api.client.get(f"/api/v1/productions/{pid}").json()
    summary = detail["summary"]
    assert summary["state"] == "READY"
    assert summary["progress_pct"] == 89
    assert 0 < summary["actual_cost"] <= summary["budget_limit"]
    assert detail["artifacts"]["review"]["status"] == "passed"
    assert detail["artifacts"]["review"]["passed"] is True
    master = detail["artifacts"]["master"]
    assert master["asset_id"] == detail["manifest"]["master_render_asset_id"]
    assert [a["id"] for a in detail["assets"]] == [master["asset_id"]]

    content = api.client.get(f"/api/v1/assets/{master['asset_id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "video/mp4"
    assert content.content == b"FAKE-MP4:" + pid.encode()

    costs = api.client.get(f"/api/v1/productions/{pid}/costs").json()
    assert costs["production_id"] == pid and costs["actual"] == summary["actual_cost"]
    ledger = api.client.get(f"/api/v1/productions/{pid}/ledger").json()
    assert ledger and all(e["production_id"] == pid for e in ledger)
    overview = api.client.get("/api/v1/costs/overview").json()
    assert overview["tenant_id"] == "tenant_demo" and overview["production_count"] == 1

    delivered = api.client.post(f"/api/v1/productions/{pid}/deliver")
    assert delivered.status_code == 200
    assert delivered.json()["state"] == "DELIVERED"
    assert api.client.get(f"/api/v1/productions/{pid}").json()["summary"]["progress_pct"] == 100


def test_auto_approve_and_budget_raise_via_api(api) -> None:
    pid = _create(api, auto_approve=True)["summary"]["id"]
    api.client.post(f"/api/v1/productions/{pid}/run")
    assert api.client.get(f"/api/v1/productions/{pid}").json()["summary"]["state"] == "READY"

    tight = _create(api, budget_limit_usd=0.5)["summary"]["id"]
    api.client.post(f"/api/v1/productions/{tight}/run")
    assert api.client.get(f"/api/v1/productions/{tight}").json()["summary"]["state"] == (
        "PAUSED_BUDGET"
    )
    res = api.client.post(
        f"/api/v1/productions/{tight}/approve",
        json={"approved_by": "cfo", "note": "ok", "raise_budget_to_usd": 25},
    )
    assert res.status_code == 202
    detail = api.client.get(f"/api/v1/productions/{tight}").json()
    assert detail["summary"]["state"] == "READY"
    assert detail["summary"]["budget_limit"] == 25.0
    assert detail["manifest"]["approval"]["approved_by"] == "cfo"


def test_cancel_and_list_newest_first(api) -> None:
    first = _create(api)["summary"]["id"]
    second = _create(api, topic="Machu Picchu at dawn")["summary"]["id"]
    listed = [p["id"] for p in api.client.get("/api/v1/productions").json()]
    assert listed[:2] == [second, first]
    res = api.client.post(f"/api/v1/productions/{first}/cancel")
    assert res.status_code == 200 and res.json()["state"] == "CANCELLED"


def test_create_is_idempotent(api) -> None:
    a = _create(api, idempotency_key="dash-1")["summary"]["id"]
    b = _create(api, idempotency_key="dash-1")["summary"]["id"]
    assert a == b
    assert len(api.client.get("/api/v1/productions").json()) == 1


# --------------------------------------------------------------------------- errors
def test_not_found_errors(api) -> None:
    for method, path in [
        ("get", "/api/v1/productions/prod_missing"),
        ("post", "/api/v1/productions/prod_missing/run"),
        ("post", "/api/v1/productions/prod_missing/approve"),
        ("post", "/api/v1/productions/prod_missing/cancel"),
        ("post", "/api/v1/productions/prod_missing/deliver"),
        ("get", "/api/v1/productions/prod_missing/costs"),
        ("get", "/api/v1/productions/prod_missing/ledger"),
        ("get", "/api/v1/assets/asset_missing/content"),
    ]:
        res = getattr(api.client, method)(path)
        assert res.status_code == 404, path
        assert res.json()["error"] == "not_found"


def test_conflict_errors(api) -> None:
    pid = _create(api)["summary"]["id"]
    res = api.client.post(f"/api/v1/productions/{pid}/deliver")
    assert res.status_code == 409
    body = res.json()
    assert body["error"] == "invalid_state_transition"
    assert body["detail"]["from_state"] == "DRAFT" and body["detail"]["to_state"] == "DELIVERED"
    assert api.client.post(f"/api/v1/productions/{pid}/approve").status_code == 409
    api.client.post(f"/api/v1/productions/{pid}/run")
    assert api.client.post(f"/api/v1/productions/{pid}/run").status_code == 409


@pytest.mark.parametrize(
    "body",
    [
        {"topic": "x"},
        {"topic": TOPIC, "mode": "ultra"},
        {"topic": TOPIC, "duration_target_sec": 0},
        {"topic": TOPIC, "unexpected": True},
        {"topic": TOPIC, "theme_id": "no-such-theme"},
    ],
)
def test_validation_errors(api, body: dict) -> None:
    res = api.client.post("/api/v1/productions", json=body)
    assert res.status_code == 422, res.text
    assert res.json()["error"] == "validation_error"


def test_invalid_tenant_header_is_rejected(api) -> None:
    res = api.client.get("/api/v1/productions", headers={"X-Tenant-Id": "bad tenant!"})
    assert res.status_code == 422


# --------------------------------------------------------------------------- tenancy
def test_tenant_isolation(api) -> None:
    theirs = api.client.post(
        "/api/v1/productions", json={"topic": TOPIC, "auto_approve": True}, headers=OTHER
    )
    assert theirs.status_code == 201
    pid = theirs.json()["summary"]["id"]
    assert theirs.json()["summary"]["tenant_id"] == "tenant_other"
    api.client.post(f"/api/v1/productions/{pid}/run", headers=OTHER)
    detail = api.client.get(f"/api/v1/productions/{pid}", headers=OTHER).json()
    assert detail["summary"]["state"] == "READY"
    asset_id = detail["manifest"]["master_render_asset_id"]

    assert api.client.get(f"/api/v1/productions/{pid}").status_code == 404
    assert api.client.post(f"/api/v1/productions/{pid}/cancel").status_code == 404
    assert api.client.get(f"/api/v1/productions/{pid}/ledger").status_code == 404
    assert api.client.get(f"/api/v1/assets/{asset_id}/content").status_code == 404
    assert api.client.get(f"/api/v1/assets/{asset_id}/content", headers=OTHER).status_code == 200
    assert api.client.get("/api/v1/productions").json() == []
    assert [p["id"] for p in api.client.get("/api/v1/productions", headers=OTHER).json()] == [pid]
    assert api.client.get("/api/v1/costs/overview").json()["production_count"] == 0
    assert api.client.get("/api/v1/costs/overview", headers=OTHER).json()["production_count"] == 1


def test_asset_content_missing_blob_is_404(api) -> None:
    pid = _create(api, auto_approve=True)["summary"]["id"]
    api.client.post(f"/api/v1/productions/{pid}/run")
    asset_id = api.client.get(f"/api/v1/productions/{pid}").json()["manifest"][
        "master_render_asset_id"
    ]
    api.fx.storage.objects.clear()
    assert api.client.get(f"/api/v1/assets/{asset_id}/content").status_code == 404
