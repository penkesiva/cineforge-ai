"""REST API request/response DTOs (FastAPI <-> dashboard).

Endpoint list: docs/architecture/contracts.md. TypeScript types are generated
from these models into packages/schemas (``make contracts``).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

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
from cineforge.contracts.review import ReviewReport
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
    checks: list[DependencyHealth] = Field(default_factory=list)


class CreateProductionRequest(ContractModel):
    theme_id: str = "time-traveler"
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
