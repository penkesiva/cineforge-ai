from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.manifest import AssetRef, AssetRole, ProductionManifest
from cineforge.contracts.workflow import ProductionState
from cineforge.orchestration import external
from cineforge.runtime import Runtime, set_runtime
from cineforge_api.main import create_app
from fakes_d import fake_runtime, small_manifest
from fastapi.testclient import TestClient

CDN = "https://d8j0ntlcm91z4.cloudfront.net/user_x/hf_clip.mp4"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "d8j0ntlcm91z4.cloudfront.net":
        return httpx.Response(200, content=b"\x00" * 64, headers={"content-type": "video/mp4"})
    return httpx.Response(404)


def _make(tmp_path: Path, *, paid: bool) -> tuple[Runtime, ProductionManifest]:
    rt = fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
            allow_paid_providers=paid,
        )
    )
    m = small_manifest()
    m.state = ProductionState.READY
    m.scenes[0].shots[0].assets.append(AssetRef(asset_id="asset_cand_x", role=AssetRole.SOURCE))
    rt.productions.create(m)
    rt.budget.create_budget(tenant_id=m.tenant_id, production_id=m.production_id, limit=Decimal(5))
    set_runtime(rt)
    return rt, m


@pytest.fixture
def paid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple]:
    rt, m = _make(tmp_path, paid=True)
    monkeypatch.setattr(
        external,
        "build_http_client",
        lambda settings: httpx.Client(transport=httpx.MockTransport(_handler)),
    )
    monkeypatch.setattr(external, "resolve_host", lambda host: ["93.184.216.34"])
    with TestClient(create_app(rt.settings)) as client:
        yield client, rt, m
    set_runtime(None)


def _body(m: ProductionManifest, **kw) -> dict:
    scene = m.scenes[0]
    data = {
        "scene_id": scene.id,
        "shot_id": scene.shots[0].id,
        "provider": "higgsfield",
        "model": "kling2_6",
        "capability": "image_to_video",
        "quoted_credits": "5",
    }
    return data | kw


def _url(m: ProductionManifest, suffix: str = "") -> str:
    return f"/api/v1/productions/{m.production_id}/external-generations{suffix}"


def test_reserve_is_forbidden_without_paid_flag(tmp_path: Path) -> None:
    rt, m = _make(tmp_path, paid=False)
    with TestClient(create_app(rt.settings)) as client:
        r = client.post(_url(m), json=_body(m))
    set_runtime(None)
    assert r.status_code == 403 and r.json()["error"] == "paid_providers_disabled"


def test_reserve_complete_flow(paid) -> None:
    client, _, m = paid
    r = client.post(_url(m), json=_body(m, credit_cap="60"))
    assert r.status_code == 201, r.text
    event = r.json()["ledger_event"]
    assert event["status"] == "reserved" and Decimal(str(event["reserved_cost"])) == Decimal(
        "0.215"
    )

    done = {
        "result_url": CDN,
        "provider_request_id": "hf_job_9",
        "credits_used": "5",
        "prompt": "slow push",
    }
    r = client.post(_url(m, f"/{event['event_id']}/complete"), json=done)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ledger_event"]["status"] == "committed"
    assert body["asset"]["origin"] == "generated"
    assert body["asset"]["generation"]["job_id"] == "hf_job_9"

    detail = client.get(f"/api/v1/productions/{m.production_id}").json()
    shot = detail["manifest"]["scenes"][0]["shots"][0]
    assert shot["disclosure"]["label_text"] == "AI-generated"

    r = client.post(_url(m, f"/{event['event_id']}/release"), json={"reason": "late"})
    assert r.status_code == 422


def test_reserve_errors(paid) -> None:
    client, _, m = paid
    r = client.post(_url(m), json=_body(m, model="veo9"))
    assert r.status_code == 422 and r.json()["error"] == "unknown_price"
    r = client.post(_url(m), json=_body(m, quoted_credits="200"))
    assert r.status_code == 409 and r.json()["error"] == "budget_exceeded"
    r = client.post(_url(m), json=_body(m, credit_cap="3"))
    assert r.status_code == 409 and r.json()["error"] == "budget_exceeded"
    assert r.json()["detail"]["cap"] == "3"
    r = client.post(_url(m), json=_body(m), headers={"X-Tenant-Id": "tenant_other"})
    assert r.status_code == 404


def test_complete_rejects_foreign_host(paid) -> None:
    client, _, m = paid
    event = client.post(_url(m), json=_body(m)).json()["ledger_event"]
    r = client.post(
        _url(m, f"/{event['event_id']}/complete"),
        json={"result_url": "https://evil.example/x.mp4", "provider_request_id": "x",
              "credits_used": "5"},
    )  # fmt: skip
    assert r.status_code == 422 and "allowlist" in r.json()["detail"]
    r = client.post(_url(m, f"/{event['event_id']}/release"), json={"reason": "bad host"})
    assert r.status_code == 200 and r.json()["ledger_event"]["status"] == "failed"


def test_generation_pack_and_rerender(paid) -> None:
    client, rt, m = paid
    r = client.get(f"/api/v1/productions/{m.production_id}/generation-pack")
    assert r.status_code == 200, r.text
    pack = r.json()
    assert pack["aspect_ratio"] == "9:16" and len(pack["scenes"]) == len(m.scenes)

    r = client.post(f"/api/v1/productions/{m.production_id}/render", json={"reason": "clips"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert job_id.startswith(f"{m.production_id}:rerender:")
    assert rt.queue.jobs[-1][2]["force"] is True

    m2 = rt.productions.get(m.production_id, m.tenant_id)
    m2.state = ProductionState.NEEDS_REVIEW
    rt.productions.save(m2)
    r = client.post(f"/api/v1/productions/{m.production_id}/render")
    assert r.status_code == 409 and r.json()["error"] == "invalid_state"
