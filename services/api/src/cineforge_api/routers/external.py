"""External generations (operator-run, e.g. Higgsfield via MCP) and master re-render."""

from __future__ import annotations

from typing import Annotated

from cineforge.contracts.api import (
    ActionResponse,
    ExternalGenerationComplete,
    ExternalGenerationRelease,
    ExternalGenerationRequest,
    ExternalGenerationResponse,
    GenerationPack,
    RenderRequest,
)
from cineforge.orchestration import external
from fastapi import APIRouter, Body, status

from cineforge_api.deps import RuntimeDep, TenantDep
from cineforge_api.routers.productions import _get_owned

router = APIRouter(prefix="/api/v1", tags=["external-generations"])


@router.get("/productions/{production_id}/generation-pack", response_model=GenerationPack)
def get_generation_pack(production_id: str, rt: RuntimeDep, tenant_id: TenantDep) -> GenerationPack:
    return external.generation_pack(rt, _get_owned(rt, production_id, tenant_id))


@router.post(
    "/productions/{production_id}/external-generations",
    response_model=ExternalGenerationResponse,
    status_code=status.HTTP_201_CREATED,
)
def reserve_external_generation(
    production_id: str, req: ExternalGenerationRequest, rt: RuntimeDep, tenant_id: TenantDep
) -> ExternalGenerationResponse:
    manifest = _get_owned(rt, production_id, tenant_id)
    event = external.reserve_external(rt, manifest, req)
    return ExternalGenerationResponse(production_id=production_id, ledger_event=event)


@router.post(
    "/productions/{production_id}/external-generations/{event_id}/complete",
    response_model=ExternalGenerationResponse,
)
def complete_external_generation(
    production_id: str,
    event_id: str,
    req: ExternalGenerationComplete,
    rt: RuntimeDep,
    tenant_id: TenantDep,
) -> ExternalGenerationResponse:
    manifest = _get_owned(rt, production_id, tenant_id)
    event, asset = external.complete_external(rt, manifest, event_id, req)
    return ExternalGenerationResponse(production_id=production_id, ledger_event=event, asset=asset)


@router.post(
    "/productions/{production_id}/external-generations/{event_id}/release",
    response_model=ExternalGenerationResponse,
)
def release_external_generation(
    production_id: str,
    event_id: str,
    req: ExternalGenerationRelease,
    rt: RuntimeDep,
    tenant_id: TenantDep,
) -> ExternalGenerationResponse:
    manifest = _get_owned(rt, production_id, tenant_id)
    event = external.release_external(rt, manifest, event_id, req)
    return ExternalGenerationResponse(production_id=production_id, ledger_event=event)


@router.post(
    "/productions/{production_id}/render",
    response_model=ActionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["productions"],
)
def rerender(
    production_id: str,
    rt: RuntimeDep,
    tenant_id: TenantDep,
    req: Annotated[RenderRequest | None, Body()] = None,
) -> ActionResponse:
    manifest = _get_owned(rt, production_id, tenant_id)
    job_id = external.request_rerender(rt, manifest, req or RenderRequest())
    fresh = rt.productions.get(production_id, tenant_id) or manifest
    return ActionResponse(
        production_id=production_id,
        state=fresh.state,
        message="Re-render queued; a new master version will appear when it finishes",
        job_id=job_id,
    )
