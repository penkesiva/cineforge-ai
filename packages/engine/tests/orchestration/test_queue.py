"""TaskQueue implementations: inline (iterative), recording, and RQ (fakeredis)."""

from __future__ import annotations

import fakeredis
import pytest
from cineforge.config import Settings
from cineforge.contracts.jobs import TaskQueue
from cineforge.orchestration.factory import build_task_queue
from cineforge.orchestration.queue import (
    InlineTaskQueue,
    RecordingTaskQueue,
    RQTaskQueue,
    resolve_job,
    rq_job_id,
)

CALLS: list[tuple[str, int]] = []


def record_job(*, name: str, depth: int = 0) -> None:
    CALLS.append((name, depth))


def failing_job(**_: object) -> None:
    raise RuntimeError("boom")


@pytest.fixture(autouse=True)
def _clear_calls() -> None:
    CALLS.clear()


def test_inline_runs_nested_jobs_iteratively_not_recursively() -> None:
    queue = InlineTaskQueue()
    depth = {"current": 0, "max": 0}

    def nested(*, n: int) -> None:
        depth["current"] += 1
        depth["max"] = max(depth["max"], depth["current"])
        CALLS.append(("nested", n))
        if n < 50:
            queue.enqueue("q", "test.nested", {"n": n + 1}, job_id=f"job-{n + 1}")
        depth["current"] -= 1

    queue.overrides["test.nested"] = nested
    queue.enqueue("q", "test.nested", {"n": 1}, job_id="job-1")
    assert [n for _, n in CALLS] == list(range(1, 51))
    assert depth["max"] == 1
    assert len(queue.executed) == 50


def test_inline_resolves_dotted_paths_and_dedupes_pending_ids() -> None:
    queue = InlineTaskQueue()
    path = f"{__name__}.record_job"

    def outer() -> None:
        queue.enqueue("q", path, {"name": "a"}, job_id="same")
        queue.enqueue("q", path, {"name": "b"}, job_id="same")  # already pending
        queue.enqueue("q", path, {"name": "c"}, job_id="other")

    queue.overrides["test.outer"] = outer
    queue.enqueue("q", "test.outer", {}, job_id="outer")
    assert [name for name, _ in CALLS] == ["a", "c"]
    # A finished id may run again (the workflow itself is idempotent).
    queue.enqueue("q", path, {"name": "d"}, job_id="same")
    assert CALLS[-1] == ("d", 0)


def test_inline_records_failures_and_continues() -> None:
    queue = InlineTaskQueue()

    def outer() -> None:
        queue.enqueue("q", f"{__name__}.failing_job", {}, job_id="bad")
        queue.enqueue("q", f"{__name__}.record_job", {"name": "after"}, job_id="good")

    queue.overrides["test.outer"] = outer
    queue.enqueue("q", "test.outer", {})
    assert [j.job_id for j, _ in queue.failures] == ["bad"]
    assert CALLS == [("after", 0)]


def test_inline_raise_errors_and_max_jobs() -> None:
    strict = InlineTaskQueue(raise_errors=True)
    with pytest.raises(RuntimeError, match="boom"):
        strict.enqueue("q", f"{__name__}.failing_job", {})
    strict.enqueue("q", f"{__name__}.record_job", {"name": "ok"})  # queue still usable
    assert CALLS == [("ok", 0)]

    bounded = InlineTaskQueue(max_jobs=3, raise_errors=True)

    def forever(*, n: int) -> None:
        bounded.enqueue("q", "test.forever", {"n": n + 1}, job_id=f"f{n + 1}")

    bounded.overrides["test.forever"] = forever
    with pytest.raises(RuntimeError, match="max_jobs"):
        bounded.enqueue("q", "test.forever", {"n": 0}, job_id="f0")


def test_recording_queue_and_protocols() -> None:
    queue = RecordingTaskQueue()
    job_id = queue.enqueue("q", "a.b", {"x": 1}, job_id="j1")
    assert job_id == "j1"
    assert queue.jobs[0].kwargs == {"x": 1}
    assert queue.enqueue("q", "a.b", {}).startswith("job_")
    for q in (queue, InlineTaskQueue(), RQTaskQueue(fakeredis.FakeRedis())):
        assert isinstance(q, TaskQueue)


def test_resolve_job_errors() -> None:
    with pytest.raises(ValueError):
        resolve_job("nodots")
    assert resolve_job(f"{__name__}.record_job") is record_job


def test_rq_job_id_encoding() -> None:
    assert rq_job_id("plain_id-1") == "plain_id-1"
    encoded = rq_job_id("prod_x:GENERATING:1")
    assert encoded.startswith("prod_x-GENERATING-1-")
    assert rq_job_id("prod_x:GENERATING:1") == encoded
    assert rq_job_id("prod_x-GENERATING-1") != encoded


def test_rq_enqueue_by_path_dedupes_active_job_ids() -> None:
    from rq import Queue

    conn = fakeredis.FakeRedis()
    queue = RQTaskQueue(conn)
    path = f"{__name__}.record_job"
    first = queue.enqueue("cineforge-agents", path, {"name": "x"}, job_id="prod_1:RESEARCHING:1")
    second = queue.enqueue("cineforge-agents", path, {"name": "x"}, job_id="prod_1:RESEARCHING:1")
    assert first == second == "prod_1:RESEARCHING:1"
    rq_queue = Queue("cineforge-agents", connection=conn)
    assert rq_queue.count == 1
    job = rq_queue.jobs[0]
    assert job.func_name == path
    assert job.kwargs == {"name": "x"}
    assert job.meta["logical_job_id"] == "prod_1:RESEARCHING:1"


def test_rq_job_runs_with_simple_worker_and_can_be_requeued_after_finish() -> None:
    from rq import Queue, SimpleWorker

    conn = fakeredis.FakeRedis()
    queue = RQTaskQueue(conn)
    path = f"{__name__}.record_job"
    queue.enqueue("cineforge-agents", path, {"name": "run", "depth": 1}, job_id="a:B:1")
    SimpleWorker([Queue("cineforge-agents", connection=conn)], connection=conn).work(burst=True)
    assert CALLS == [("run", 1)]
    queue.enqueue("cineforge-agents", path, {"name": "again"}, job_id="a:B:1")
    assert Queue("cineforge-agents", connection=conn).count == 1


def test_factory_builds_backend_by_settings() -> None:
    assert isinstance(build_task_queue(Settings(queue_backend="inline")), InlineTaskQueue)
    rq_queue = build_task_queue(Settings(queue_backend="redis", redis_url="redis://localhost:1/0"))
    assert isinstance(rq_queue, RQTaskQueue)
