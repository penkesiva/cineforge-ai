"""Vlog gates over HTTP: stage quote, approve per stage, shot redo."""

from __future__ import annotations

from cineforge.cost.factory import load_price_catalog
from cineforge.media.factory import build_rights_gate


def _credit_prices(api) -> None:
    catalog = load_price_catalog(api.rt.settings)
    api.rt.__dict__["price_catalog"] = catalog
    api.fx.guard.catalog = catalog


def _vlog(api) -> str:
    _credit_prices(api)
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


def _upload(api, **params) -> dict:
    query = {"name": "Hanging pillar", "author": "Owner", "generator": "ChatGPT", **params}
    res = api.client.post(
        "/api/v1/assets/references",
        params=query,
        content=b"\x89PNG-bytes",
        headers={"content-type": "image/png"},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _brief(asset_id: str) -> dict:
    return {
        "topic": "Lepakshi temple",
        "theme_id": "lena-vlog",
        "mode": "premium",
        "duration_target_sec": 75,
        "look": {
            "wardrobe": "an ivory Kalamkari kurta over jeans",
            "location": "a granite temple hall",
            "references": [{"id": "ref_pillar", "asset_id": asset_id, "description": "pillar"}],
        },
        "script": {
            "lines": [
                {"scene_order": 1, "kind": "dialogue", "text": "Wait. Is it floating?"},
                {"scene_order": 1, "kind": "broll", "voiceover": True, "text": "No strings.",
                 "refs": ["ref_pillar"]},
            ]
        },
    }  # fmt: skip


def test_reference_upload_is_rights_checked_and_usable_in_a_brief(api) -> None:
    _credit_prices(api)
    api.rt.__dict__["rights_gate"] = build_rights_gate(api.rt.settings)
    owned = _upload(api, commercial_use=True)
    assert owned["kind"] == "reference" and owned["origin"] == "uploaded"
    assert owned["rights"]["status"] == "approved"
    assert owned["metadata"] == {
        "usage": "reference_only",
        "description": "",
        "ai_generated": True,
        "generator": "ChatGPT",
    }
    assert owned["storage_key"].startswith("tenants/tenant_demo/library/reference/hanging-pillar-")
    assert api.rt.storage.open(owned["storage_key"]).read() == b"\x89PNG-bytes"

    unknown = _upload(api)
    assert unknown["rights"]["status"] != "approved"

    created = api.client.post("/api/v1/productions", json=_brief(owned["id"]))
    assert created.status_code == 201, created.text
    manifest = api.client.get(f"/api/v1/productions/{created.json()['summary']['id']}").json()
    assert manifest["manifest"]["look"]["references"][0]["asset_id"] == owned["id"]

    blocked = api.client.post("/api/v1/productions", json=_brief(unknown["id"]))
    assert blocked.status_code == 422
    assert blocked.json()["error"] == "invalid_production_input"


def test_reference_upload_rejects_non_images(api) -> None:
    res = api.client.post(
        "/api/v1/assets/references",
        params={"name": "notes", "author": "Owner"},
        content=b"hello",
        headers={"content-type": "text/plain"},
    )
    assert res.status_code == 415
