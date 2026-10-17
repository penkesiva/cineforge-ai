"""Sources page: provider catalog per capability, enable/priority, write-only keys, checks.

Keys are write-only: they are stored in the tenant's ``SecretStore`` and never echoed
(responses carry only ``key_source`` and a ``...abcd`` hint). Whether a provider can
actually run is still decided by the registry readiness rules and ``PaidCallGuard``.
"""

from __future__ import annotations

from cineforge.contracts.api import (
    CapabilityGroup,
    ProvidersOverview,
    ProviderTestResult,
    SetProviderKeyRequest,
    UpdateProviderRequest,
)
from cineforge.contracts.providers import (
    ProviderCapability,
    ProviderCatalogEntry,
    ProviderSetting,
    ProviderStatus,
    UnsupportedCapabilityError,
)
from cineforge.providers.checks import check_provider
from cineforge.runtime import Runtime
from fastapi import APIRouter, HTTPException, status

from cineforge_api.deps import RuntimeDep, TenantDep

router = APIRouter(prefix="/api/v1", tags=["providers"])

CAPABILITY_LABELS: dict[ProviderCapability, str] = {
    ProviderCapability.LLM_TEXT: "Reasoning (LLM)",
    ProviderCapability.WEB_RESEARCH: "Research / search",
    ProviderCapability.MEDIA_SEARCH: "Licensed media search",
    ProviderCapability.IMAGE_GENERATION: "Image generation",
    ProviderCapability.IMAGE_EDIT: "Image editing",
    ProviderCapability.VIDEO_GENERATION: "Video generation",
    ProviderCapability.IMAGE_TO_VIDEO: "Image to video",
    ProviderCapability.VOICE_TTS: "Voice / narration",
    ProviderCapability.MUSIC_GENERATION: "Music",
    ProviderCapability.SFX_GENERATION: "Sound effects",
    ProviderCapability.LIP_SYNC: "Lip sync",
    ProviderCapability.VIDEO_DISCOVERY: "Video discovery",
    ProviderCapability.TRANSCRIPTION: "Transcription",
    ProviderCapability.EMBEDDING: "Embeddings",
}


def _rank(entry: ProviderCatalogEntry) -> tuple[int, int, int, str]:
    order = {ProviderStatus.READY: 0, ProviderStatus.PLANNED: 2}
    return (order.get(entry.status, 1), entry.priority, int(entry.is_mock), entry.name)


def _entry(rt: Runtime, name: str, tenant_id: str) -> ProviderCatalogEntry:
    for entry in rt.providers.catalog(tenant_id):
        if entry.name == name:
            return entry
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"provider {name!r} not found")


def _routable(rt: Runtime, name: str, tenant_id: str) -> ProviderCatalogEntry:
    entry = _entry(rt, name, tenant_id)
    if entry.status == ProviderStatus.PLANNED:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"provider {name!r} is planned ({entry.planned_phase})"
        )
    return entry


@router.get("/providers", response_model=ProvidersOverview)
def providers_overview(rt: RuntimeDep, tenant_id: TenantDep) -> ProvidersOverview:
    catalog = rt.providers.catalog(tenant_id)
    groups: list[CapabilityGroup] = []
    for capability in ProviderCapability:
        entries = sorted((e for e in catalog if capability in e.capabilities), key=_rank)
        if not entries:
            continue
        try:
            active: str | None = rt.providers.route(capability, tenant_id=tenant_id).info.name
        except UnsupportedCapabilityError:
            active = None
        groups.append(
            CapabilityGroup(
                capability=capability,
                label=CAPABILITY_LABELS.get(capability, capability.value),
                providers=entries,
                active_provider=active,
            )
        )
    return ProvidersOverview(
        provider_mode=rt.settings.provider_mode,
        paid_providers_allowed=rt.settings.allow_paid_providers,
        secrets_backend=rt.secrets.name,
        groups=groups,
    )


@router.patch("/providers/{name}", response_model=ProviderCatalogEntry)
def update_provider(
    name: str, body: UpdateProviderRequest, rt: RuntimeDep, tenant_id: TenantDep
) -> ProviderCatalogEntry:
    current = _routable(rt, name, tenant_id)
    rt.provider_settings.upsert(
        ProviderSetting(
            tenant_id=tenant_id,
            provider=name,
            enabled=current.enabled if body.enabled is None else body.enabled,
            priority=current.priority if body.priority is None else body.priority,
        )
    )
    return _entry(rt, name, tenant_id)


@router.put("/providers/{name}/key", response_model=ProviderCatalogEntry)
def set_provider_key(
    name: str, body: SetProviderKeyRequest, rt: RuntimeDep, tenant_id: TenantDep
) -> ProviderCatalogEntry:
    entry = _routable(rt, name, tenant_id)
    if not entry.requires_key or entry.auth_method == "oauth":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"provider {name!r} does not use an API key"
        )
    rt.secrets.put(tenant_id, name, body.api_key.strip())
    return _entry(rt, name, tenant_id)


@router.delete("/providers/{name}/key", response_model=ProviderCatalogEntry)
def delete_provider_key(name: str, rt: RuntimeDep, tenant_id: TenantDep) -> ProviderCatalogEntry:
    _routable(rt, name, tenant_id)
    rt.secrets.delete(tenant_id, name)
    return _entry(rt, name, tenant_id)


@router.post("/providers/{name}/test", response_model=ProviderTestResult)
def test_provider(name: str, rt: RuntimeDep, tenant_id: TenantDep) -> ProviderTestResult:
    _entry(rt, name, tenant_id)
    return check_provider(rt.providers, name, tenant_id)
