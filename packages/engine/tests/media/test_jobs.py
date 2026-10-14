from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from cineforge.config import Settings
from cineforge.contracts.agents import AgentRun, AgentRunStatus, MasterRender
from cineforge.contracts.common import AgentId
from cineforge.contracts.jobs import JOB_ADVANCE_PRODUCTION, QUEUE_AGENTS
from cineforge.contracts.media import AssetKind, AssetOrigin, RightsStatus
from cineforge.contracts.workflow import ProductionState
from cineforge.media import jobs
from cineforge.media.render import RenderError
from cineforge.runtime import Runtime, set_runtime
from fakes_d import (
    DATABASE_URL,
    DEMO_TENANT_ID,
    PgScratch,
    db_available,
    fake_runtime,
    small_manifest,
)

PID = "prod_sample0000000001"
TENANT = "tenant_demo"


@pytest.fixture
def rt(tmp_path: Path) -> Iterator[Runtime]:
    runtime = fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
        )
    )
    manifest = small_manifest()
    manifest.state = ProductionState.ASSEMBLING
    runtime.productions.create(manifest)
    set_runtime(runtime)
    yield runtime
    set_runtime(None)


def _call() -> str:
    return jobs.render_master(
        production_id=PID, tenant_id=TENANT, idempotency_key=f"{PID}:ASSEMBLING:render"
    )


@pytest.mark.ffmpeg
def test_render_master_end_to_end(
    require_ffmpeg: None, rt: Runtime, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    asset_id = _call()

    asset = rt.assets.get(asset_id, TENANT)
    assert asset is not None
    assert asset.kind == AssetKind.RENDER and asset.origin == AssetOrigin.RENDERED
    assert asset.storage_key == f"tenants/{TENANT}/productions/{PID}/render/master_v1.mp4"
    assert asset.uri == f"local://{asset.storage_key}"
    assert asset.rights.status == RightsStatus.APPROVED
    assert (asset.width, asset.height) == (180, 320)
    assert asset.duration_sec == pytest.approx(5.0, abs=0.5)
    assert asset.generation["renderer"] == "ffmpeg-slate"
    assert asset.generation["ffmpeg_version"]
    path = rt.storage.local_path(asset.storage_key)
    assert path.is_file() and path.is_relative_to(tmp_path)
    assert rt.assets.get(asset_id, "tenant_other") is None

    (run,) = rt.agent_runs.list_for_production(PID, TENANT)
    assert run.agent_id == AgentId.EDITOR_QC and run.step == ProductionState.ASSEMBLING
    assert run.status == AgentRunStatus.SUCCEEDED and run.output_model == "MasterRender"
    assert run.idempotency_key == f"{PID}:ASSEMBLING:a9_editor_qc:render:1"
    master = MasterRender.model_validate(run.output)
    assert master.asset_id == asset_id and master.codec == "h264" and master.audio_codec == "aac"
    assert master.sha256 == asset.sha256 and master.size_bytes == asset.size_bytes

    manifest = rt.productions.get(PID, TENANT)
    assert manifest.master_render_asset_id == asset_id
    assert manifest.state == ProductionState.ASSEMBLING
    assert manifest.audit[-1].action == "master_rendered"

    job_id = f"{PID}:ASSEMBLING:rendered"
    assert rt.queue.jobs == [
        (
            QUEUE_AGENTS,
            JOB_ADVANCE_PRODUCTION,
            {"production_id": PID, "tenant_id": TENANT, "idempotency_key": job_id},
            job_id,
        )
    ]

    # Second call: no re-render, same asset, advance re-enqueued with the same job id.
    def boom(*a, **k):
        raise AssertionError("must not re-render")

    monkeypatch.setattr(jobs, "render_master_slate", boom)
    assert _call() == asset_id
    assert len(rt.assets.list_for_production(PID, TENANT)) == 1
    assert len(rt.agent_runs.list_for_production(PID, TENANT)) == 1
    assert len(rt.queue.jobs) == 1


def test_failure_marks_run_and_production_failed(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*a, **k):
        raise RenderError("ffmpeg failed (1): synthetic")

    monkeypatch.setattr(jobs, "render_master_slate", broken)
    with pytest.raises(RenderError):
        _call()
    (run,) = rt.agent_runs.list_for_production(PID, TENANT)
    assert run.status == AgentRunStatus.FAILED and "synthetic" in run.error
    manifest = rt.productions.get(PID, TENANT)
    assert manifest.state == ProductionState.FAILED
    assert manifest.master_render_asset_id is None
    assert rt.queue.jobs == []
    assert rt.assets.list_for_production(PID, TENANT) == []


def test_blocking_qc_finding_fails_production(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_render(manifest, out_path):
        Path(out_path).write_bytes(b"not really a video")
        return Path(out_path)

    monkeypatch.setattr(jobs, "render_master_slate", fake_render)
    monkeypatch.setattr(jobs, "probe", lambda path: {"streams": [], "format": {}})
    with pytest.raises(RenderError, match="technical QC"):
        _call()
    assert rt.productions.get(PID, TENANT).state == ProductionState.FAILED
    assert not list((tmp_path / "media").rglob("*.mp4"))


def test_recovers_succeeded_run_without_rendering(
    rt: Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    master = MasterRender(
        asset_id="asset_prev",
        uri="local://x",
        duration_sec=5,
        width=180,
        height=320,
        fps=24,
        codec="h264",
        audio_codec="aac",
        size_bytes=10,
        sha256="00" * 32,
    )
    rt.agent_runs.runs["run_prev"] = AgentRun(
        id="run_prev",
        production_id=PID,
        tenant_id=TENANT,
        agent_id=AgentId.EDITOR_QC,
        step=ProductionState.ASSEMBLING,
        status=AgentRunStatus.SUCCEEDED,
        idempotency_key=jobs.render_run_key(PID),
        output=master.model_dump(mode="json"),
        output_model="MasterRender",
    )
    monkeypatch.setattr(jobs, "render_master_slate", lambda *a, **k: pytest.fail("re-render"))
    assert _call() == "asset_prev"
    assert rt.productions.get(PID, TENANT).master_render_asset_id == "asset_prev"
    assert len(rt.queue.jobs) == 1


@pytest.mark.integration
@pytest.mark.ffmpeg
def test_render_master_with_postgres_assets(require_ffmpeg: None, tmp_path: Path) -> None:
    if not db_available():
        pytest.skip("Postgres not reachable")
    pg = PgScratch()
    try:
        pid = pg.add_production()
        runtime = fake_runtime(
            Settings(
                persistence_backend="postgres",
                database_url=DATABASE_URL,
                queue_backend="inline",
                storage_local_root=tmp_path / "media",
            )
        )
        manifest = small_manifest(production_id=pid, tenant_id=pg.tenant_id)
        manifest.state = ProductionState.ASSEMBLING
        runtime.productions.create(manifest)
        set_runtime(runtime)
        asset_id = jobs.render_master(
            production_id=pid, tenant_id=pg.tenant_id, idempotency_key=f"{pid}:render"
        )
        stored = runtime.assets.get(asset_id, pg.tenant_id)
        assert stored is not None and stored.kind == AssetKind.RENDER
        assert stored.license is not None and stored.license.license_type == "rendered"
        assert runtime.assets.get(asset_id, DEMO_TENANT_ID) is None
        assert runtime.storage.exists(stored.storage_key)
    finally:
        set_runtime(None)
        pg.cleanup()


def test_missing_production(rt: Runtime) -> None:
    from cineforge.contracts.repositories import NotFoundError

    with pytest.raises(NotFoundError):
        jobs.render_master(production_id="prod_nope", tenant_id=TENANT, idempotency_key="k")
    with pytest.raises(NotFoundError):
        jobs.render_master(production_id=PID, tenant_id="tenant_other", idempotency_key="k")
