"""TaskQueue implementations: RQ (Redis), inline (synchronous) and recording (tests)."""

from __future__ import annotations

import hashlib
import importlib
import logging
import re
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cineforge.contracts.common import new_id

log = logging.getLogger(__name__)

JobFunc = Callable[..., Any]

_RQ_ID_INVALID = re.compile(r"[^A-Za-z0-9_-]")
# Statuses for which a job with the same id must not be enqueued again.
_ACTIVE_STATUSES = frozenset({"queued", "started", "deferred", "scheduled"})


def rq_job_id(job_id: str) -> str:
    """Map a logical job id (e.g. ``prod_x:GENERATING:1``) to an RQ-safe id.

    RQ only accepts ``[A-Za-z0-9_-]``. Invalid characters become ``-`` and a short
    hash of the original id is appended so distinct logical ids never collide.
    """
    safe = _RQ_ID_INVALID.sub("-", job_id)
    if safe == job_id:
        return job_id
    digest = hashlib.sha1(job_id.encode()).hexdigest()[:8]
    return f"{safe}-{digest}"


def resolve_job(job_path: str) -> JobFunc:
    module_name, _, attr = job_path.rpartition(".")
    if not module_name:
        raise ValueError(f"job path must be a dotted path, got {job_path!r}")
    func = getattr(importlib.import_module(module_name), attr)
    if not callable(func):
        raise TypeError(f"{job_path} is not callable")
    return func


@dataclass(frozen=True)
class EnqueuedJob:
    queue: str
    job_path: str
    kwargs: dict[str, Any]
    job_id: str


class RQTaskQueue:
    """Redis/RQ queue. Jobs are enqueued by dotted path so producers never import consumers."""

    def __init__(
        self,
        connection: Any,
        *,
        job_timeout: int = 1800,
        result_ttl: int = 3600,
        failure_ttl: int = 7 * 24 * 3600,
    ) -> None:
        self.connection = connection
        self.job_timeout = job_timeout
        self.result_ttl = result_ttl
        self.failure_ttl = failure_ttl

    @classmethod
    def from_url(cls, redis_url: str) -> RQTaskQueue:
        from redis import Redis

        return cls(Redis.from_url(redis_url))

    def enqueue(
        self,
        queue: str,
        job_path: str,
        kwargs: dict[str, Any],
        *,
        job_id: str | None = None,
    ) -> str:
        from rq import Queue
        from rq.exceptions import NoSuchJobError
        from rq.job import Job

        logical_id = job_id or new_id("job")
        rq_id = rq_job_id(logical_id)
        try:
            existing = Job.fetch(rq_id, connection=self.connection)
            status = existing.get_status(refresh=True)
            if status is not None and str(getattr(status, "value", status)) in _ACTIVE_STATUSES:
                log.info("job %s already %s; not enqueuing again", logical_id, status)
                return logical_id
        except NoSuchJobError:
            pass
        Queue(queue, connection=self.connection).enqueue(
            job_path,
            kwargs=kwargs,
            job_id=rq_id,
            job_timeout=self.job_timeout,
            result_ttl=self.result_ttl,
            failure_ttl=self.failure_ttl,
            description=f"{job_path} [{logical_id}]",
            meta={"logical_job_id": logical_id},
        )
        log.info("enqueued %s on %s as %s", job_path, queue, logical_id)
        return logical_id


class InlineTaskQueue:
    """Runs jobs synchronously in the calling thread (unit tests, ``QUEUE_BACKEND=inline``).

    Jobs run iteratively from a per-thread deque, so a job that enqueues another job
    does not recurse: the nested job runs after the current one returns. A job id that
    is already pending or running is not enqueued twice. ``overrides`` maps job paths to
    callables (e.g. a fake media job in tests).
    """

    def __init__(
        self,
        *,
        max_jobs: int = 1000,
        overrides: dict[str, JobFunc] | None = None,
        raise_errors: bool = False,
    ) -> None:
        self.max_jobs = max_jobs
        self.overrides: dict[str, JobFunc] = dict(overrides or {})
        self.raise_errors = raise_errors
        self.executed: list[EnqueuedJob] = []
        self.failures: list[tuple[EnqueuedJob, BaseException]] = []
        self._local = threading.local()
        self._record_lock = threading.Lock()

    def _state(self) -> threading.local:
        local = self._local
        if not hasattr(local, "pending"):
            local.pending = deque()
            local.running = None
        return local

    def enqueue(
        self,
        queue: str,
        job_path: str,
        kwargs: dict[str, Any],
        *,
        job_id: str | None = None,
    ) -> str:
        state = self._state()
        job = EnqueuedJob(queue, job_path, dict(kwargs), job_id or new_id("job"))
        if (state.running is not None and state.running.job_id == job.job_id) or any(
            p.job_id == job.job_id for p in state.pending
        ):
            log.info("inline job %s already pending/running; skipped", job.job_id)
            return job.job_id
        state.pending.append(job)
        if state.running is None:
            self._drain(state)
        return job.job_id

    def _drain(self, state: threading.local) -> None:
        count = 0
        try:
            while state.pending:
                count += 1
                if count > self.max_jobs:
                    raise RuntimeError(f"inline queue exceeded max_jobs={self.max_jobs}")
                job = state.pending.popleft()
                state.running = job
                try:
                    func = self.overrides.get(job.job_path) or resolve_job(job.job_path)
                    func(**job.kwargs)
                    with self._record_lock:
                        self.executed.append(job)
                except Exception as exc:
                    log.exception("inline job %s (%s) failed", job.job_id, job.job_path)
                    with self._record_lock:
                        self.failures.append((job, exc))
                    if self.raise_errors:
                        raise
                finally:
                    state.running = None
        except BaseException:
            state.pending.clear()
            raise


@dataclass
class RecordingTaskQueue:
    """Test helper: records enqueued jobs without running them."""

    jobs: list[EnqueuedJob] = field(default_factory=list)

    def enqueue(
        self,
        queue: str,
        job_path: str,
        kwargs: dict[str, Any],
        *,
        job_id: str | None = None,
    ) -> str:
        job = EnqueuedJob(queue, job_path, dict(kwargs), job_id or new_id("job"))
        self.jobs.append(job)
        return job.job_id

    def clear(self) -> None:
        self.jobs.clear()
