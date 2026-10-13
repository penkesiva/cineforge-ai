"""Tenant-scoped asset content streaming."""

from __future__ import annotations

from collections.abc import Iterator
from typing import BinaryIO

from cineforge.contracts.media import StorageError
from cineforge.contracts.repositories import NotFoundError
from fastapi import APIRouter
from fastapi.responses import FileResponse, StreamingResponse

from cineforge_api.deps import RuntimeDep, TenantDep

router = APIRouter(prefix="/api/v1", tags=["assets"])

CHUNK_SIZE = 256 * 1024


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
