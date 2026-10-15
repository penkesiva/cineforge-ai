"""Persona routes: list, detail with canon, reference images per tenant."""

from __future__ import annotations

from cineforge.contracts.media import persona_storage_key


def test_list_and_detail_without_images(api) -> None:
    listed = api.client.get("/api/v1/personas")
    assert listed.status_code == 200
    lena = next(p for p in listed.json() if p["id"] == "lena-voss")
    assert lena["version"] == 2 and lena["age"] == 23 and lena["voice_name"] == "Juno"
    assert lena["reference_count"] == 19 and lena["references_available"] == 0
    assert lena["cover_url"] is None

    detail = api.client.get("/api/v1/personas/lena-voss").json()
    assert detail["versions"] == [1, 2]
    assert detail["profile"]["voice"]["candidates"][1]["name"] == "Gia"
    assert detail["canon"]["facts"]
    assert all(not r["available"] and r["url"] is None for r in detail["references"])

    v1 = api.client.get("/api/v1/personas/lena-voss", params={"version": 1}).json()
    assert v1["summary"]["version"] == 1

    assert api.client.get("/api/v1/personas/nobody").status_code == 404
    assert api.client.get("/api/v1/personas/lena-voss?version=9").status_code == 404


def test_reference_image_streams_only_when_stored(api) -> None:
    detail = api.client.get("/api/v1/personas/lena-voss").json()
    front = next(r for r in detail["references"] if r["angle"] == "front")
    url = f"/api/v1/personas/lena-voss/references/{front['id']}"
    assert api.client.get(url).status_code == 404

    key = persona_storage_key("tenant_demo", "lena-voss", front["file"])
    api.rt.storage.put_bytes(key, b"tiny", "image/png")

    got = api.client.get(url)
    assert got.status_code == 200
    assert got.content == b"tiny" and got.headers["content-type"] == "image/png"
    summary = next(p for p in api.client.get("/api/v1/personas").json() if p["id"] == "lena-voss")
    assert summary["references_available"] == 1 and summary["cover_url"] == url
    assert api.client.get("/api/v1/personas/lena-voss/references/ref_nope").status_code == 404
