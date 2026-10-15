"""Tenant-scoped asset content streaming."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from typing import Annotated, BinaryIO

from cineforge.contracts.common import new_id
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    LicenseInfo,
    StorageError,
    storage_key,
)
from cineforge.contracts.repositories import NotFoundError
from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, StreamingResponse

from cineforge_api.deps import RuntimeDep, TenantDep

router = APIRouter(prefix="/api/v1", tags=["assets"])

CHUNK_SIZE = 256 * 1024
MAX_REFERENCE_BYTES = 25 * 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _iter_file(handle: BinaryIO) -> Iterator[bytes]:
    try:
        while chunk := handle.read(CHUNK_SIZE):
            yield chunk
    finally:
        handle.close()


@router.get(
    "/assets/{asset_id}/content",
    response_class=StreamingResponse,
    response_model=None,
    responses={200: {"content": {"application/octet-stream": {}}}},
    summary="Stream asset bytes (tenant-scoped)",
)
def asset_content(
    asset_id: str, rt: RuntimeDep, tenant_id: TenantDep
) -> StreamingResponse | FileResponse:
    record = rt.assets.get(asset_id, tenant_id)
    if record is None:
        raise NotFoundError(f"asset {asset_id} not found")
    filename = record.storage_key.rsplit("/", 1)[-1]
    headers = {
        "Content-Disposition": f'inline; filename="{filename}"',
        "Cache-Control": "private, max-age=300",
    }
    try:
        path = rt.storage.local_path(record.storage_key)
    except (StorageError, ValueError) as exc:
        raise NotFoundError(f"asset {asset_id} content not found") from exc
    if path is not None and path.is_file():
        # FileResponse honours HTTP Range requests, so <video> can seek.
        return FileResponse(path, media_type=record.content_type, headers=headers)
    try:
        handle = rt.storage.open(record.storage_key)
    except (StorageError, FileNotFoundError, KeyError, OSError) as exc:
        raise NotFoundError(f"asset {asset_id} content not found") from exc
    return StreamingResponse(_iter_file(handle), media_type=record.content_type, headers=headers)


@router.post(
    "/assets/references",
    response_model=AssetRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a reference image (raw body); rights are evaluated, never shown on screen",
)
async def upload_reference(
    request: Request,
    rt: RuntimeDep,
    tenant_id: TenantDep,
    name: Annotated[str, Query(min_length=2, max_length=80, description="Short file stem")],
    author: Annotated[str, Query(min_length=2, max_length=200)],
    description: Annotated[str, Query(max_length=200)] = "",
    license_type: Annotated[str, Query(description="e.g. customer-upload, CC0, CC-BY-4.0")] = (
        "customer-upload"
    ),
    commercial_use: Annotated[
        bool, Query(description="Uploader attests commercial-use rights")
    ] = False,
    source_url: str | None = None,
    generator: Annotated[str | None, Query(description="AI tool, if AI-generated")] = None,
) -> AssetRecord:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    suffix = IMAGE_TYPES.get(content_type)
    if suffix is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "png, jpeg or webp only")
    data = await request.body()
    if not data or len(data) > MAX_REFERENCE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "empty or larger than 25 MB")
    stem = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "reference"
    asset_id = new_id("asset")
    key = storage_key(tenant_id, None, AssetKind.REFERENCE, f"{stem}-{asset_id[-8:]}{suffix}")
    stored = rt.storage.put_bytes(key, data, content_type)
    lic = LicenseInfo(
        license_type=license_type,
        author=author,
        attribution_text=author if license_type.lower().startswith("cc-by") else None,
        commercial_use_allowed=True if commercial_use else None,
        modifications_allowed=True,
        source_provider="upload",
        source_url=source_url,
    )
    record = AssetRecord(
        id=asset_id,
        tenant_id=tenant_id,
        kind=AssetKind.REFERENCE,
        origin=AssetOrigin.UPLOADED,
        storage_backend=stored.backend,
        storage_key=stored.key,
        uri=stored.uri,
        content_type=content_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        source_url=source_url,
        source_provider="upload",
        license=lic,
        rights=rt.rights_gate.evaluate(lic),
        metadata={
            "usage": "reference_only",
            "description": description,
            "ai_generated": generator is not None,
            "generator": generator,
        },
    )
    return rt.assets.add(record)
