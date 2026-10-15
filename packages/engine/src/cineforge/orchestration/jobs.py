"""Job entrypoints (referenced by dotted path, see ``cineforge.contracts.jobs``)."""

from __future__ import annotations

from typing import Any

from cineforge.orchestration.workflow import WorkflowEngine
from cineforge.runtime import get_runtime


def advance_production(*, production_id: str, tenant_id: str, idempotency_key: str) -> None:
    """Run the current workflow step for a production and enqueue the next one."""
    WorkflowEngine(get_runtime()).advance(production_id, tenant_id, idempotency_key)


def regenerate_shot(
    *, production_id: str, tenant_id: str, shot_id: str, request: dict[str, Any]
) -> None:
    """Redo one shot's still, voice line or clip at a vlog gate."""
    WorkflowEngine(get_runtime()).run_regeneration(production_id, tenant_id, shot_id, request)
