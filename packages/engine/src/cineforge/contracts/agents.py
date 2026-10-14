"""Logical agent contracts (PRD 3 section 3).

Agents make creative/planning decisions and emit TYPED artifacts. Deterministic
services (budget, rights, state machine, rendering) enforce the rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from cineforge.contracts.common import AgentId, ContractModel, Money, ProductionMode, money, utcnow
from cineforge.contracts.cost import CostEstimate
from cineforge.contracts.manifest import (
    CreativeBrief,
    OutputProfile,
    ProductionManifest,
    Scene,
    Shot,
)
from cineforge.contracts.media import LicenseInfo, RightsStatus
from cineforge.contracts.providers import PaidCallGuard, ProviderCapability, ProviderRegistry
from cineforge.contracts.theme import ProductionModePolicy, ThemeProfile
from cineforge.contracts.workflow import ProductionState

S = ProductionState
C = ProviderCapability


# --------------------------------------------------------------------------- #
# Registry definitions
# --------------------------------------------------------------------------- #
class AgentDefinition(ContractModel):
    id: AgentId
    code: str = Field(pattern=r"^A(10|[1-9])$")
    name: str
    responsibility: str
    input_model: str = Field(description="Contract model name of the agent input")
    output_model: str = Field(description="Contract model name of the agent output")
    outputs: list[str]
    key_checks: list[str]
    workflow_states: list[ProductionState]
    capabilities: list[ProviderCapability]
    prompt_template_id: str
    prompt_template_version: int = Field(default=1, ge=1)


def _def(
    agent_id: AgentId,
    code: str,
    name: str,
    responsibility: str,
    input_model: str,
    output_model: str,
    outputs: list[str],
    key_checks: list[str],
    states: list[ProductionState],
    caps: list[ProviderCapability],
    version: int = 1,
) -> AgentDefinition:
    return AgentDefinition(
        id=agent_id,
        code=code,
        name=name,
        responsibility=responsibility,
        input_model=input_model,
        output_model=output_model,
        outputs=outputs,
        key_checks=key_checks,
        workflow_states=states,
        capabilities=caps,
        prompt_template_id=agent_id.value,
        prompt_template_version=version,
    )


AGENT_DEFINITIONS: tuple[AgentDefinition, ...] = (
    _def(AgentId.MASTER_ORCHESTRATOR, "A1", "Master Orchestrator",
         "Workflow, dependencies, task delegation, budgets and escalation.",
         "PlanningInput", "ProductionPlan", ["ProductionPlan", "TaskGraph"],
         ["state", "retries", "budget gates"], [S.RESEARCHING], [C.LLM_TEXT]),
    _def(AgentId.RESEARCH, "A2", "Research & Fact Agent",
         "Topics, source discovery, evidence and claim verification.",
         "ResearchInput", "ResearchBrief", ["ResearchBrief", "FactClaims"],
         ["claim citations", "ambiguity"], [S.RESEARCHING], [C.LLM_TEXT, C.WEB_RESEARCH], 2),
    _def(AgentId.MEDIA_DISCOVERY, "A3", "Media Discovery Agent",
         "Federated image/video search, rights checks, dedup and asset selection.",
         "MediaDiscoveryInput", "AssetSelection", ["AssetCandidates", "AssetSelections"],
         ["license", "authenticity", "quality"], [S.RESEARCHING], [C.MEDIA_SEARCH]),
    _def(AgentId.CREATIVE_DIRECTOR, "A4", "Creative Director",
         "Theme, genre, narrative style, visual language and creative brief.",
         "CreativeInput", "CreativeTreatment", ["CreativeTreatment", "StyleBible"],
         ["consistency", "novelty"], [S.RESEARCHING], [C.LLM_TEXT], 2),
    _def(AgentId.SCRIPTWRITER, "A5", "Scriptwriter & Reasoner",
         "Hook, story beats, screenplay, dialogue and pacing.",
         "ScriptInput", "Script", ["Script", "StoryBeats"],
         ["coherence", "fact use", "word budget"], [S.SCRIPTING], [C.LLM_TEXT], 2),
    _def(AgentId.SCENE_DIRECTOR, "A6", "Scene Director",
         "Scene decomposition, storyboards, shots, cinematography and prompt compilation.",
         "SceneDirectionInput", "SceneGraph", ["SceneGraph", "ShotSpecs"],
         ["continuity", "feasible shots"], [S.STORYBOARDING], [C.LLM_TEXT], 2),
    _def(AgentId.VISUAL_PRODUCTION, "A7", "Visual Production Agent",
         "Image/video provider routing, generation, reuse and shot repairs.",
         "ShotProductionInput", "RenderedShotRef", ["RenderedShotRefs"],
         ["cost", "artifacts", "temporal quality"], [S.GENERATING],
         [C.IMAGE_GENERATION, C.IMAGE_TO_VIDEO, C.VIDEO_GENERATION]),
    _def(AgentId.AUDIO_PERFORMANCE, "A8", "Audio & Performance Agent",
         "Voice, multilingual speech, music, Foley, lip-sync and gestures.",
         "AudioInput", "AudioPackage", ["AudioTracks", "Alignment", "PerformanceRefs"],
         ["timing", "consent", "sync"], [S.GENERATING],
         [C.VOICE_TTS, C.MUSIC_GENERATION, C.SFX_GENERATION, C.LIP_SYNC]),
    _def(AgentId.EDITOR_QC, "A9", "Editor & QC Agent",
         "Timeline assembly, compositing, grading and technical/creative review.",
         "ReviewInput", "ReviewReport", ["MasterRender", "ReviewReport"],
         ["export", "continuity", "safety"], [S.ASSEMBLING, S.REVIEWING], [C.LLM_TEXT]),
    _def(AgentId.COST_OPTIMIZER, "A10", "Cost & Optimization Agent",
         "Quotes, routing advice, budgets, caching and spend reports.",
         "CostPlanningInput", "CostPlan", ["CostPlan", "CostLedger", "Alerts"],
         ["hard budget enforcement"], [S.STORYBOARDING], []),
)  # fmt: skip


def agent_definition(agent_id: AgentId) -> AgentDefinition:
    return next(d for d in AGENT_DEFINITIONS if d.id == agent_id)


# --------------------------------------------------------------------------- #
# Typed artifacts (agent outputs)
# --------------------------------------------------------------------------- #
class PlannedStep(ContractModel):
    state: ProductionState
    agent_ids: list[AgentId]
    parallel: bool = False


class ProductionPlan(ContractModel):
    production_id: str
    mode: ProductionMode
    steps: list[PlannedStep]
    scene_count_target: int = Field(ge=1)
    budget_envelope: Money
    notes: list[str] = Field(default_factory=list)


class SourceCitation(ContractModel):
    url: str
    title: str
    publisher: str | None = None
    published_at: date | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)
    excerpt: str | None = Field(
        default=None, description="Source text supporting the claim (provenance check)"
    )


class ClaimStatus(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    DISPUTED = "disputed"
    DRAMATIZED = "dramatized"


class FactClaim(ContractModel):
    id: str = Field(pattern=r"^claim_")
    text: str
    status: ClaimStatus
    sources: list[SourceCitation] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    notes: str = ""


class ResearchBrief(ContractModel):
    topic: str
    summary: str
    claims: list[FactClaim]
    unresolved_questions: list[str] = Field(default_factory=list)


class AssetCandidate(ContractModel):
    candidate_id: str
    provider: str
    media_type: Literal["image", "video", "audio"]
    title: str
    source_url: str
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    license: LicenseInfo | None = None
    rights_status: RightsStatus = RightsStatus.UNKNOWN
    score: float = Field(default=0, ge=0, le=1)


class AssetSelection(ContractModel):
    candidates: list[AssetCandidate]
    selected_ids: list[str] = Field(default_factory=list)
    blocked: dict[str, str] = Field(
        default_factory=dict, description="candidate_id -> reason it was blocked"
    )


class CreativeTreatment(ContractModel):
    theme_id: str
    theme_version: int
    logline: str
    genre: str
    tone: str
    narrative_style: str
    visual_language: list[str]
    style_bible: dict[str, Any] = Field(default_factory=dict)


class StoryBeat(ContractModel):
    order: int = Field(ge=1)
    beat: str
    purpose: str


class ScriptLine(ContractModel):
    scene_order: int = Field(ge=1)
    speaker: str = "narrator"
    text: str
    claim_ids: list[str] = Field(default_factory=list)
    dramatized: bool = False


class Script(ContractModel):
    hook: str
    logline: str
    beats: list[StoryBeat]
    lines: list[ScriptLine]
    cta: str | None = None
    word_count: int = Field(ge=0)
    estimated_duration_sec: float = Field(gt=0)


class SceneGraph(ContractModel):
    scenes: list[Scene] = Field(min_length=1)


class RenderedShotRef(ContractModel):
    scene_id: str
    shot_id: str
    asset_id: str | None = None
    provider: str
    model: str
    attempt: int = Field(default=1, ge=1)
    cost: Money = money(0)
    ledger_event_id: str | None = None


class AudioTrack(ContractModel):
    id: str
    kind: Literal["narration", "dialogue", "music", "sfx", "ambience"]
    scene_id: str | None = None
    asset_id: str | None = None
    duration_sec: float = Field(gt=0)
    provider: str
    model: str
    cost: Money = money(0)


class AlignmentRef(ContractModel):
    shot_id: str
    audio_track_id: str
    offset_ms: int = 0
    method: Literal["none", "forced_alignment", "lip_sync"] = "none"


class AudioPackage(ContractModel):
    tracks: list[AudioTrack]
    alignments: list[AlignmentRef] = Field(default_factory=list)


class MasterRender(ContractModel):
    asset_id: str
    uri: str
    duration_sec: float
    width: int
    height: int
    fps: float
    codec: str
    audio_codec: str | None = None
    size_bytes: int
    sha256: str
    probe: dict[str, Any] = Field(default_factory=dict)


class CostPlan(ContractModel):
    production_id: str
    estimate: CostEstimate
    within_budget: bool
    recommendations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Typed agent inputs
# --------------------------------------------------------------------------- #
class PlanningInput(ContractModel):
    production_id: str
    brief: CreativeBrief
    mode: ProductionMode
    budget_limit: Money
    duration_target_sec: float


class ResearchInput(ContractModel):
    brief: CreativeBrief
    theme_id: str
    factual_rigor: Literal["strict", "moderate", "creative"]
    max_claims: int = Field(default=8, ge=1)


class MediaDiscoveryInput(ContractModel):
    brief: CreativeBrief
    claims: list[FactClaim]
    max_candidates: int = Field(default=12, ge=1)
    intended_use: str = "commercial"


class CreativeInput(ContractModel):
    brief: CreativeBrief
    theme: ThemeProfile


class ScriptInput(ContractModel):
    brief: CreativeBrief
    treatment: CreativeTreatment
    research: ResearchBrief
    assets: AssetSelection
    scene_count: int = Field(ge=1)
    duration_target_sec: float = Field(gt=0)
    excluded_claim_ids: list[str] = Field(
        default_factory=list, description="Claims a reviewer rejected; never cite them"
    )


class SceneDirectionInput(ContractModel):
    script: Script
    treatment: CreativeTreatment
    assets: AssetSelection
    output: OutputProfile
    mode_policy: ProductionModePolicy
    max_shots_per_scene: int = Field(ge=1)


class ShotProductionInput(ContractModel):
    scene_id: str
    shot: Shot
    attempt: int = Field(default=1, ge=1)
    retry_reason: str | None = None


class AudioInput(ContractModel):
    """The orchestrator calls A8 once per scene (narration/lip-sync) and once for the
    music bed, so a failed line retries alone instead of rerunning all audio."""

    scenes: list[Scene]
    script: Script
    language: str = "en-US"
    include_narration: bool = True
    include_music: bool = True


class ReviewInput(ContractModel):
    manifest: ProductionManifest
    research: ResearchBrief | None = None
    master: MasterRender | None = None


class CostPlanningInput(ContractModel):
    """The estimate is computed deterministically by ``CostEstimator`` before A10 runs;
    A10 adds routing advice and the within-budget decision."""

    manifest: ProductionManifest
    mode_policy: ProductionModePolicy
    estimate: CostEstimate


# --------------------------------------------------------------------------- #
# Runtime interfaces
# --------------------------------------------------------------------------- #
class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class AgentRun(ContractModel):
    """Persisted record of one agent invocation (shown on the dashboard)."""

    id: str
    production_id: str
    tenant_id: str
    agent_id: AgentId
    step: ProductionState
    status: AgentRunStatus
    attempt: int = Field(default=1, ge=1)
    idempotency_key: str
    prompt_template_id: str | None = None
    prompt_template_version: int | None = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = Field(default=None, description="Typed artifact as JSON")
    output_model: str | None = None
    error: str | None = None
    estimated_cost: Money = money(0)
    actual_cost: Money = money(0)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None


@dataclass
class AgentContext:
    """Everything an agent may use. Agents never touch DB/queue/storage directly."""

    production_id: str
    tenant_id: str
    manifest: ProductionManifest
    theme: ThemeProfile
    mode_policy: ProductionModePolicy
    providers: ProviderRegistry
    paid_calls: PaidCallGuard
    idempotency_key: str
    attempt: int = 1
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class Agent(Protocol):
    definition: AgentDefinition
    input_model: type[BaseModel]
    output_model: type[BaseModel]

    def run(self, ctx: AgentContext, payload: BaseModel) -> BaseModel: ...


class AgentSchemaError(ValueError):
    """Agent input or output failed contract validation."""


@runtime_checkable
class AgentRegistry(Protocol):
    def register(self, agent: Agent) -> None: ...

    def get(self, agent_id: AgentId) -> Agent: ...

    def definitions(self) -> list[AgentDefinition]: ...

    def invoke(self, agent_id: AgentId, ctx: AgentContext, payload: BaseModel | dict) -> BaseModel:
        """Validate input against ``input_model``, run, validate output against
        ``output_model``. Raises AgentSchemaError on contract violations."""
        ...
