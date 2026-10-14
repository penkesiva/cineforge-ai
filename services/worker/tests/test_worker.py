"""Agent worker: construction, CLI and running advance_production jobs from Redis (fakeredis)."""

from __future__ import annotations

import pytest
from cineforge.contracts.api import ApproveProductionRequest, CreateProductionRequest
from cineforge.contracts.jobs import QUEUE_AGENTS, QUEUE_MEDIA
from cineforge.contracts.workflow import ProductionState
from cineforge.orchestration.queue import RQTaskQueue, rq_job_id
from cineforge.orchestration.workflow import WorkflowEngine
from rq import Queue, SimpleWorker, Worker

TENANT = "tenant_worker_test"
TOPIC = "The lighthouse keepers of the Flannan Isles, December 1900"


def test_module_imports() -> None:
    import cineforge_worker
    import cineforge_worker.__main__ as entry

    assert cineforge_worker.__doc__
    assert callable(entry.main) and callable(entry.build_worker)


def test_build_worker_listens_on_agents_queue(fake_redis) -> None:
    from cineforge_worker.__main__ import build_worker

    worker = build_worker(fake_redis, name="w-test")
    assert isinstance(worker, Worker) and not isinstance(worker, SimpleWorker)
    assert worker.queue_names() == [QUEUE_AGENTS]
    assert worker.name == "w-test"
    simple = build_worker(fake_redis, queues=["a", "b"], simple=True)
    assert isinstance(simple, SimpleWorker)
    assert simple.queue_names() == ["a", "b"]


def _burst(conn) -> None:
    SimpleWorker([Queue(QUEUE_AGENTS, connection=conn)], connection=conn).work(burst=True)


def test_worker_runs_production_steps_from_redis(fake_redis) -> None:
    from fakes_b import fake_render_master, make_runtime

    rt, _ = make_runtime(queue=RQTaskQueue(fake_redis))
    wf = WorkflowEngine(rt)
    m = wf.create_production(CreateProductionRequest(topic=TOPIC), TENANT)
    started = wf.start(m.production_id, TENANT)
    assert started.job_id == f"{m.production_id}:RESEARCHING:1"
    agents_q = Queue(QUEUE_AGENTS, connection=fake_redis)
    assert agents_q.job_ids == [rq_job_id(started.job_id)]

    _burst(fake_redis)
    assert rt.productions.get(m.production_id, TENANT).state == ProductionState.AWAITING_APPROVAL
    assert agents_q.count == 0

    wf.approve(m.production_id, TENANT, ApproveProductionRequest())
    _burst(fake_redis)
    m = rt.productions.get(m.production_id, TENANT)
    assert m.state == ProductionState.ASSEMBLING

    media_q = Queue(QUEUE_MEDIA, connection=fake_redis)
    [render_job_id] = media_q.job_ids
    render_job = media_q.fetch_job(render_job_id)
    assert render_job.func_name == "cineforge.media.jobs.render_master"
    assert render_job.meta["logical_job_id"] == f"{m.production_id}:ASSEMBLING:render"

    fake_render_master(**render_job.kwargs)  # stands in for the media worker (Workstream D)
    _burst(fake_redis)
    m = rt.productions.get(m.production_id, TENANT)
    assert m.state == ProductionState.READY
    assert m.master_render_asset_id is not None


def test_unknown_production_is_a_noop_and_bad_job_lands_in_failed_registry(fake_redis) -> None:
    from fakes_b import make_runtime

    queue = RQTaskQueue(fake_redis)
    make_runtime(queue=queue)
    queue.enqueue(
        QUEUE_AGENTS,
        "cineforge.orchestration.jobs.advance_production",
        {"production_id": "prod_missing", "tenant_id": TENANT, "idempotency_key": "x:DRAFT:1"},
        job_id="prod_missing:RESEARCHING:1",
    )
    queue.enqueue(
        QUEUE_AGENTS,
        "cineforge.orchestration.jobs.advance_production",
        {"production_id": "prod_missing"},
        job_id="prod_missing:RESEARCHING:2",
    )
    _burst(fake_redis)
    agents_q = Queue(QUEUE_AGENTS, connection=fake_redis)
    assert agents_q.finished_job_registry.get_job_ids() == [rq_job_id("prod_missing:RESEARCHING:1")]
    assert agents_q.failed_job_registry.get_job_ids() == [rq_job_id("prod_missing:RESEARCHING:2")]


def test_main_burst_mode(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    import redis
    from cineforge.config import Settings
    from cineforge_worker.__main__ import main

    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url: fake_redis))
    settings = Settings(persistence_backend="memory", queue_backend="redis", log_level="WARNING")
    assert main(["--burst", "--simple", "--name", "w-main"], settings=settings) == 0
