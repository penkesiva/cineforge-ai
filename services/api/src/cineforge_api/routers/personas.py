"""Personas: recurring AI hosts (profile, voice, canon) and their reference images."""

from __future__ import annotations

import mimetypes
from typing import Annotated

from cineforge.configuration import PersonaNotFoundError, load_personas
from cineforge.contracts.api import PersonaDetail, PersonaReference, PersonaSummary
from cineforge.contracts.media import StorageError, persona_storage_key
from cineforge.contracts.persona import PersonaProfile, ReferenceAngle
from cineforge.contracts.repositories import NotFoundError
from cineforge.media.persona_refs import reference_available
from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, StreamingResponse

from cineforge_api.deps import RuntimeDep, TenantDep, WorkflowDep
from cineforge_api.routers.assets import _iter_file

router = APIRouter(prefix="/api/v1", tags=["personas"])

COVER_ANGLES = (ReferenceAngle.FRONT, ReferenceAngle.CLOSE_UP)


def _versions(rt: RuntimeDep, persona_id: str) -> dict[int, PersonaProfile]:
    versions = load_personas(rt.settings.configurations_dir).get(persona_id)
    if not versions:
        raise NotFoundError(f"persona {persona_id} not found")
    return versions


def _ref_url(persona_id: str, ref_id: str) -> str:
    return f"/api/v1/personas/{persona_id}/references/{ref_id}"


def _references(rt: RuntimeDep, tenant_id: str, p: PersonaProfile) -> list[PersonaReference]:
    out = []
    for ref in p.references:
        ok = reference_available(rt.storage, tenant_id=tenant_id, persona=p, ref=ref)
        out.append(
            PersonaReference(
                id=ref.id,
                file=ref.file,
                angle=ref.angle.value,
                description=ref.description,
                available=ok,
                url=_ref_url(p.id, ref.id) if ok else None,
            )
        )
    return out


def _summary(p: PersonaProfile, refs: list[PersonaReference]) -> PersonaSummary:
    present = [r for r in refs if r.available]
    cover = next((r for a in COVER_ANGLES for r in present if r.angle == a.value), None)
    if cover is None and present:
        cover = present[0]
    return PersonaSummary(
        id=p.id,
        version=p.version,
        name=p.name,
        handle=p.handle,
        age=p.identity.age,
        tagline=p.personality.summary,
        voice_name=p.voice.voice_name,
        reference_count=len(refs),
        references_available=len(present),
        cover_url=cover.url if cover else None,
    )


@router.get("/personas", response_model=list[PersonaSummary])
def list_personas(rt: RuntimeDep, tenant_id: TenantDep) -> list[PersonaSummary]:
    out = []
    for versions in load_personas(rt.settings.configurations_dir).values():
        latest = versions[max(versions)]
        out.append(_summary(latest, _references(rt, tenant_id, latest)))
    return sorted(out, key=lambda s: s.name)


@router.get("/personas/{persona_id}", response_model=PersonaDetail)
def get_persona_detail(
    persona_id: str,
    rt: RuntimeDep,
    tenant_id: TenantDep,
    engine: WorkflowDep,
    version: Annotated[int | None, Query(ge=1, description="Default: latest")] = None,
) -> PersonaDetail:
    versions = _versions(rt, persona_id)
    profile = versions.get(version or max(versions))
    if profile is None:
        raise NotFoundError(f"persona {persona_id} v{version} not found")
    refs = _references(rt, tenant_id, profile)
    try:
        canon = engine.persona_canon(tenant_id, persona_id)
    except PersonaNotFoundError as exc:
        raise NotFoundError(str(exc)) from exc
    return PersonaDetail(
        summary=_summary(profile, refs),
        profile=profile,
        canon=canon,
        references=refs,
        versions=sorted(versions),
    )


@router.get(
    "/personas/{persona_id}/references/{ref_id}",
    response_class=StreamingResponse,
    response_model=None,
    responses={200: {"content": {"image/*": {}}}},
    summary="Reference image bytes (for review only; never used as footage)",
)
def persona_reference(
    persona_id: str, ref_id: str, rt: RuntimeDep, tenant_id: TenantDep
) -> StreamingResponse | FileResponse:
    ref = next(
        (r for p in _versions(rt, persona_id).values() for r in p.references if r.id == ref_id),
        None,
    )
    if ref is None:
        raise NotFoundError(f"reference {ref_id} not found")
    key = persona_storage_key(tenant_id, persona_id, ref.file)
    headers = {"Cache-Control": "private, max-age=3600"}
    try:
        path = rt.storage.local_path(key)
    except (StorageError, ValueError) as exc:
        raise NotFoundError(f"reference {ref_id} not in storage") from exc
    media_type = mimetypes.guess_type(ref.file)[0] or "application/octet-stream"
    if path is not None and path.is_file():
        return FileResponse(path, media_type=media_type, headers=headers)
    try:
        handle = rt.storage.open(key)
    except (StorageError, FileNotFoundError, KeyError, OSError) as exc:
        raise NotFoundError(f"reference {ref_id} not in storage") from exc
    return StreamingResponse(_iter_file(handle), media_type=media_type, headers=headers)
