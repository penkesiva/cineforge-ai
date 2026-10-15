"""Video Production Manifest (PRD 3 section 7).

The manifest is the single structured hand-off between agents. It carries
references (asset IDs, URIs, prompt refs), never media blobs or huge prompts.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from cineforge.contracts.common import (
    DEFAULT_CURRENCY,
    SCHEMA_VERSION,
    ContractModel,
    GenerationStrategy,
    Money,
    ProductionMode,
    money,
    rename_legacy_key,
    utcnow,
)
from cineforge.contracts.providers import ProviderCapability
from cineforge.contracts.review import ReviewFinding, ReviewScore, ReviewStatus
from cineforge.contracts.workflow import ProductionState


class ThemeRef(ContractModel):
    id: str
    version: int = Field(ge=1)


class CreativeBrief(ContractModel):
    topic: str = Field(min_length=3, max_length=500)
    genre: str | None = None
    language: str = "en-US"
    audience: str | None = None
    notes: str | None = None


class OutputProfile(ContractModel):
    aspect_ratio: Literal["9:16", "1:1", "16:9"] = "9:16"
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps: int = Field(default=30, gt=0, le=120)
    codec: str = "h264"
    audio_codec: str = "aac"
    container: str = "mp4"
    bitrate_kbps: int | None = None
    duration_target_sec: float = Field(default=45, gt=0, le=600)


class BudgetSnapshot(ContractModel):
    """Denormalized view of the production budget; the cost ledger is authoritative."""

    currency: str = DEFAULT_CURRENCY
    limit: Money
    estimated: Money = money(0)
    reserved: Money = money(0)
    actual: Money = money(0)


class ApprovalPolicy(ContractModel):
    auto_approve: bool = False
    approved_by: str | None = None
    approved_at: datetime | None = None
    note: str | None = None


class WorkStatus(StrEnum):
    PLANNED = "planned"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    APPROVED = "approved"
    NEEDS_REPAIR = "needs_repair"
    FAILED = "failed"
    SKIPPED = "skipped"


class VisualSpec(ContractModel):
    shot_type: str = Field(description="e.g. wide, medium, close_up, extreme_close_up")
    camera_motion: str = Field(description="e.g. static, slow_push, dolly, pan, tilt, drone")
    lens: str | None = None
    lighting: str | None = None
    atmosphere: str | None = None
    color_grade: str | None = None
    vfx: list[str] = Field(default_factory=list)
    camera_path: dict[str, Any] | None = None
    camera_control_supported: bool = False


class PerformanceSpec(ContractModel):
    character_ref: str | None = None
    emotion: str | None = None
    gesture: str | None = None
    lip_sync_required: bool = False


class AudioSpec(ContractModel):
    dialogue_ref: str | None = None
    dialogue_text: str | None = Field(
        default=None, description="What the on-camera host says in this shot (A-roll)"
    )
    narration_text: str | None = None
    ambience: str | None = None
    music_cue: str | None = None
    sfx: list[str] = Field(default_factory=list)


class AssetRole(StrEnum):
    SOURCE = "source"
    REFERENCE = "reference"
    KEYFRAME = "keyframe"
    GENERATED = "generated"
    AUDIO = "audio"
    CAPTION = "caption"
    RENDER = "render"


class AssetRef(ContractModel):
    asset_id: str
    role: AssetRole
    uri: str | None = None
    transform: dict[str, Any] = Field(
        default_factory=dict, description="Per-asset transform, e.g. crop, ken_burns, grade"
    )


class ProviderPlan(ContractModel):
    strategy: GenerationStrategy = GenerationStrategy.HYBRID
    capability: ProviderCapability | None = None
    provider: str = "unassigned"
    model: str = "unassigned"
    prompt_template_id: str | None = None
    prompt_template_version: int | None = None
    prompt: str | None = Field(default=None, description="Compiled prompt (short)")
    prompt_ref: str | None = Field(default=None, description="Storage ref for long prompts")
    negative_prompt: str | None = None
    seed: int | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    draft_first: bool = False


class ProviderAttempt(ContractModel):
    attempt: int = Field(ge=1)
    provider: str
    model: str
    status: Literal["succeeded", "failed"]
    provider_request_id: str | None = None
    ledger_event_id: str | None = None
    cost: Money = money(0)
    error: str | None = None
    output_asset_id: str | None = None
    at: datetime = Field(default_factory=utcnow)


class Disclosure(ContractModel):
    synthetic_media: bool = False
    reconstruction: bool = False
    label_text: str | None = None


class ShotKind(StrEnum):
    STANDARD = "standard"
    A_ROLL = "a_roll"
    B_ROLL = "b_roll"


class ApprovalStage(StrEnum):
    """Gates of a fully generative production, cheapest first."""

    SCRIPT = "script"
    PREVIEW = "preview"
    PILOT = "pilot"
    FINAL = "final"


class Shot(ContractModel):
    id: str
    order: int = Field(ge=1)
    duration_sec: float = Field(gt=0)
    kind: ShotKind = ShotKind.STANDARD
    description: str = ""
    visual: VisualSpec
    performance: PerformanceSpec = Field(default_factory=PerformanceSpec)
    audio: AudioSpec = Field(default_factory=AudioSpec)
    assets: list[AssetRef] = Field(default_factory=list)
    provider_plan: ProviderPlan = Field(default_factory=ProviderPlan)
    attempts: list[ProviderAttempt] = Field(default_factory=list)
    review_scores: list[ReviewScore] = Field(default_factory=list)
    disclosure: Disclosure = Field(default_factory=Disclosure)
    depends_on: list[str] = Field(default_factory=list, description="Artifact IDs")
    estimated_cost: Money = money(0)
    actual_cost: Money = money(0)
    artifact_hash: str | None = None
    version: int = Field(default=1, ge=1)
    status: WorkStatus = WorkStatus.PLANNED


class Scene(ContractModel):
    id: str
    order: int = Field(ge=1)
    title: str = ""
    duration_sec: float = Field(gt=0)
    story_beat: str = ""
    narration: str | None = None
    facts: list[str] = Field(default_factory=list, description="FactClaim IDs used")
    shots: list[Shot] = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    budget_limit: Money | None = None
    estimated_cost: Money = money(0)
    actual_cost: Money = money(0)
    version: int = Field(default=1, ge=1)
    status: WorkStatus = WorkStatus.PLANNED

    @model_validator(mode="after")
    def _shots_fill_scene(self) -> Scene:
        total = sum(s.duration_sec for s in self.shots)
        if abs(total - self.duration_sec) > 0.05:
            raise ValueError(
                f"scene {self.id}: shot durations sum to {total}s, expected {self.duration_sec}s"
            )
        return self


class Caption(ContractModel):
    start_sec: float = Field(ge=0)
    end_sec: float = Field(gt=0)
    text: str


class CaptionTrack(ContractModel):
    language: str = "en-US"
    burn_in: bool = True
    cues: list[Caption] = Field(default_factory=list)


class Soundtrack(ContractModel):
    music_asset_id: str | None = None
    music_cue: str | None = None
    ambience: str | None = None
    loudness_target_lufs: float = -14.0


class AuditEntry(ContractModel):
    at: datetime = Field(default_factory=utcnow)
    actor: str = Field(description="agent id, 'system' or a user identifier")
    action: str
    details: dict[str, Any] = Field(default_factory=dict)


class ClaimReview(ContractModel):
    """Human decision on a research claim at the approval gate (ENG-04)."""

    claim_id: str = Field(pattern=r"^claim_")
    decision: Literal["approved", "rejected"]
    reviewed_by: str = "operator"
    reviewed_at: datetime = Field(default_factory=utcnow)
    note: str | None = None


class ProductionManifest(ContractModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION  # type: ignore[assignment]
    production_id: str
    tenant_id: str
    title: str | None = None
    theme_profile: ThemeRef
    mode: ProductionMode = ProductionMode.BALANCED
    state: ProductionState = ProductionState.DRAFT
    config_version: int = Field(default=1, ge=1)
    creative_brief: CreativeBrief
    output: OutputProfile = Field(default_factory=OutputProfile)
    budget: BudgetSnapshot
    approval: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    approval_stage: ApprovalStage | None = Field(
        default=None, description="Current gate of a fully generative production"
    )
    persona_id: str | None = None
    persona_version: int | None = Field(
        default=None, description="Persona version pinned at creation (like the theme)"
    )
    character_bible_ref: str | None = None
    style_bible_ref: str | None = None
    research_brief_ref: str | None = None
    scenes: list[Scene] = Field(default_factory=list)
    captions: list[CaptionTrack] = Field(default_factory=list)
    soundtrack: Soundtrack | None = None
    master_render_asset_id: str | None = None
    provenance_refs: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = ReviewStatus.PENDING
    review_findings: list[ReviewFinding] = Field(default_factory=list)
    claim_reviews: list[ClaimReview] = Field(
        default_factory=list, description="Latest decision per claim wins"
    )
    audit: list[AuditEntry] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @model_validator(mode="before")
    @classmethod
    def _legacy_keys(cls, data: Any) -> Any:
        return rename_legacy_key(data, "character_id", "persona_id")

    @model_validator(mode="after")
    def _validate_graph(self) -> ProductionManifest:
        scene_ids = [s.id for s in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("duplicate scene ids")
        orders = [s.order for s in self.scenes]
        if len(orders) != len(set(orders)):
            raise ValueError("duplicate scene order values")
        shot_ids = [sh.id for sh in self.iter_shots()]
        if len(shot_ids) != len(set(shot_ids)):
            raise ValueError("duplicate shot ids across production")
        known = set(scene_ids) | set(shot_ids)
        for node_id, deps in self._dependency_edges():
            missing = [d for d in deps if d not in known and not d.startswith(("asset_", "claim_"))]
            if missing:
                raise ValueError(f"{node_id} depends on unknown ids {missing}")
        return self

    def iter_shots(self) -> Iterator[Shot]:
        for scene in self.scenes:
            yield from scene.shots

    def total_duration_sec(self) -> float:
        return sum(s.duration_sec for s in self.scenes)

    def find_scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.scenes if s.id == scene_id), None)

    def find_shot(self, shot_id: str) -> Shot | None:
        return next((sh for sh in self.iter_shots() if sh.id == shot_id), None)

    def _dependency_edges(self) -> Iterator[tuple[str, list[str]]]:
        for scene in self.scenes:
            yield scene.id, scene.depends_on
            for shot in scene.shots:
                # A shot implicitly depends on its scene and its bound assets.
                yield shot.id, [*shot.depends_on]

    def dependents_of(self, artifact_id: str) -> set[str]:
        """Transitive set of scene/shot IDs invalidated when ``artifact_id`` changes.

        Used for targeted repair: only these artifacts are regenerated.
        """
        reverse: dict[str, set[str]] = {}
        for scene in self.scenes:
            for dep in scene.depends_on:
                reverse.setdefault(dep, set()).add(scene.id)
            for shot in scene.shots:
                reverse.setdefault(scene.id, set()).add(shot.id)
                for dep in shot.depends_on:
                    reverse.setdefault(dep, set()).add(shot.id)
                for ref in shot.assets:
                    reverse.setdefault(ref.asset_id, set()).add(shot.id)
        seen: set[str] = set()
        stack = [artifact_id]
        while stack:
            for child in reverse.get(stack.pop(), ()):
                if child not in seen:
                    seen.add(child)
                    stack.append(child)
        return seen
