"""Phase 1 API: theme registry, claim review, script rewrite, health provider mode."""

from __future__ import annotations

TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"


def _at_gate(api) -> str:
    res = api.client.post("/api/v1/productions", json={"topic": TOPIC})
    assert res.status_code == 201, res.text
    pid = res.json()["summary"]["id"]
    api.client.post(f"/api/v1/productions/{pid}/run")
    assert api.client.get(f"/api/v1/productions/{pid}").json()["summary"]["state"] == (
        "AWAITING_APPROVAL"
    )
    return pid


def _cited_claims(api, pid: str) -> list[str]:
    detail = api.client.get(f"/api/v1/productions/{pid}").json()
    return sorted({cid for scene in detail["manifest"]["scenes"] for cid in scene["facts"]})


def test_health_reports_provider_mode(api) -> None:
    assert api.client.get("/health").json()["provider_mode"] == "mock"


def test_theme_versions_create_get_and_conflict(api) -> None:
    base = api.client.get("/api/v1/themes/time-traveler").json()
    edited = base | {"tone": "Hushed and reverent", "id": "ignored-by-server"}
    res = api.client.post(
        "/api/v1/themes/time-traveler/versions",
        json={"base_version": base["version"], "profile": edited},
    )
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["id"] == "time-traveler"
    assert created["version"] == base["version"] + 1
    assert created["tone"] == "Hushed and reverent"

    latest = api.client.get("/api/v1/themes/time-traveler").json()
    assert latest["version"] == created["version"]
    old = api.client.get(f"/api/v1/themes/time-traveler?version={base['version']}").json()
    assert old["tone"] == base["tone"]
    versions = api.client.get("/api/v1/themes/time-traveler/versions").json()
    assert [v["version"] for v in versions] == [base["version"], created["version"]]
    summary = next(t for t in api.client.get("/api/v1/themes").json() if t["id"] == base["id"])
    assert summary["version"] == created["version"]

    stale = api.client.post(
        "/api/v1/themes/time-traveler/versions",
        json={"base_version": base["version"], "profile": edited},
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "theme_version_conflict"
    assert api.client.get("/api/v1/themes/time-traveler?version=99").status_code == 404
    assert api.client.get("/api/v1/themes/nope/versions").status_code == 404


def test_create_production_with_theme_version(api) -> None:
    base = api.client.get("/api/v1/themes/time-traveler").json()
    api.client.post(
        "/api/v1/themes/time-traveler/versions",
        json={"base_version": base["version"], "profile": base | {"tone": "Different"}},
    )
    res = api.client.post(
        "/api/v1/productions", json={"topic": TOPIC, "theme_version": base["version"]}
    )
    assert res.status_code == 201
    assert res.json()["summary"]["theme_version"] == base["version"]
    bad = api.client.post("/api/v1/productions", json={"topic": TOPIC, "theme_version": 42})
    assert bad.status_code == 422


def test_claim_review_blocks_approval_then_rewrite_unblocks(api) -> None:
    pid = _at_gate(api)
    cited = _cited_claims(api, pid)
    res = api.client.post(
        f"/api/v1/productions/{pid}/claims",
        json={
            "reviewed_by": "editor",
            "decisions": [{"claim_id": cited[0], "decision": "rejected", "note": "weak source"}],
        },
    )
    assert res.status_code == 200, res.text
    reviews = res.json()["manifest"]["claim_reviews"]
    assert reviews[-1]["claim_id"] == cited[0] and reviews[-1]["decision"] == "rejected"

    blocked = api.client.post(f"/api/v1/productions/{pid}/approve")
    assert blocked.status_code == 409
    assert blocked.json()["error"] == "approval_blocked"

    rewrite = api.client.post(f"/api/v1/productions/{pid}/rewrite-script")
    assert rewrite.status_code == 202, rewrite.text
    assert cited[0] not in _cited_claims(api, pid)
    assert api.client.post(f"/api/v1/productions/{pid}/approve").status_code == 202


def test_claim_review_validation(api) -> None:
    pid = _at_gate(api)
    unknown = api.client.post(
        f"/api/v1/productions/{pid}/claims",
        json={"decisions": [{"claim_id": "claim_99", "decision": "rejected"}]},
    )
    assert unknown.status_code == 422
    empty = api.client.post(f"/api/v1/productions/{pid}/claims", json={"decisions": []})
    assert empty.status_code == 422
    draft = api.client.post("/api/v1/productions", json={"topic": TOPIC}).json()["summary"]["id"]
    wrong_state = api.client.post(
        f"/api/v1/productions/{draft}/claims",
        json={"decisions": [{"claim_id": "claim_01", "decision": "approved"}]},
    )
    assert wrong_state.status_code == 409
    assert api.client.post(f"/api/v1/productions/{draft}/rewrite-script").status_code == 409
