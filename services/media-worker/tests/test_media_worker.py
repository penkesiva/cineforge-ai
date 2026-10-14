from __future__ import annotations

import shutil
from pathlib import Path

import fakeredis
import pytest
from cineforge.config import Settings
from cineforge.contracts.jobs import JOB_ADVANCE_PRODUCTION, JOB_RENDER_MASTER, QUEUE_MEDIA
from cineforge.contracts.workflow import ProductionState
from cineforge.runtime import set_runtime
from cineforge_media_worker import __main__ as worker_main
from fakes_d import fake_runtime, small_manifest
from rq import Queue, SimpleWorker
from rq.job import JobStatus

PID = "prod_worker_test_0001"
TENANT = "tenant_demo"


def test_imports_and_queue_name() -> None:
    worker = worker_main.build_worker(fakeredis.FakeStrictRedis(), name="test-media-worker")
    assert worker.queue_names() == [QUEUE_MEDIA]
    assert JOB_RENDER_MASTER == "cineforge.media.jobs.render_master"


def test_exits_with_clear_error_without_ffmpeg(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(worker_main.shutil, "which", lambda name: None)
    called = []
    monkeypatch.setattr(worker_main, "build_worker", lambda *a, **k: called.append(1))
    assert worker_main.main([]) == 2
    err = capsys.readouterr().err
    assert "ffmpeg" in err and "ffprobe" in err
    assert called == []


def test_redact_url() -> None:
    assert worker_main.redact_url("redis://:s3cret@redis:6379/0") == "redis://:***@redis:6379/0"
    assert worker_main.redact_url("redis://127.0.0.1:6379/0") == "redis://127.0.0.1:6379/0"


@pytest.mark.ffmpeg
def test_burst_worker_renders_master(tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        pytest.skip("ffmpeg/ffprobe not installed")
    rt = fake_runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
        )
    )
    manifest = small_manifest(production_id=PID)
    manifest.state = ProductionState.ASSEMBLING
    rt.productions.create(manifest)
    set_runtime(rt)
    try:
        conn = fakeredis.FakeStrictRedis()
        queue = Queue(QUEUE_MEDIA, connection=conn)
        # RQ 2.x job ids allow only [A-Za-z0-9_-]; the queue adapter maps ':' accordingly.
        job = queue.enqueue(
            JOB_RENDER_MASTER,
            kwargs={
                "production_id": PID,
                "tenant_id": TENANT,
                "idempotency_key": f"{PID}:ASSEMBLING:1",
            },
            job_id=f"{PID}-ASSEMBLING-1",
        )
        SimpleWorker([queue], connection=conn).work(burst=True)
        job.refresh()
        assert job.get_status() == JobStatus.FINISHED, job.latest_result()
        asset_id = job.return_value()
        assert rt.productions.get(PID, TENANT).master_render_asset_id == asset_id
        asset = rt.assets.get(asset_id, TENANT)
        assert asset is not None and rt.storage.exists(asset.storage_key)
        assert [j[1] for j in rt.queue.jobs] == [JOB_ADVANCE_PRODUCTION]
    finally:
        set_runtime(None)
