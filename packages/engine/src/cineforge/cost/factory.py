"""Composition-root factories for cost services (names fixed by the contract)."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.cost import BudgetService, CostEstimator, PriceCatalog
from cineforge.cost.catalog import YamlPriceCatalog
from cineforge.cost.estimator import DefaultCostEstimator


def load_price_catalog(settings: Settings) -> YamlPriceCatalog:
    """``PRICE_CATALOG_VERSION`` may list several versions (comma-separated); they merge."""
    versions = [v.strip() for v in settings.price_catalog_version.split(",") if v.strip()]
    return YamlPriceCatalog.load_many(settings.configurations_dir, versions)


def build_budget_service(settings: Settings) -> BudgetService:
    if settings.persistence_backend == "memory":
        from cineforge.cost.memory import InMemoryBudgetService

        return InMemoryBudgetService()
    from cineforge.cost.postgres import PostgresBudgetService

    return PostgresBudgetService(settings.database_url)


def build_cost_estimator(settings: Settings, catalog: PriceCatalog) -> CostEstimator:
    return DefaultCostEstimator(catalog)
