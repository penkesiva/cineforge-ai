"""Background job contract.

Jobs are referenced by dotted import path so producers never import consumers.
All job functions take keyword arguments only and must be idempotent.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

QUEUE_AGENTS = "cineforge-agents"
QUEUE_MEDIA = "cineforge-media"

# advance_production(production_id: str, tenant_id: str, idempotency_key: str) -> None
#   Runs the next workflow step for a production, persists results, and enqueues
#   itself again until a gate (AWAITING_APPROVAL), a hand-off (ASSEMBLING ->
#   media worker) or a terminal/exception state is reached.
JOB_ADVANCE_PRODUCTION = "cineforge.orchestration.jobs.advance_production"

# render_master(production_id: str, tenant_id: str, idempotency_key: str) -> None
#   Media worker: deterministic FFmpeg render of the timeline (Phase 0: slate),
#   ffprobe validation, store via StorageBackend, register AssetRecord, set
#   manifest.master_render_asset_id, then enqueue JOB_ADVANCE_PRODUCTION.
JOB_RENDER_MASTER = "cineforge.media.jobs.render_master"


@runtime_checkable
class TaskQueue(Protocol):
    def enqueue(
        self,
        queue: str,
        job_path: str,
        kwargs: dict[str, Any],
        *,
        job_id: str | None = None,
    ) -> str:
        """Enqueue a job; returns the job id. Same ``job_id`` must not run twice."""
        ...
