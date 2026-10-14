"""Composition root: builds every service from Settings via workstream-owned factories.

Factory functions (names are part of the frozen contract, see
docs/architecture/contracts.md):

- cineforge.persistence.factory.build_repositories(settings) -> Repositories   [B]
- cineforge.orchestration.factory.build_task_queue(settings) -> TaskQueue      [B]
- cineforge.agents.factory.build_agent_registry(settings) -> AgentRegistry     [B]
- cineforge.cost.factory.load_price_catalog(settings) -> PriceCatalog          [D]
- cineforge.cost.factory.build_budget_service(settings) -> BudgetService       [D]
- cineforge.cost.factory.build_cost_estimator(settings, catalog) -> CostEstimator [D]
- cineforge.media.factory.build_storage(settings) -> StorageBackend            [D]
- cineforge.media.factory.build_asset_repository(settings) -> AssetRepository  [D]
- cineforge.media.factory.build_rights_gate(settings) -> RightsGate            [D]
- cineforge.persistence.factory.build_theme_repository(settings) -> ThemeRepository [B]
- cineforge.providers.factory.build_secret_store(settings) -> SecretStore      [D]
- cineforge.providers.factory.build_provider_settings_repository(settings)
      -> ProviderSettingsRepository                                             [D]
- cineforge.providers.factory.build_provider_registry(
      settings, *, secrets, provider_settings) -> ProviderRegistry             [D]
- cineforge.providers.factory.build_paid_call_guard(settings, budget, catalog) -> PaidCallGuard [D]

Imports are lazy so each workstream can test its own pieces in isolation.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from functools import cached_property

from cineforge.config import Settings, get_settings
from cineforge.contracts.agents import AgentRegistry
from cineforge.contracts.cost import BudgetService, CostEstimator, PriceCatalog
from cineforge.contracts.jobs import TaskQueue
from cineforge.contracts.media import AssetRepository, RightsGate, StorageBackend
from cineforge.contracts.providers import (
    PaidCallGuard,
    ProviderRegistry,
    ProviderSettingsRepository,
    SecretStore,
)
from cineforge.contracts.repositories import (
    AgentRunRepository,
    ProductionRepository,
    ThemeRepository,
)


@dataclass(frozen=True)
class Repositories:
    productions: ProductionRepository
    agent_runs: AgentRunRepository


class Runtime:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @cached_property
    def repositories(self) -> Repositories:
        from cineforge.persistence.factory import build_repositories

        return build_repositories(self.settings)

    @property
    def productions(self) -> ProductionRepository:
        return self.repositories.productions

    @property
    def agent_runs(self) -> AgentRunRepository:
        return self.repositories.agent_runs

    @cached_property
    def queue(self) -> TaskQueue:
        from cineforge.orchestration.factory import build_task_queue

        return build_task_queue(self.settings)

    @cached_property
    def agents(self) -> AgentRegistry:
        from cineforge.agents.factory import build_agent_registry

        return build_agent_registry(self.settings)

    @cached_property
    def price_catalog(self) -> PriceCatalog:
        from cineforge.cost.factory import load_price_catalog

        return load_price_catalog(self.settings)

    @cached_property
    def budget(self) -> BudgetService:
        from cineforge.cost.factory import build_budget_service

        return build_budget_service(self.settings)

    @cached_property
    def cost_estimator(self) -> CostEstimator:
        from cineforge.cost.factory import build_cost_estimator

        return build_cost_estimator(self.settings, self.price_catalog)

    @cached_property
    def storage(self) -> StorageBackend:
        from cineforge.media.factory import build_storage

        return build_storage(self.settings)

    @cached_property
    def assets(self) -> AssetRepository:
        from cineforge.media.factory import build_asset_repository

        return build_asset_repository(self.settings)

    @cached_property
    def rights_gate(self) -> RightsGate:
        from cineforge.media.factory import build_rights_gate

        return build_rights_gate(self.settings)

    @cached_property
    def themes(self) -> ThemeRepository:
        from cineforge.persistence.factory import build_theme_repository

        return build_theme_repository(self.settings)

    @cached_property
    def secrets(self) -> SecretStore:
        from cineforge.providers.factory import build_secret_store

        return build_secret_store(self.settings)

    @cached_property
    def provider_settings(self) -> ProviderSettingsRepository:
        from cineforge.providers.factory import build_provider_settings_repository

        return build_provider_settings_repository(self.settings)

    @cached_property
    def providers(self) -> ProviderRegistry:
        from cineforge.providers.factory import build_provider_registry

        return build_provider_registry(
            self.settings, secrets=self.secrets, provider_settings=self.provider_settings
        )

    @cached_property
    def paid_calls(self) -> PaidCallGuard:
        from cineforge.providers.factory import build_paid_call_guard

        return build_paid_call_guard(self.settings, self.budget, self.price_catalog)


_lock = threading.Lock()
_runtime: Runtime | None = None


def get_runtime() -> Runtime:
    global _runtime
    with _lock:
        if _runtime is None:
            _runtime = Runtime(get_settings())
        return _runtime


def set_runtime(runtime: Runtime | None) -> None:
    """Test hook: install a runtime (e.g. memory backends + inline queue) or reset."""
    global _runtime
    with _lock:
        _runtime = runtime
