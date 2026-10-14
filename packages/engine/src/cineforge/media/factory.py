"""Composition-root factories for media services (names fixed by the contract)."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.media import AssetRepository, RightsGate, StorageBackend
from cineforge.media.rights import DefaultRightsGate
from cineforge.media.storage import LocalStorage, SupabaseStorage


def build_storage(settings: Settings) -> StorageBackend:
    if settings.storage_backend == "supabase":
        return SupabaseStorage(
            supabase_url=settings.supabase_url,
            service_role_key=settings.supabase_service_role_key,
            bucket=settings.supabase_storage_bucket,
        )
    return LocalStorage(settings.storage_local_root)


def build_asset_repository(settings: Settings) -> AssetRepository:
    if settings.persistence_backend == "memory":
        from cineforge.media.assets import InMemoryAssetRepository

        return InMemoryAssetRepository()
    from cineforge.media.assets import PostgresAssetRepository

    return PostgresAssetRepository(settings.database_url)


def build_rights_gate(settings: Settings) -> RightsGate:
    return DefaultRightsGate()
