"""In-memory repositories (unit tests, ``PERSISTENCE_BACKEND=memory``).

Thread-safe; every read and write deep-copies so callers can never mutate stored state.
"""

from __future__ import annotations

import copy
import threading
from decimal import Decimal
from typing import Any

from cineforge.contracts.agents import AgentRun, AgentRunStatus
from cineforge.contracts.common import money, utcnow
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.repositories import NotFoundError
from cineforge.contracts.workflow import ProductionEvent, ProductionState, assert_transition


def _copy(model):
    return model.model_copy(deep=True)


class InMemoryProductionRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._items: dict[str, ProductionManifest] = {}
        self._by_key: dict[str, str] = {}
        self._events: dict[str, list[ProductionEvent]] = {}
        self._event_seq = 0

    def create(
        self, manifest: ProductionManifest, *, idempotency_key: str | None = None
    ) -> ProductionManifest:
        with self._lock:
            if idempotency_key is not None and idempotency_key in self._by_key:
                existing = self._items[self._by_key[idempotency_key]]
                if existing.tenant_id != manifest.tenant_id:
                    raise ValueError("idempotency key already used by another tenant")
                return _copy(existing)
            if manifest.production_id in self._items:
                raise ValueError(f"production {manifest.production_id} already exists")
            self._items[manifest.production_id] = _copy(manifest)
            self._events[manifest.production_id] = []
            if idempotency_key is not None:
                self._by_key[idempotency_key] = manifest.production_id
            return _copy(manifest)

    def _get_owned(self, production_id: str, tenant_id: str) -> ProductionManifest:
        item = self._items.get(production_id)
        if item is None or item.tenant_id != tenant_id:
            raise NotFoundError(f"production {production_id} not found")
        return item

    def get(self, production_id: str, tenant_id: str) -> ProductionManifest | None:
        with self._lock:
            item = self._items.get(production_id)
            if item is None or item.tenant_id != tenant_id:
                return None
            return _copy(item)

    def list(self, tenant_id: str, *, limit: int = 50) -> list[ProductionManifest]:
        with self._lock:
            owned = [m for m in self._items.values() if m.tenant_id == tenant_id]
            owned.sort(key=lambda m: m.created_at, reverse=True)
            return [_copy(m) for m in owned[:limit]]

    def save(self, manifest: ProductionManifest) -> ProductionManifest:
        with self._lock:
            stored = self._get_owned(manifest.production_id, manifest.tenant_id)
            # State only changes through transition(); keep the stored state.
            updated = manifest.model_copy(
                deep=True, update={"state": stored.state, "updated_at": utcnow()}
            )
            self._items[manifest.production_id] = updated
            return _copy(updated)

    def transition(
        self,
        production_id: str,
        tenant_id: str,
        to_state: ProductionState,
        *,
        reason: str,
        payload: dict[str, Any] | None = None,
    ) -> ProductionManifest:
        with self._lock:
            stored = self._get_owned(production_id, tenant_id)
            from_state = stored.state
            assert_transition(from_state, to_state)
            updated = stored.model_copy(
                deep=True, update={"state": to_state, "updated_at": utcnow()}
            )
            self._items[production_id] = updated
            self._append_event(
                ProductionEvent(
                    production_id=production_id,
                    tenant_id=tenant_id,
                    event_type="state_changed",
                    from_state=from_state,
                    to_state=to_state,
                    message=reason,
                    payload=dict(payload or {}),
                )
            )
            return _copy(updated)

    def _append_event(self, event: ProductionEvent) -> ProductionEvent:
        self._event_seq += 1
        stored = event.model_copy(deep=True, update={"id": self._event_seq})
        self._events.setdefault(event.production_id, []).append(stored)
        return _copy(stored)

    def add_event(self, event: ProductionEvent) -> ProductionEvent:
        with self._lock:
            self._get_owned(event.production_id, event.tenant_id)
            return self._append_event(event)

    def events(self, production_id: str, tenant_id: str) -> list[ProductionEvent]:
        with self._lock:
            return [
                _copy(e) for e in self._events.get(production_id, []) if e.tenant_id == tenant_id
            ]


class InMemoryAgentRunRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, AgentRun] = {}
        self._by_key: dict[str, str] = {}

    def start(self, run: AgentRun) -> AgentRun:
        with self._lock:
            existing_id = self._by_key.get(run.idempotency_key)
            if existing_id is not None:
                existing = self._runs[existing_id]
                if existing.status == AgentRunStatus.SUCCEEDED:
                    return _copy(existing)
                # Re-run of a failed/interrupted invocation: reuse the row.
                restarted = existing.model_copy(
                    deep=True,
                    update={
                        "status": AgentRunStatus.RUNNING,
                        "input_summary": dict(run.input_summary),
                        "output": None,
                        "output_model": None,
                        "error": None,
                        "estimated_cost": run.estimated_cost,
                        "actual_cost": money(0),
                        "started_at": utcnow(),
                        "finished_at": None,
                    },
                )
                self._runs[existing_id] = restarted
                return _copy(restarted)
            stored = run.model_copy(deep=True, update={"status": AgentRunStatus.RUNNING})
            self._runs[stored.id] = stored
            self._by_key[stored.idempotency_key] = stored.id
            return _copy(stored)

    def finish(
        self,
        run_id: str,
        *,
        status: AgentRunStatus,
        output: dict[str, Any] | None = None,
        output_model: str | None = None,
        error: str | None = None,
        actual_cost: Any = None,
    ) -> AgentRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                raise NotFoundError(f"agent run {run_id} not found")
            update: dict[str, Any] = {
                "status": status,
                "output": copy.deepcopy(output),
                "output_model": output_model,
                "error": error,
                "finished_at": utcnow(),
            }
            if actual_cost is not None:
                update["actual_cost"] = money(Decimal(str(actual_cost)))
            finished = run.model_copy(deep=True, update=update)
            self._runs[run_id] = finished
            return _copy(finished)

    def get_by_idempotency_key(self, idempotency_key: str) -> AgentRun | None:
        with self._lock:
            run_id = self._by_key.get(idempotency_key)
            return _copy(self._runs[run_id]) if run_id else None

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AgentRun]:
        with self._lock:
            runs = [
                r
                for r in self._runs.values()
                if r.production_id == production_id and r.tenant_id == tenant_id
            ]
            runs.sort(key=lambda r: r.started_at)
            return [_copy(r) for r in runs]
