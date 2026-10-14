from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus, AssetCandidate, AssetSelection
from cineforge.contracts.common import AgentId
from cineforge.contracts.media import AssetKind, AssetOrigin, LicenseInfo, RightsStatus
from cineforge.contracts.workflow import ProductionState
from cineforge.media import ingest
from cineforge.media.download import DownloadError, check_url, download, host_allowed
from cineforge.runtime import Runtime
from fakes_d import fake_runtime, small_manifest

PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 64
COMMONS_PAGE = "https://commons.wikimedia.org/wiki/File:Old_Town_Square.jpg"
FULL_URL = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab/x.jpg/1920px-x.jpg"


def _license(kind: str = "CC-BY-4.0", attribution: str | None = "Photo by A") -> LicenseInfo:
    return LicenseInfo(
        license_type=kind,
        attribution_text=attribution,
        attribution_required=True,
        source_provider="wikimedia-commons",
        source_url=COMMONS_PAGE,
    )


def _candidate(cid: str = "asset_cand_x_01", **kw) -> AssetCandidate:
    data = {
        "candidate_id": cid,
        "provider": "wikimedia-commons",
        "media_type": "image",
        "title": "Old Town Square",
        "source_url": COMMONS_PAGE,
        "thumbnail_url": "https://upload.wikimedia.org/thumb/640px-x.jpg",
        "license": _license(),
        "rights_status": RightsStatus.APPROVED,
        "score": 0.9,
    }
    data.update(kw)
    return AssetCandidate(**data)


class Recorder:
    def __init__(self, image: bytes = JPEG, content_type: str = "image/jpeg") -> None:
        self.calls: list[str] = []
        self.image, self.content_type = image, content_type

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if request.url.host == "commons.wikimedia.org":
            assert request.url.params["titles"] == "File:Old Town Square.jpg"
            assert request.url.params["iiurlwidth"] == "1920"
            return httpx.Response(
                200, json={"query": {"pages": [{"imageinfo": [{"thumburl": FULL_URL}]}]}}
            )
        if request.url.host == "upload.wikimedia.org":
            return httpx.Response(
                200, content=self.image, headers={"content-type": self.content_type}
            )
        return httpx.Response(404)


@pytest.fixture
def rt(tmp_path: Path) -> Runtime:
    runtime = fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
        )
    )
    manifest = small_manifest()
    manifest.state = ProductionState.READY
    runtime.productions.create(manifest)
    return runtime


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# ----------------------------------------------------------------------------- download
def test_check_url_rules() -> None:
    assert check_url("https://upload.wikimedia.org/x.jpg", resolver=PUBLIC)
    with pytest.raises(DownloadError, match="https"):
        check_url("http://upload.wikimedia.org/x.jpg", resolver=PUBLIC)
    for private in ("127.0.0.1", "10.0.0.5", "192.168.1.2", "169.254.1.1", "::1"):
        with pytest.raises(DownloadError, match="non-public"):
            check_url("https://evil.example/x", resolver=lambda h, ip=private: [ip])
    with pytest.raises(DownloadError, match="allowlist"):
        check_url("https://cdn.other.com/x", resolver=PUBLIC, allowed_hosts=[".higgsfield.ai"])
    assert host_allowed("d1.cdn.higgsfield.ai", [".higgsfield.ai"])
    assert host_allowed("higgsfield.ai", [".higgsfield.ai"])
    assert not host_allowed("higgsfield.ai.evil.com", [".higgsfield.ai"])


def test_download_rechecks_every_redirect_hop() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.example":
            return httpx.Response(302, headers={"location": "https://b.example/f.jpg"})
        return httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"})

    got = download(
        _client(handler), "https://a.example/f", allowed_types=("image/",), max_bytes=1000,
        resolver=PUBLIC,
    )  # fmt: skip
    assert got.data == JPEG and got.final_url == "https://b.example/f.jpg"

    def resolver(host: str) -> list[str]:
        return ["10.0.0.1"] if host == "b.example" else ["93.184.216.34"]

    with pytest.raises(DownloadError, match="non-public"):
        download(
            _client(handler), "https://a.example/f", allowed_types=("image/",), max_bytes=1000,
            resolver=resolver,
        )  # fmt: skip


def test_download_enforces_type_and_size() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/html":
            return httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"})
        return httpx.Response(200, content=b"x" * 2000, headers={"content-type": "image/png"})

    client = _client(handler)
    with pytest.raises(DownloadError, match="content type"):
        download(client, "https://a.example/html", allowed_types=("image/",), max_bytes=10_000,
                 resolver=PUBLIC)  # fmt: skip
    with pytest.raises(DownloadError, match="larger"):
        download(client, "https://a.example/big", allowed_types=("image/png",), max_bytes=1000,
                 resolver=PUBLIC)  # fmt: skip


# ------------------------------------------------------------------------------- ingest
def test_ingest_commons_still(rt: Runtime) -> None:
    manifest = small_manifest()
    rt.budget.create_budget(
        tenant_id=manifest.tenant_id, production_id=manifest.production_id, limit=Decimal(5)
    )
    rec = Recorder()
    asset = ingest.ingest_still(rt, manifest, _candidate(), client=_client(rec), resolver=PUBLIC)

    assert asset is not None
    assert asset.kind == AssetKind.IMAGE and asset.origin == AssetOrigin.OPEN_LICENSE
    assert asset.storage_key.endswith("/image/asset_cand_x_01.jpg")
    assert asset.license.attribution_text == "Photo by A"
    assert asset.rights.status == RightsStatus.APPROVED
    assert asset.metadata["candidate_id"] == "asset_cand_x_01"
    assert asset.metadata["download_url"] == FULL_URL
    assert rt.storage.local_path(asset.storage_key).read_bytes() == JPEG
    (event,) = rt.budget.ledger(manifest.production_id)
    assert (event.provider, event.model) == ("wikimedia-commons", "file-download")
    assert event.actual_cost == 0

    again = ingest.ingest_still(rt, manifest, _candidate(), client=_client(rec), resolver=PUBLIC)
    assert again.id == asset.id and len(rec.calls) == 2


@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(license=_license("CC-BY-ND-4.0")),
        _candidate(license=_license("CC-BY-SA-4.0")),
        _candidate(license=None),
        _candidate(provider="mock-media-search"),
        _candidate(media_type="video"),
    ],
    ids=["no-derivatives", "share-alike-pending", "no-license", "mock", "video"],
)
def test_ingest_refuses_unusable_candidates(rt: Runtime, candidate: AssetCandidate) -> None:
    rec = Recorder()
    got = ingest.ingest_still(rt, small_manifest(), candidate, client=_client(rec), resolver=PUBLIC)
    assert got is None and rec.calls == []
    assert rt.assets.list_for_production(small_manifest().production_id, "tenant_demo") == []


def test_ingest_skips_non_image_download(rt: Runtime) -> None:
    rec = Recorder(image=b"<html>", content_type="text/html")
    got = ingest.ingest_still(
        rt, small_manifest(), _candidate(), client=_client(rec), resolver=PUBLIC
    )
    assert got is None


def test_openverse_resolves_original_url() -> None:
    uid = "0aff3595-8168-440b-83ff-7a80b65dea42"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"/v1/images/{uid}/"
        return httpx.Response(200, json={"url": "https://live.staticflickr.com/1/x_b.jpg"})

    cand = _candidate(
        provider="openverse",
        thumbnail_url=f"https://api.openverse.org/v1/images/{uid}/thumb/",
        source_url="https://www.flickr.com/photos/x/1",
    )
    assert ingest.resolve_image_url(_client(handler), cand) == (
        "https://live.staticflickr.com/1/x_b.jpg"
    )


def test_commons_file_title() -> None:
    assert ingest.commons_file_title(COMMONS_PAGE) == "File:Old Town Square.jpg"
    assert ingest.commons_file_title("https://commons.wikimedia.org/wiki/Main_Page") is None


def test_latest_selection_reads_newest_a3_run(rt: Runtime) -> None:
    manifest = small_manifest()
    for i, cid in enumerate(("asset_cand_old", "asset_cand_new")):
        rt.agent_runs.runs[f"run_{i}"] = AgentRun(
            id=f"run_{i}",
            production_id=manifest.production_id,
            tenant_id=manifest.tenant_id,
            agent_id=AgentId.MEDIA_DISCOVERY,
            step=ProductionState.RESEARCHING,
            status=AgentRunStatus.SUCCEEDED,
            idempotency_key=f"k{i}",
            output=AssetSelection(candidates=[_candidate(cid)]).model_dump(mode="json"),
            output_model="AssetSelection",
        )
    selection = ingest.latest_selection(rt, manifest)
    assert list(ingest.candidates_by_id(selection)) == ["asset_cand_new"]
