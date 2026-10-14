"""FastAPI dependencies: runtime, tenant scoping, workflow engine."""

from __future__ import annotations

import re
from typing import Annotated

from cineforge.orchestration.workflow import WorkflowEngine
from cineforge.runtime import Runtime, get_runtime
from fastapi import Depends, Header, HTTPException, status

_TENANT_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def runtime_dep() -> Runtime:
    return get_runtime()


RuntimeDep = Annotated[Runtime, Depends(runtime_dep)]


def tenant_dep(
    rt: RuntimeDep,
    x_tenant_id: Annotated[
        str | None,
        Header(alias="X-Tenant-Id", description="Tenant scope (default DEFAULT_TENANT_ID)"),
    ] = None,
) -> str:
    tenant = (x_tenant_id or "").strip() or rt.settings.default_tenant_id
    if not _TENANT_RE.match(tenant):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="X-Tenant-Id must match ^[A-Za-z0-9_-]{1,64}$",
        )
    return tenant


TenantDep = Annotated[str, Depends(tenant_dep)]


def workflow_dep(rt: RuntimeDep) -> WorkflowEngine:
    return WorkflowEngine(rt)


WorkflowDep = Annotated[WorkflowEngine, Depends(workflow_dep)]
