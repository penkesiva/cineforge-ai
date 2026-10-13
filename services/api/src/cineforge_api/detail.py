"""Assembly of ProductionSummary / ProductionDetail from the engine's services."""

from __future__ import annotations

import logging

from cineforge.contracts.agents import (
    AgentRun,
    AgentRunStatus,
    AssetSelection,
    CostPlan,
    CreativeTreatment,
    MasterRender,
    ProductionPlan,
    ResearchBrief,
    Script,
)
from cineforge.contracts.api import ProductionArtifacts, ProductionDetail, ProductionSummary
from cineforge.contracts.cost import CostSummary
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.review import ReviewReport
from cineforge.contracts.workflow import progress_pct
from cineforge.persistence.serde import load
from cineforge.runtime import Runtime
from pydantic import BaseModel

log = logging.getLogger(__name__)

# output_model name -> (ProductionArtifacts field, model)
ARTIFACT_FIELDS: dict[str, tuple[str, type[BaseModel]]] = {
    "ProductionPlan": ("plan", ProductionPlan),
    "CreativeTreatment": ("treatment", CreativeTreatment),
    "ResearchBrief": ("research", ResearchBrief),
    "AssetSelection": ("media", AssetSelection),
    "Script": ("script", Script),
    "CostPlan": ("cost_plan", CostPlan),
    "ReviewReport": ("review", ReviewReport),
    "MasterRender": ("master", MasterRender),
}


def build_summary(m: ProductionManifest, cost: CostSummary | None = None) -> ProductionSummary:
    """Summary; costs come from the ledger summary when given, else the manifest snapshot."""
    return ProductionSummary(
        id=m.production_id,
        tenant_id=m.tenant_id,
        title=m.title,
        topic=m.creative_brief.topic,
        theme_id=m.theme_profile.id,
        theme_version=m.theme_profile.version,
        mode=m.mode,
        state=m.state,
        progress_pct=progress_pct(m.state),
        scene_count=len(m.scenes),
        shot_count=sum(len(s.shots) for s in m.scenes),
        currency=cost.currency if cost else m.budget.currency,
        budget_limit=cost.limit if cost else m.budget.limit,
        estimated_cost=(cost.estimated or m.budget.estimated) if cost else m.budget.estimated,
        actual_cost=cost.actual if cost else m.budget.actual,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def build_artifacts(runs: list[AgentRun]) -> ProductionArtifacts:
    found: dict[str, BaseModel] = {}
    for run in runs:  # ordered oldest -> newest; later runs win
        if run.status != AgentRunStatus.SUCCEEDED or not run.output or not run.output_model:
            continue
        target = ARTIFACT_FIELDS.get(run.output_model)
        if target is None:
            continue
        field, model = target
        try:
            found[field] = load(model, run.output)
        except ValueError:
            log.warning("agent run %s: unreadable %s artifact", run.id, run.output_model)
    return ProductionArtifacts(**found)


def cost_summary(rt: Runtime, m: ProductionManifest, artifacts: ProductionArtifacts) -> CostSummary:
    estimate = artifacts.cost_plan.estimate if artifacts.cost_plan else None
    try:
        return rt.budget.summary(m.production_id, estimate=estimate)
    except Exception:
        log.exception("cost summary unavailable for %s; using manifest snapshot", m.production_id)
        b = m.budget
        return CostSummary(
            production_id=m.production_id,
            currency=b.currency,
            limit=b.limit,
            estimated=b.estimated,
            reserved=b.reserved,
            actual=b.actual,
            remaining=max(b.limit - b.actual - b.reserved, 0),
        )


def build_detail(rt: Runtime, m: ProductionManifest) -> ProductionDetail:
    runs = rt.agent_runs.list_for_production(m.production_id, m.tenant_id)
    artifacts = build_artifacts(runs)
    cost = cost_summary(rt, m, artifacts)
    return ProductionDetail(
        summary=build_summary(m, cost),
        manifest=m,
        agent_runs=runs,
        events=rt.productions.events(m.production_id, m.tenant_id),
        cost=cost,
        artifacts=artifacts,
        assets=rt.assets.list_for_production(m.production_id, m.tenant_id),
    )
