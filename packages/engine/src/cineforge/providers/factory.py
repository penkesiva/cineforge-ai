"""Composition-root factories for providers (names fixed by the contract)."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.cost import BudgetService, PriceCatalog
from cineforge.contracts.providers import PaidCallGuard, ProviderRegistry
from cineforge.providers.guard import DefaultPaidCallGuard
from cineforge.providers.mock import build_mock_providers
from cineforge.providers.registry import InMemoryProviderRegistry


def build_provider_registry(settings: Settings) -> ProviderRegistry:
    if settings.provider_mode != "mock":
        raise ValueError(f"unsupported PROVIDER_MODE {settings.provider_mode!r} in Phase 0")
    return InMemoryProviderRegistry(build_mock_providers(failure_rate=settings.mock_failure_rate))


def build_paid_call_guard(
    settings: Settings, budget: BudgetService, catalog: PriceCatalog
) -> PaidCallGuard:
    return DefaultPaidCallGuard(settings, budget, catalog)
