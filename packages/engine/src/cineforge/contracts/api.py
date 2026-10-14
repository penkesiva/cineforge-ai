"""REST API request/response DTOs (FastAPI <-> dashboard).

Endpoint list: docs/architecture/contracts.md. TypeScript types are generated
from these models into packages/schemas (``make contracts``).
"""

from __future__ import annotations

from datetime import datetime
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
from cineforge.contracts.cost import CostSummary
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.media import AssetRecord
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
