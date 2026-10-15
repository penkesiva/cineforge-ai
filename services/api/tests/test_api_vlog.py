"""Vlog gates over HTTP: stage quote, approve per stage, shot redo."""

from __future__ import annotations

from cineforge.cost.factory import load_price_catalog


def _vlog(api) -> str:
    catalog = load_price_catalog(api.rt.settings)
    api.rt.__dict__["price_catalog"] = catalog
    api.fx.guard.catalog = catalog
    body = {
        "topic": "A day at the 1889 World's Fair",
        "theme_id": "lena-vlog",
        "mode": "premium",
        "duration_target_sec": 75,
        "budget_limit_usd": "100",
    }
    created = api.client.post("/api/v1/productions", json=body)
    assert created.status_code == 201, created.text
    pid = created.json()["summary"]["id"]
    assert api.client.post(f"/api/v1/productions/{pid}/run").status_code == 202
    return pid


def test_stage_quote_and_gates(api) -> None:
    pid = _vlog(api)
    detail = api.client.get(f"/api/v1/productions/{pid}").json()
    assert detail["summary"]["state"] == "AWAITING_APPROVAL"
    assert detail["summary"]["approval_stage"] == "script"

    quote = api.client.get(f"/api/v1/productions/{pid}/stage-quote").json()
    assert quote["stage"] == "preview" and quote["items"] > 0
    assert float(quote["credits"]) > 0 and quote["credit_cap"] == "300"

    shot_id = detail["manifest"]["scenes"][0]["shots"][0]["id"]
    early = api.client.post(
        f"/api/v1/productions/{pid}/shots/{shot_id}/regenerate", json={"target": "still"}
    )
    assert early.status_code == 409
    assert early.json()["error"] == "regenerate_blocked"

    assert api.client.post(f"/api/v1/productions/{pid}/approve").status_code == 202
    summary = api.client.get(f"/api/v1/productions/{pid}").json()["summary"]
    assert summary["approval_stage"] == "preview"

    redo = api.client.post(
        f"/api/v1/productions/{pid}/shots/{shot_id}/regenerate",
        json={"target": "still", "note": "golden hour"},
    )
    assert redo.status_code == 202, redo.text
    assert redo.json()["job_id"].endswith(f"{shot_id}:still:2")


def test_stage_quote_404_for_classic_theme(api) -> None:
    created = api.client.post("/api/v1/productions", json={"topic": "Eiffel Tower lights"})
    pid = created.json()["summary"]["id"]
    assert api.client.get(f"/api/v1/productions/{pid}/stage-quote").status_code == 404
