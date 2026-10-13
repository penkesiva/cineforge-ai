"""The composition root builds every Workstream D service from Settings."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from cineforge.config import Settings
from cineforge.configuration import load_mode_policies
from cineforge.contracts.common import AgentId, ProductionMode
from cineforge.contracts.cost import BudgetService, CostEstimator, LedgerStatus, PriceCatalog
from cineforge.contracts.media import AssetRepository, RightsGate, StorageBackend
from cineforge.contracts.providers import (
    PaidCallGuard,
    ProviderCapability,
    ProviderRegistry,
    ProviderRequest,
)
from cineforge.runtime import Runtime
from cineforge.testing import sample_manifest


def test_runtime_builds_d_services(tmp_path: Path) -> None:
    rt = Runtime(
        Settings(
            persistence_backend="memory",
            queue_backend="inline",
            storage_local_root=tmp_path / "media",
        )
    )
    assert isinstance(rt.price_catalog, PriceCatalog)
    assert isinstance(rt.budget, BudgetService)
    assert isinstance(rt.cost_estimator, CostEstimator)
    assert isinstance(rt.storage, StorageBackend)
    assert isinstance(rt.assets, AssetRepository)
    assert isinstance(rt.rights_gate, RightsGate)
    assert isinstance(rt.providers, ProviderRegistry)
    assert isinstance(rt.paid_calls, PaidCallGuard)
    assert rt.paid_calls.budget is rt.budget

    manifest = sample_manifest()
    policy = load_mode_policies(rt.settings.configurations_dir)[ProductionMode.BALANCED]
    estimate = rt.cost_estimator.estimate(manifest, policy)
    rt.budget.create_budget(
        tenant_id=manifest.tenant_id,
        production_id=manifest.production_id,
        limit=manifest.budget.limit,
        scene_limits={sid: cost * 2 for sid, cost in estimate.by_scene.items()},
    )

    # What an agent does: route by capability, call through the guard.
    provider = rt.providers.for_capability(ProviderCapability.LLM_TEXT)
    run_key = f"{manifest.production_id}:SCRIPTING:{AgentId.SCRIPTWRITER.value}:script:1"
    response, event = rt.paid_calls.call(
        provider,
        ProviderRequest(
            tenant_id=manifest.tenant_id,
            production_id=manifest.production_id,
            capability=ProviderCapability.LLM_TEXT,
            model="mock-llm-standard",
            prompt="Write the hook for the Eiffel Tower short.",
            parameters={"max_tokens": 1200},
            idempotency_key=f"{run_key}:{provider.info.name}:mock-llm-standard",
        ),
        agent_id=AgentId.SCRIPTWRITER,
    )
    assert event.status == LedgerStatus.COMMITTED and event.actual_cost > 0
    summary = rt.budget.summary(manifest.production_id, estimate=estimate)
    assert summary.actual == event.actual_cost
    assert summary.estimated == estimate.total_estimated
    assert summary.remaining == manifest.budget.limit - event.actual_cost
    assert rt.budget.get_budget(manifest.production_id, "scene_01").limit_amount > Decimal(0)
    assert response.output_text
