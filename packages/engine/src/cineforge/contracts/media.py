"""Media asset metadata, rights and storage abstraction (PRD 3 section 8).

Binaries live in object storage; Postgres holds metadata, provenance and licenses.
Rights checks fail closed: unknown or uncertain rights are never auto-approved.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, BinaryIO, Protocol, runtime_checkable

from pydantic import Field

from cineforge.contracts.common import ContractModel, Money, money, new_id, utcnow


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    RENDER = "render"
    REFERENCE = "reference"
    SUBTITLE = "subtitle"
    DOCUMENT = "document"


class AssetOrigin(StrEnum):
    LICENSED = "licensed"
    OPEN_LICENSE = "open_license"
    PUBLIC_DOMAIN = "public_domain"
    UPLOADED = "uploaded"
    GENERATED = "generated"
    RENDERED = "rendered"


class RightsStatus(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class LicenseInfo(ContractModel):
    license_type: str = Field(
        description="e.g. CC0, CC-BY-4.0, public-domain, commercial, customer-upload, "
        "generated, unknown"
    )
    license_url: str | None = None
    author: str | None = None
    attribution_text: str | None = None
    attribution_required: bool = False
    commercial_use_allowed: bool | None = None
    modifications_allowed: bool | None = None
    restrictions: list[str] = Field(default_factory=list)
    source_provider: str | None = None
    source_url: str | None = None
    retrieved_at: datetime | None = None


class RightsDecision(ContractModel):
    status: RightsStatus
    reasons: list[str] = Field(default_factory=list)
    decided_by: str = "rights_gate"
    policy_version: str = "v1"
    decided_at: datetime = Field(default_factory=utcnow)


class AssetRecord(ContractModel):
    id: str = Field(default_factory=lambda: new_id("asset"))
    tenant_id: str
    production_id: str | None = None
    kind: AssetKind
    origin: AssetOrigin
    storage_backend: str
    storage_key: str
    uri: str
    content_type: str
    size_bytes: int = Field(ge=0)
    sha256: str
    perceptual_hash: str | None = None
    width: int | None = None
    height: int | None = None
    duration_sec: float | None = None
    source_url: str | None = None
    source_provider: str | None = None
    license: LicenseInfo | None = None
    rights: RightsDecision
    generation: dict[str, Any] | None = Field(
        default=None, description="provider/model/prompt refs for generated assets"
    )
    usage_cost: Money = money(0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class StoredObject(ContractModel):
    backend: str
    key: str
    uri: str
    size_bytes: int
    sha256: str
    content_type: str


class StorageError(RuntimeError):
    pass


@runtime_checkable
class StorageBackend(Protocol):
    """S3-style object storage. Keys use forward slashes and never start with '/'."""

    name: str

    def put_bytes(self, key: str, data: bytes, content_type: str) -> StoredObject: ...

    def put_file(self, key: str, path: Path, content_type: str) -> StoredObject: ...

    def open(self, key: str) -> BinaryIO: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def local_path(self, key: str) -> Path | None:
        """Filesystem path if the backend is local, else None."""
        ...


@runtime_checkable
class RightsGate(Protocol):
    def evaluate(
        self, license: LicenseInfo | None, *, intended_use: str = "commercial"
    ) -> RightsDecision:
        """Must return BLOCKED/UNKNOWN (never APPROVED) when rights are uncertain."""
        ...


@runtime_checkable
class AssetRepository(Protocol):
    def add(self, record: AssetRecord) -> AssetRecord: ...

    def get(self, asset_id: str, tenant_id: str) -> AssetRecord | None:
        """Tenant-scoped: returns None for another tenant's asset."""
        ...

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AssetRecord]: ...


def storage_key(tenant_id: str, production_id: str | None, kind: AssetKind, filename: str) -> str:
    """Canonical object key layout shared by every storage backend."""
    scope = f"productions/{production_id}" if production_id else "library"
    return f"tenants/{tenant_id}/{scope}/{kind.value}/{filename}"
