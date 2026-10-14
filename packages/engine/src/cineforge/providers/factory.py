"""Composition-root factories for providers (names fixed by the contract)."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.cost import BudgetService, PriceCatalog
from cineforge.contracts.providers import (
    PaidCallGuard,
    ProviderRegistry,
    ProviderSettingsRepository,
    SecretStore,
)
from cineforge.providers.guard import DefaultPaidCallGuard
from cineforge.providers.mock import build_mock_providers
from cineforge.providers.registry import InMemoryProviderRegistry
from cineforge.providers.settings_store import (
    InMemoryProviderSettingsRepository,
    MemorySecretStore,
)


def build_secret_store(settings: Settings) -> SecretStore:
    return MemorySecretStore()


def build_provider_settings_repository(settings: Settings) -> ProviderSettingsRepository:
    return InMemoryProviderSettingsRepository()


def build_provider_registry(
    settings: Settings,
    *,
    secrets: SecretStore | None = None,
    provider_settings: ProviderSettingsRepository | None = None,
) -> ProviderRegistry:
    return InMemoryProviderRegistry(
        build_mock_providers(failure_rate=settings.mock_failure_rate),
        settings=settings,
        secrets=secrets,
        provider_settings=provider_settings,
    )


def build_paid_call_guard(
    settings: Settings, budget: BudgetService, catalog: PriceCatalog
) -> PaidCallGuard:
    return DefaultPaidCallGuard(settings, budget, catalog)
