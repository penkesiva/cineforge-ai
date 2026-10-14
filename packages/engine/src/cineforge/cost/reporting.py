"""Report assembly shared by the memory and Postgres budget services.

Aggregation semantics (identical for both backends):

- ``estimated``: sum of ``estimated_cost`` over all ledger events (overridden by a
  preflight ``CostEstimate`` when one is supplied).
- ``reserved``: sum of ``reserved_cost`` over events still in status ``reserved``.
- ``actual``: sum of ``actual_cost`` over all events (committed spend plus any
  cost recorded on failed calls). This is the ledger truth and may exceed the
  budget row's ``actual_amount`` when a commit overran its scope cap.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from decimal import Decimal

from cineforge.contracts.agents import agent_definition
from cineforge.contracts.common import AgentId, money
from cineforge.contracts.cost import (
    Budget,
    CostBreakdownRow,
    CostEstimate,
    CostSummary,
    LedgerEvent,
    LedgerStatus,
)

PRODUCTION_SCOPE = "production"


def scope_key(scene_id: str | None) -> str:
    return f"scene:{scene_id}" if scene_id else PRODUCTION_SCOPE


@dataclass
class Totals:
    estimated: Decimal = Decimal(0)
    reserved: Decimal = Decimal(0)
    actual: Decimal = Decimal(0)
    count: int = 0

    def add_event(self, event: LedgerEvent) -> None:
        self.estimated += event.estimated_cost
        if event.status == LedgerStatus.RESERVED:
            self.reserved += event.reserved_cost
        self.actual += event.actual_cost
        self.count += 1


def capped_actual(
    *, limit: Decimal, reserved: Decimal, actual: Decimal, amount: Decimal
) -> Decimal:
    """Portion of ``amount`` a scope can absorb without breaking reserved+actual <= limit.

    Overage policy: the ledger always records the full actual cost (real spend), but
    a budget scope's ``actual_amount`` is capped at its limit. The scope is then full,
    so every further reservation fails and the production pauses for approval.
    """
    headroom = limit - reserved - actual
    return max(Decimal(0), min(amount, headroom))


def overspend_reason(*, reserved: Decimal, actual: Decimal) -> str | None:
    """``status_reason`` for a commit whose actual cost exceeds its reservation."""
    if money(actual) <= money(reserved):
        return None
    return f"overspend: reserved {money(reserved)}, actual {money(actual)}"


def group_events(
    events: Iterable[LedgerEvent], key: Callable[[LedgerEvent], str]
) -> dict[str, Totals]:
    groups: dict[str, Totals] = {}
    for event in events:
        groups.setdefault(key(event), Totals()).add_event(event)
    return groups


def scene_group_key(scene_id: str | None) -> str:
    return scene_id or PRODUCTION_SCOPE


def scene_label(key: str) -> str:
    return "Production-level" if key == PRODUCTION_SCOPE else key


def agent_label(key: str) -> str:
    try:
        return agent_definition(AgentId(key)).name
    except (ValueError, StopIteration):
        return key


def rows(groups: dict[str, Totals], label: Callable[[str], str]) -> list[CostBreakdownRow]:
    return [
        CostBreakdownRow(
            key=key,
            label=label(key),
            estimated=money(t.estimated),
            reserved=money(t.reserved),
            actual=money(t.actual),
            event_count=t.count,
        )
        for key, t in sorted(groups.items())
    ]


def _override_estimated(groups: dict[str, Totals], estimated: dict[str, Decimal]) -> None:
    for key in groups:
        groups[key].estimated = Decimal(0)
    for key, value in estimated.items():
        groups.setdefault(key, Totals()).estimated = value


def build_summary(
    *,
    production_id: str,
    budget: Budget | None,
    totals: Totals,
    by_scene: dict[str, Totals],
    by_agent: dict[str, Totals],
    by_provider: dict[str, Totals],
    retry_count: int,
    cache_hits: int,
    simulated: bool,
    estimate: CostEstimate | None = None,
) -> CostSummary:
    estimated = totals.estimated
    if estimate is not None:
        estimated = estimate.total_estimated
        _override_estimated(by_scene, {scene_group_key(k): v for k, v in estimate.by_scene.items()})
        _override_estimated(by_agent, dict(estimate.by_agent))
        per_provider: dict[str, Decimal] = {}
        for item in estimate.line_items:
            per_provider[item.provider] = per_provider.get(item.provider, Decimal(0)) + (
                item.estimated_cost
            )
        _override_estimated(by_provider, per_provider)
    limit = budget.limit_amount if budget else Decimal(0)
    return CostSummary(
        production_id=production_id,
        currency=budget.currency if budget else (estimate.currency if estimate else "USD"),
        limit=money(limit),
        estimated=money(estimated),
        reserved=money(totals.reserved),
        actual=money(totals.actual),
        remaining=money(max(Decimal(0), limit - totals.reserved - totals.actual)),
        by_scene=rows(by_scene, scene_label),
        by_agent=rows(by_agent, agent_label),
        by_provider=rows(by_provider, str),
        retry_count=retry_count,
        cache_hits=cache_hits,
        event_count=totals.count,
        simulated=simulated,
    )


def is_simulated_provider(provider: str) -> bool:
    """Mock providers are named ``mock-*``; any other ledger row is real (even if free),
    so ``CostSummary.simulated`` / ``CostOverview.simulated`` turn False."""
    return provider.startswith("mock-")
