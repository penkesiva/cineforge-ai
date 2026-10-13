"""Persistence interfaces for productions and agent runs.

Two implementations per interface: in-memory (unit tests) and Postgres.
Cost/ledger persistence lives behind ``BudgetService``; assets behind
``AssetRepository``.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from cineforge.contracts.agents import AgentRun, AgentRunStatus
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.workflow import ProductionEvent, ProductionState


class NotFoundError(LookupError):
    pass


class ConcurrentUpdateError(RuntimeError):
    """Optimistic-lock conflict: the manifest changed since it was read."""


@runtime_checkable
class ProductionRepository(Protocol):
    def create(
        self, manifest: ProductionManifest, *, idempotency_key: str | None = None
    ) -> ProductionManifest:
        """Insert. If ``idempotency_key`` already exists, return that production."""
        ...

    def get(self, production_id: str, tenant_id: str) -> ProductionManifest | None: ...

    def list(self, tenant_id: str, *, limit: int = 50) -> list[ProductionManifest]: ...

    def save(self, manifest: ProductionManifest) -> ProductionManifest:
        """Persist manifest changes (not state changes). Bumps ``updated_at``."""
        ...

    def transition(
        self,
        production_id: str,
        tenant_id: str,
        to_state: ProductionState,
        *,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> ProductionManifest:
        """Validate via the state machine, update state, append a state_changed event.
        Raises InvalidStateTransitionError."""
        ...

    def add_event(self, event: ProductionEvent) -> ProductionEvent: ...

    def events(self, production_id: str, tenant_id: str) -> list[ProductionEvent]: ...


@runtime_checkable
class AgentRunRepository(Protocol):
    def start(self, run: AgentRun) -> AgentRun:
        """Insert a RUNNING run. If a SUCCEEDED run with the same idempotency_key exists,
        return it unchanged (caller then skips re-execution)."""
        ...

    def finish(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        output: dict[str, Any] | None = None,
        output_model: str | None = None,
        error: str | None = None,
        actual_cost: Any = None,
    ) -> AgentRun: ...

    def get_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None: ...

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AgentRun]: ...
