"""Cost monitoring contracts (PRD 3 section 9).

Hard rule: every paid provider call is preceded by an ATOMIC budget reservation.
Budget limits are enforced by deterministic code, never by an LLM decision.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field

from cineforge.contracts.common import (
    DEFAULT_CURRENCY,
    AgentId,
    ContractModel,
    Money,
    ProductionMode,
    money,
    new_id,
    utcnow,
)
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.providers import PriceUnit, ProviderCapability
from cineforge.contracts.theme import ProductionModePolicy


class PriceCatalogEntry(ContractModel):
    provider: str
    model: str
    capability: ProviderCapability
    unit: PriceUnit
    unit_price: Money
    currency: str = DEFAULT_CURRENCY
    credits_per_unit: Decimal | None = None
    version: str
    effective_from: date
    effective_to: date | None = None
    notes: str = ""


class CostLineItem(ContractModel):
    key: str = Field(description="Stable key, e.g. 'scene_01/shot_01/a7_visual_production'")
    scene_id: str | None = None
    shot_id: str | None = None
    agent_id: AgentId
    provider: str
    model: str
    capability: ProviderCapability
    unit: PriceUnit
    quantity: Decimal = Field(ge=0)
    unit_price: Money
    expected_attempts: Decimal = Field(default=Decimal(1), ge=1)
    estimated_cost: Money


class CostEstimate(ContractModel):
    production_id: str
    currency: str = DEFAULT_CURRENCY
    mode: ProductionMode
    price_catalog_version: str
    line_items: list[CostLineItem] = Field(default_factory=list)
    total_estimated: Money
    by_scene: dict[str, Money] = Field(default_factory=dict)
    by_agent: dict[str, Money] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class Budget(ContractModel):
    id: str = Field(default_factory=lambda: new_id("budget"))
    tenant_id: str
    production_id: str
    scene_id: str | None = Field(default=None, description="None = production-level budget")
    currency: str = DEFAULT_CURRENCY
    limit_amount: Money
    reserved_amount: Money = money(0)
    actual_amount: Money = money(0)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    @property
    def committed_and_reserved(self) -> Decimal:
        return self.reserved_amount + self.actual_amount

    @property
    def available(self) -> Decimal:
        return max(Decimal(0), self.limit_amount - self.committed_and_reserved)


class LedgerStatus(StrEnum):
    RESERVED = "reserved"
    COMMITTED = "committed"
    RELEASED = "released"
    FAILED = "failed"


class ReservationRequest(ContractModel):
    tenant_id: str
    production_id: str
    scene_id: str | None = None
    shot_id: str | None = None
    agent_id: AgentId
    provider: str
    model: str
    capability: ProviderCapability
    usage_units: Decimal = Field(ge=0)
    usage_unit: PriceUnit
    unit_price_version: str
    estimated_cost: Money
    attempt: int = Field(default=1, ge=1)
    retry_reason: str | None = None
    idempotency_key: str


class LedgerEvent(ContractModel):
    """One row of the cost ledger (PRD 3 section 9 'Ledger minimum')."""

    event_id: str = Field(default_factory=lambda: new_id("ledger"))
    tenant_id: str
    production_id: str
    scene_id: str | None = None
    shot_id: str | None = None
    agent_id: AgentId
    provider: str
    model: str
    capability: ProviderCapability
    provider_request_id: str | None = None
    usage_units: Decimal = Field(ge=0)
    usage_unit: PriceUnit
    unit_price_version: str
    estimated_cost: Money
    reserved_cost: Money
    actual_cost: Money = money(0)
    currency: str = DEFAULT_CURRENCY
    status: LedgerStatus = LedgerStatus.RESERVED
    attempt: int = Field(default=1, ge=1)
    retry_reason: str | None = None
    cache_hit: bool = False
    credits_used: Decimal | None = None
    idempotency_key: str
    timestamp: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class CreditBalance(ContractModel):
    tenant_id: str
    provider: str
    balance: Decimal
    unit: str = "credit"
    is_estimated: bool = True
    updated_at: datetime = Field(default_factory=utcnow)


class CostBreakdownRow(ContractModel):
    key: str
    label: str
    estimated: Money = money(0)
    reserved: Money = money(0)
    actual: Money = money(0)
    event_count: int = 0


class CostSummary(ContractModel):
    production_id: str
    currency: str = DEFAULT_CURRENCY
    limit: Money
    estimated: Money = money(0)
    reserved: Money = money(0)
    actual: Money = money(0)
    remaining: Money = money(0)
    by_scene: list[CostBreakdownRow] = Field(default_factory=list)
    by_agent: list[CostBreakdownRow] = Field(default_factory=list)
    by_provider: list[CostBreakdownRow] = Field(default_factory=list)
    retry_count: int = 0
    cache_hits: int = 0
    event_count: int = 0
    simulated: bool = Field(default=True, description="True while only mock providers are used")


class CostOverview(ContractModel):
    """Tenant-wide cost report across productions."""

    tenant_id: str
    currency: str = DEFAULT_CURRENCY
    production_count: int = 0
    total_limit: Money = money(0)
    total_estimated: Money = money(0)
    total_reserved: Money = money(0)
    total_actual: Money = money(0)
    by_production: list[CostBreakdownRow] = Field(default_factory=list)
    by_provider: list[CostBreakdownRow] = Field(default_factory=list)
    by_agent: list[CostBreakdownRow] = Field(default_factory=list)
    retry_count: int = 0
    credit_balances: list[CreditBalance] = Field(default_factory=list)
    simulated: bool = True


class BudgetExceededError(RuntimeError):
    def __init__(
        self,
        *,
        production_id: str,
        scene_id: str | None,
        requested: Decimal,
        available: Decimal,
    ) -> None:
        scope = f"scene {scene_id}" if scene_id else "production"
        super().__init__(
            f"Budget exceeded for {production_id} ({scope}): "
            f"requested {requested}, available {available}"
        )
        self.production_id = production_id
        self.scene_id = scene_id
        self.requested = requested
        self.available = available


class UnknownPriceError(LookupError):
    """No catalog price for provider/model/unit. Paid calls must not proceed."""


@runtime_checkable
class PriceCatalog(Protocol):
    version: str

    def get(self, provider: str, model: str, unit: PriceUnit) -> PriceCatalogEntry:
        """Raises UnknownPriceError if missing."""
        ...

    def entries(self) -> list[PriceCatalogEntry]: ...


@runtime_checkable
class BudgetService(Protocol):
    """Authoritative, concurrency-safe budget + ledger.

    Invariant per budget scope: reserved_amount + actual_amount <= limit_amount.
    ``reserve`` must be atomic across processes (Postgres: row lock) and idempotent
    on ``idempotency_key`` (a repeated key returns the existing event).
    """

    def create_budget(
        self,
        *,
        tenant_id: str,
        production_id: str,
        limit: Decimal,
        currency: str = DEFAULT_CURRENCY,
        scene_limits: dict[str, Decimal] | None = None,
    ) -> Budget: ...

    def get_budget(self, production_id: str, scene_id: str | None = None) -> Budget | None: ...

    def set_limit(self, production_id: str, limit: Decimal, scene_id: str | None = None) -> Budget:
        """Update a scope's hard cap, creating the scope (e.g. a scene budget) if missing.
        Never lowers a cap below reserved + actual."""
        ...

    def reserve(self, request: ReservationRequest) -> LedgerEvent:
        """Raises BudgetExceededError if production or scene budget would be exceeded."""
        ...

    def commit(
        self,
        event_id: str,
        *,
        actual_cost: Decimal,
        usage_units: Decimal | None = None,
        provider_request_id: str | None = None,
        cache_hit: bool = False,
        credits_used: Decimal | None = None,
    ) -> LedgerEvent: ...

    def release(
        self, event_id: str, *, reason: str, failed: bool = False, actual_cost: Decimal = Decimal(0)
    ) -> LedgerEvent:
        """Free the reservation. ``failed=True`` records a failed call (actual cost may be > 0)."""
        ...

    def ledger(self, production_id: str) -> list[LedgerEvent]: ...

    def summary(
        self, production_id: str, *, estimate: CostEstimate | None = None
    ) -> CostSummary: ...

    def overview(self, tenant_id: str) -> CostOverview: ...

    def credit_balances(self, tenant_id: str) -> list[CreditBalance]:
        """Estimated provider credit balances (decremented on commit by credits_used)."""
        ...


@runtime_checkable
class CostEstimator(Protocol):
    def estimate(
        self, manifest: ProductionManifest, mode_policy: ProductionModePolicy
    ) -> CostEstimate:
        """Preflight estimate per agent, scene and shot incl. expected retries."""
        ...
