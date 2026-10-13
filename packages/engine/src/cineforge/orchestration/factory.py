"""Composition-root factory for the task queue."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.jobs import TaskQueue


def build_task_queue(settings: Settings) -> TaskQueue:
    from cineforge.orchestration.queue import InlineTaskQueue, RQTaskQueue

    if settings.queue_backend == "inline":
        return InlineTaskQueue()
    return RQTaskQueue.from_url(settings.redis_url)
