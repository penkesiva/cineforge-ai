"""REST API request/response DTOs (FastAPI <-> dashboard).

Endpoint list: docs/architecture/contracts.md. TypeScript types are generated
from these models into packages/schemas (``make contracts``).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field

from cineforge.contracts.agents import (
    AgentRun,
    AssetSelection,
    CostPlan,
    CreativeTreatment,
    MasterRender,
    ProductionPlan,
    ResearchBrief,
    Script,
)
from cineforge.contracts.common import ContractModel, Money, ProductionMode
from cineforge.contracts.cost import CostSummary, LedgerEvent
from cineforge.contracts.discovery import InspirationReference
from cineforge.contracts.manifest import AuthoredScript, ProductionLook, ProductionManifest
from cineforge.contracts.media import AssetRecord, LicenseInfo, RightsStatus
from cineforge.contracts.persona import PersonaCanon, PersonaProfile
from cineforge.contracts.providers import ProviderCapability, ProviderCatalogEntry
from cineforge.contracts.review import ReviewReport
from cineforge.contracts.theme import ThemeProfile
from cineforge.contracts.workflow import ProductionEvent, ProductionState


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


class DependencyHealth(ContractModel):
    name: str
    status: HealthStatus
    detail: str = ""


class HealthResponse(ContractModel):
    status: HealthStatus
    service: str = "cineforge-api"
    version: str
    environment: str
    paid_providers_enabled: bool
    provider_mode: str = "mock"
    checks: list[DependencyHealth] = Field(default_factory=list)


class CreateProductionRequest(ContractModel):
    theme_id: str = "time-traveler"
    theme_version: int | None = Field(default=None, ge=1, description="Latest when omitted")
    topic: str = Field(min_length=3, max_length=500)
    title: str | None = None
    mode: ProductionMode = ProductionMode.BALANCED
    duration_target_sec: float = Field(default=45, gt=0, le=180)
    budget_limit_usd: Money | None = Field(
        default=None, description="Defaults to the mode policy's default budget"
    )
    language: str = "en-US"
    auto_approve: bool = False
    idempotency_key: str | None = None
    look: ProductionLook | None = Field(
        default=None, description="Fully generative themes: outfit, location, references"
    )
    script: AuthoredScript | None = Field(
        default=None, description="Fully generative themes: approved script used as-is"
    )
    reference: InspirationReference | None = Field(
        default=None,
        description="Optional YouTube inspiration. Identity only: no title or statistics.",
    )


class ApproveProductionRequest(ContractModel):
    approved_by: str = "operator"
    note: str | None = None
    raise_budget_to_usd: Money | None = Field(
        default=None, description="Optional new hard cap when resuming from PAUSED_BUDGET"
    )


class ProductionSummary(ContractModel):
    id: str
    tenant_id: str
    title: str | None
    topic: str
    theme_id: str
    theme_version: int
    mode: ProductionMode
    state: ProductionState
    progress_pct: int = Field(ge=0, le=100)
    approval_stage: str | None = None
    scene_count: int
    shot_count: int
    currency: str
    budget_limit: Money
    estimated_cost: Money
    actual_cost: Money
    created_at: datetime
    updated_at: datetime


class ProductionArtifacts(ContractModel):
    plan: ProductionPlan | None = None
    treatment: CreativeTreatment | None = None
    research: ResearchBrief | None = None
    media: AssetSelection | None = None
    script: Script | None = None
    cost_plan: CostPlan | None = None
    review: ReviewReport | None = None
    master: MasterRender | None = None


class ProductionDetail(ContractModel):
    summary: ProductionSummary
    manifest: ProductionManifest
    agent_runs: list[AgentRun]
    events: list[ProductionEvent]
    cost: CostSummary
    artifacts: ProductionArtifacts
    assets: list[AssetRecord] = Field(default_factory=list)


class ActionResponse(ContractModel):
    production_id: str
    state: ProductionState
    message: str
    job_id: str | None = None


class ErrorResponse(ContractModel):
    error: str
    detail: Any = None


# --------------------------------------------------------------------------- #
# Claim review at the approval gate (ENG-04)
# --------------------------------------------------------------------------- #
class ClaimDecision(ContractModel):
    claim_id: str = Field(pattern=r"^claim_")
    decision: Literal["approved", "rejected"]
    note: str | None = Field(default=None, max_length=1000)


class ReviewClaimsRequest(ContractModel):
    reviewed_by: str = "operator"
    decisions: list[ClaimDecision] = Field(min_length=1)


# --------------------------------------------------------------------------- #
# Sources page (provider catalog, settings, write-only keys)
# --------------------------------------------------------------------------- #
class CapabilityGroup(ContractModel):
    capability: ProviderCapability
    label: str
    providers: list[ProviderCatalogEntry] = Field(description="Best (routable) first")
    active_provider: str | None = Field(
        default=None, description="What routing would pick right now, if anything"
    )


class ProvidersOverview(ContractModel):
    provider_mode: Literal["mock", "live"]
    paid_providers_allowed: bool
    secrets_backend: str
    groups: list[CapabilityGroup]


class UpdateProviderRequest(ContractModel):
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)


class SetProviderKeyRequest(ContractModel):
    api_key: str = Field(
        min_length=8, max_length=500, json_schema_extra={"writeOnly": True}, repr=False
    )


class ProviderTestResult(ContractModel):
    provider: str
    ok: bool
    detail: str
    latency_ms: int = 0
    paid_call: bool = Field(default=False, description="True if the check itself costs money")


# --------------------------------------------------------------------------- #
# Theme registry (ENG-01)
# --------------------------------------------------------------------------- #
class CreateThemeVersionRequest(ContractModel):
    base_version: int = Field(ge=1, description="Must be the current latest version")
    profile: ThemeProfile = Field(description="id/version are overwritten by the server")


# --------------------------------------------------------------------------- #
# External generations (media made outside the engine, e.g. Higgsfield via MCP)
# --------------------------------------------------------------------------- #
class GenerationPackStill(ContractModel):
    candidate_id: str
    provider: str
    title: str
    image_url: str | None = Field(
        default=None, description="Full-resolution https URL a generator can import"
    )
    source_url: str
    license: LicenseInfo | None = None
    rights_status: RightsStatus


class GenerationPackShot(ContractModel):
    scene_id: str
    scene_order: int = Field(ge=1)
    shot_id: str
    shot_order: int = Field(ge=1)
    duration_sec: float = Field(gt=0)
    prompt: str
    camera_motion: str
    still: GenerationPackStill | None = Field(
        default=None, description="Rights-approved still to animate; None if there is none"
    )
    score: float = Field(default=0, ge=0, le=1, description="Still ranking score from A3")
    generated_asset_id: str | None = Field(
        default=None, description="Real generated clip already attached to the shot"
    )


class GenerationPackScene(ContractModel):
    scene_id: str
    order: int = Field(ge=1)
    duration_sec: float = Field(gt=0)
    narration: str | None = None
    narration_asset_id: str | None = Field(
        default=None, description="Real narration audio already attached to the scene"
    )


class GenerationPack(ContractModel):
    production_id: str
    state: ProductionState
    width: int
    height: int
    aspect_ratio: str = Field(description="e.g. '9:16'")
    scenes: list[GenerationPackScene]
    shots: list[GenerationPackShot]


class ExternalGenerationRequest(ContractModel):
    """Reserve budget before a human-approved generation runs outside the engine."""

    scene_id: str
    shot_id: str | None = Field(default=None, description="None for scene-level audio")
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    capability: ProviderCapability
    quoted_credits: Decimal = Field(gt=0, description="Provider quote for this one call")
    credit_cap: Decimal | None = Field(
        default=None,
        gt=0,
        description="Max credits this provider may use in this production, incl. this call",
    )
    attempt: int = Field(default=1, ge=1)
    requested_by: str = "operator"


class ExternalGenerationComplete(ContractModel):
    result_url: str = Field(description="https URL of the finished output on the provider CDN")
    provider_request_id: str = Field(min_length=1, max_length=200)
    credits_used: Decimal = Field(ge=0)
    prompt: str | None = Field(default=None, max_length=4000)
    source_candidate_id: str | None = Field(
        default=None, description="A3 candidate the output was derived from (start image)"
    )
    parameters: dict[str, Any] = Field(default_factory=dict)


class ExternalGenerationRelease(ContractModel):
    reason: str = Field(min_length=1, max_length=500)
    failed: bool = True
    credits_used: Decimal = Field(default=Decimal(0), ge=0)


class ExternalGenerationResponse(ContractModel):
    production_id: str
    ledger_event: LedgerEvent
    asset: AssetRecord | None = None


class RenderRequest(ContractModel):
    requested_by: str = "operator"
    reason: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Fully generative productions (host-led vlogs): staged gates and per-shot redo
# --------------------------------------------------------------------------- #
class RegenerateShotRequest(ContractModel):
    target: Literal["still", "voice", "clip"]
    note: str | None = Field(
        default=None, max_length=1000, description="What to change, added to the prompt"
    )
    dialogue_text: str | None = Field(
        default=None, max_length=600, description="New line for voice redo (A-roll only)"
    )
    requested_by: str = "operator"


class StageQuote(ContractModel):
    """Credits the next gate will spend, before the operator approves it."""

    stage: str
    items: int = Field(ge=0)
    credits: Decimal = Field(ge=0)
    usd: Money
    credits_used: Decimal = Field(ge=0, description="Provider credits used so far")
    credit_cap: Decimal | None = None


class OAuthStartResponse(ContractModel):
    provider: str
    authorize_url: str


class ConnectorStatus(ContractModel):
    provider: str
    connected: bool
    balance_credits: Decimal | None = None
    detail: str = ""


class PersonaReference(ContractModel):
    """A reference image entry and whether its file is present in storage."""

    id: str
    file: str
    angle: str
    description: str | None = None
    available: bool = False
    url: str | None = Field(default=None, description="API path to the image when available")


class PersonaSummary(ContractModel):
    id: str
    version: int
    name: str
    handle: str | None = None
    age: int
    tagline: str
    voice_name: str | None = None
    reference_count: int = 0
    references_available: int = 0
    cover_url: str | None = None


class PersonaDetail(ContractModel):
    summary: PersonaSummary
    profile: PersonaProfile
    canon: PersonaCanon
    references: list[PersonaReference] = Field(default_factory=list)
    versions: list[int] = Field(default_factory=list)
