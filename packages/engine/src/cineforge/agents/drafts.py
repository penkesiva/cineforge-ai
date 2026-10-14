"""LLM-facing draft models (agent-internal, not contracts).

Drafts are deliberately small: the LLM contributes creative/analytic content, while
deterministic agent code owns ids, timing, budgets, rights and routing, and converts
each draft into the frozen contract artifact after validation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Draft(BaseModel):
    model_config = ConfigDict(extra="ignore")


# --------------------------------------------------------------------------- A2
class ClaimDraft(_Draft):
    text: str = Field(min_length=8, max_length=400, description="One self-contained fact")
    source_index: int | None = Field(
        default=None, ge=1, description="Number of the source that supports it (None if dramatized)"
    )
    excerpt: str = Field(
        default="",
        max_length=500,
        description="Verbatim sentence copied from that source's text that supports the claim",
    )
    status: Literal["verified", "disputed", "dramatized"] = "verified"
    confidence: float = Field(default=0.8, ge=0, le=1)


class ResearchDraft(_Draft):
    summary: str = Field(min_length=10, max_length=800)
    claims: list[ClaimDraft] = Field(min_length=1, max_length=10)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=5)


# --------------------------------------------------------------------------- A4
class TreatmentDraft(_Draft):
    logline: str = Field(min_length=10, max_length=240)
    narrative_style: str = Field(min_length=3, max_length=300)
    visual_language: list[str] = Field(min_length=2, max_length=10)
    director_notes: str = Field(default="", max_length=600)


# --------------------------------------------------------------------------- A5
class LineDraft(_Draft):
    scene_order: int = Field(ge=1)
    text: str = Field(min_length=3, max_length=400)
    claim_ids: list[str] = Field(default_factory=list, max_length=3)


class ScriptDraft(_Draft):
    hook: str = Field(min_length=5, max_length=240)
    lines: list[LineDraft] = Field(min_length=1, max_length=12)


# --------------------------------------------------------------------------- A6
class ShotDraft(_Draft):
    description: str = Field(min_length=5, max_length=240)
    shot_type: Literal["wide", "medium", "close_up", "extreme_close_up", "detail", "aerial"]
    camera_motion: str = Field(min_length=3, max_length=40)
    lighting: str | None = Field(default=None, max_length=60)
    atmosphere: str | None = Field(default=None, max_length=60)


class SceneDraft(_Draft):
    order: int = Field(ge=1)
    title: str = Field(min_length=2, max_length=80)
    shots: list[ShotDraft] = Field(min_length=1, max_length=4)


class StoryboardDraft(_Draft):
    scenes: list[SceneDraft] = Field(min_length=1, max_length=12)
