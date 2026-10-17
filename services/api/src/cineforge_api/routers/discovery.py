"""YouTube discovery runs. Sync, tenant scoped, and separate from media search."""

from __future__ import annotations

from cineforge.contracts.discovery import DiscoveryPageRequest, DiscoveryRun, StartDiscoveryRequest
from cineforge.discovery.service import DiscoveryRejected
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from cineforge_api.deps import RuntimeDep, TenantDep
from cineforge_api.errors import error_response

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])


@router.post("/runs", response_model=DiscoveryRun)
def start_run(
    body: StartDiscoveryRequest, rt: RuntimeDep, tenant_id: TenantDep
) -> DiscoveryRun | JSONResponse:
    try:
        filters = body.to_filters()
    except ValidationError as exc:
        return error_response(422, "validation_error", exc.errors())
    try:
        return rt.discovery.start(tenant_id, filters, body.idempotency_key)
    except DiscoveryRejected as exc:
        return error_response(exc.status, _name(exc.status), str(exc))


@router.get("/runs/{run_id}", response_model=DiscoveryRun)
def get_run(run_id: str, rt: RuntimeDep, tenant_id: TenantDep) -> DiscoveryRun | JSONResponse:
    try:
        return rt.discovery.get(tenant_id, run_id)
    except DiscoveryRejected as exc:
        return error_response(exc.status, _name(exc.status), str(exc))


@router.post("/runs/{run_id}/pages", response_model=DiscoveryRun)
def next_page(
    run_id: str, body: DiscoveryPageRequest, rt: RuntimeDep, tenant_id: TenantDep
) -> DiscoveryRun | JSONResponse:
    try:
        return rt.discovery.page(tenant_id, run_id, body.cursor)
    except DiscoveryRejected as exc:
        return error_response(exc.status, _name(exc.status), str(exc))


def _name(status: int) -> str:
    return {
        400: "bad_request",
        404: "not_found",
        409: "conflict",
        429: "quota_exceeded",
        502: "provider_error",
    }.get(status, "error")
