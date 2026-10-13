"""Production lifecycle endpoints."""

from __future__ import annotations

from typing import Annotated

from cineforge.configuration import ThemeNotFoundError
from cineforge.contracts.api import (
    ActionResponse,
    ApproveProductionRequest,
    CreateProductionRequest,
    ProductionDetail,
    ProductionSummary,
)
from cineforge.contracts.cost import CostOverview, CostSummary, LedgerEvent
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.repositories import NotFoundError
from cineforge.orchestration.workflow import ActionResult
from cineforge.runtime import Runtime
from fastapi import APIRouter, Body, HTTPException, Query, status

from cineforge_api.deps import RuntimeDep, TenantDep, WorkflowDep
from cineforge_api.detail import build_artifacts, build_detail, build_summary, cost_summary

router = APIRouter(prefix="/api/v1")


def _get_owned(rt: Runtime, production_id: str, tenant_id: str) -> ProductionManifest:
    manifest = rt.productions.get(production_id, tenant_id)
    if manifest is None:
        raise NotFoundError(f"production {production_id} not found")
    return manifest


def _action(result: ActionResult) -> ActionResponse:
    return ActionResponse(
        production_id=result.manifest.production_id,
        state=result.manifest.state,
        message=result.message,
        job_id=result.job_id,
    )


@router.get("/productions", response_model=list[ProductionSummary], tags=["productions"])
def list_productions(
    rt: RuntimeDep,
    tenant_id: TenantDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ProductionSummary]:
    return [build_summary(m) for m in rt.productions.list(tenant_id, limit=limit)]


@router.post(
    "/productions",
    response_model=ProductionDetail,
    status_code=status.HTTP_201_CREATED,
    tags=["productions"],
)
def create_production(
    req: CreateProductionRequest, rt: RuntimeDep, tenant_id: TenantDep, wf: WorkflowDep
) -> ProductionDetail:
    try:
        manifest = wf.create_production(req, tenant_id)
    except ThemeNotFoundError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return build_detail(rt, manifest)


@router.get("/productions/{production_id}", response_model=ProductionDetail, tags=["productions"])
def get_production(production_id: str, rt: RuntimeDep, tenant_id: TenantDep) -> ProductionDetail:
    return build_detail(rt, _get_owned(rt, production_id, tenant_id))


@router.post(
    "/productions/{production_id}/run",
    response_model=ActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["productions"],
)
def run_production(production_id: str, tenant_id: TenantDep, wf: WorkflowDep) -> ActionResponse:
    return _action(wf.start(production_id, tenant_id))


@router.post(
    "/productions/{production_id}/approve",
    response_model=ActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["productions"],
)
def approve_production(
    production_id: str,
    tenant_id: TenantDep,
    wf: WorkflowDep,
    req: Annotated[ApproveProductionRequest | None, Body()] = None,
) -> ActionResponse:
    return _action(wf.approve(production_id, tenant_id, req or ApproveProductionRequest()))


@router.post(
    "/productions/{production_id}/cancel", response_model=ActionResponse, tags=["productions"]
)
def cancel_production(production_id: str, tenant_id: TenantDep, wf: WorkflowDep) -> ActionResponse:
    return _action(wf.cancel(production_id, tenant_id))


@router.post(
    "/productions/{production_id}/deliver", response_model=ActionResponse, tags=["productions"]
)
def deliver_production(production_id: str, tenant_id: TenantDep, wf: WorkflowDep) -> ActionResponse:
    return _action(wf.deliver(production_id, tenant_id))


@router.get("/productions/{production_id}/costs", response_model=CostSummary, tags=["costs"])
def production_costs(production_id: str, rt: RuntimeDep, tenant_id: TenantDep) -> CostSummary:
    manifest = _get_owned(rt, production_id, tenant_id)
    runs = rt.agent_runs.list_for_production(production_id, tenant_id)
    return cost_summary(rt, manifest, build_artifacts(runs))


@router.get("/productions/{production_id}/ledger", response_model=list[LedgerEvent], tags=["costs"])
def production_ledger(
    production_id: str, rt: RuntimeDep, tenant_id: TenantDep
) -> list[LedgerEvent]:
    _get_owned(rt, production_id, tenant_id)
    return [e for e in rt.budget.ledger(production_id) if e.tenant_id == tenant_id]


@router.get("/costs/overview", response_model=CostOverview, tags=["costs"])
def costs_overview(rt: RuntimeDep, tenant_id: TenantDep) -> CostOverview:
    return rt.budget.overview(tenant_id)
