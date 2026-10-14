"""Production workflow state machine (PRD 3 section 6)."""

from __future__ import annotations

import itertools
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from cineforge.contracts.common import ContractModel, utcnow


class ProductionState(StrEnum):
    # Happy path, in order.
    DRAFT = "DRAFT"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    STORYBOARDING = "STORYBOARDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    GENERATING = "GENERATING"
    ASSEMBLING = "ASSEMBLING"
    REVIEWING = "REVIEWING"
    READY = "READY"
    DELIVERED = "DELIVERED"
    # Exceptional states.
    PAUSED_BUDGET = "PAUSED_BUDGET"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


S = ProductionState

HAPPY_PATH: tuple[ProductionState, ...] = (
    S.DRAFT,
    S.RESEARCHING,
    S.SCRIPTING,
    S.STORYBOARDING,
    S.AWAITING_APPROVAL,
    S.GENERATING,
    S.ASSEMBLING,
    S.REVIEWING,
    S.READY,
    S.DELIVERED,
)
TERMINAL_STATES: frozenset[ProductionState] = frozenset({S.DELIVERED, S.FAILED, S.CANCELLED})
EXCEPTION_STATES: frozenset[ProductionState] = frozenset(
    {S.PAUSED_BUDGET, S.NEEDS_REVIEW, S.FAILED, S.CANCELLED}
)
# States in which the orchestrator actively executes agents.
WORKING_STATES: frozenset[ProductionState] = frozenset(
    {S.RESEARCHING, S.SCRIPTING, S.STORYBOARDING, S.GENERATING, S.ASSEMBLING, S.REVIEWING}
)


def _build_transitions() -> dict[ProductionState, frozenset[ProductionState]]:
    allowed: dict[ProductionState, set[ProductionState]] = {s: set() for s in ProductionState}
    for current, nxt in itertools.pairwise(HAPPY_PATH):
        allowed[current].add(nxt)
    for state in ProductionState:
        if state in TERMINAL_STATES:
            continue
        allowed[state] |= {S.FAILED, S.CANCELLED}
        if state not in {S.PAUSED_BUDGET, S.NEEDS_REVIEW}:
            allowed[state] |= {S.PAUSED_BUDGET, S.NEEDS_REVIEW}
    # Targeted repair: QC sends failed shots back to generation.
    allowed[S.REVIEWING].add(S.GENERATING)
    # Resume after budget approval.
    allowed[S.PAUSED_BUDGET] |= {S.AWAITING_APPROVAL, S.GENERATING, S.ASSEMBLING}
    # Resume after human review, back to any working/gate state.
    allowed[S.NEEDS_REVIEW] |= {
        S.RESEARCHING,
        S.SCRIPTING,
        S.STORYBOARDING,
        S.AWAITING_APPROVAL,
        S.GENERATING,
        S.ASSEMBLING,
        S.REVIEWING,
        S.READY,
    }
    return {k: frozenset(v) for k, v in allowed.items()}


ALLOWED_TRANSITIONS: dict[ProductionState, frozenset[ProductionState]] = _build_transitions()


class InvalidStateTransitionError(ValueError):
    def __init__(self, from_state: ProductionState, to_state: ProductionState) -> None:
        super().__init__(f"Invalid production state transition {from_state} -> {to_state}")
        self.from_state = from_state
        self.to_state = to_state


def can_transition(from_state: ProductionState, to_state: ProductionState) -> bool:
    return to_state in ALLOWED_TRANSITIONS[from_state]


def assert_transition(from_state: ProductionState, to_state: ProductionState) -> None:
    if not can_transition(from_state, to_state):
        raise InvalidStateTransitionError(from_state, to_state)


def progress_pct(state: ProductionState) -> int:
    """Happy-path progress for dashboards. Exception states report 0 (UI shows last step)."""
    if state in HAPPY_PATH:
        return round(100 * HAPPY_PATH.index(state) / (len(HAPPY_PATH) - 1))
    return 0


class ProductionEvent(ContractModel):
    """Immutable audit record of something that happened to a production."""

    id: int | None = None
    production_id: str
    tenant_id: str
    event_type: str = Field(description="e.g. state_changed, agent_started, budget_paused")
    from_state: ProductionState | None = None
    to_state: ProductionState | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)
