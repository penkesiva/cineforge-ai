"""PaidCallGuard: the only sanctioned way to invoke a provider.

Order: paid-provider gate -> usage estimate -> catalog price (UnknownPriceError
stops the call) -> atomic budget reservation (BudgetExceededError stops the call)
-> invoke -> commit actual cost, or release the reservation on error.

When ``usage.breakdown`` is set (e.g. input vs output tokens) each line is priced
separately and summed, for both the estimate and the actual; the ledger row keeps the
aggregate ``units``/``unit``.

The ledger idempotency key is ``request.idempotency_key``; callers build it as
``"{agent_run_key}:{provider}:{model}"`` (one key per attempt). Replaying a key
whose event is already committed returns the recorded result without invoking.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from cineforge.config import Settings
from cineforge.contracts.common import AgentId, money
from cineforge.contracts.cost import (
    BudgetService,
    LedgerEvent,
    LedgerStatus,
    PriceCatalog,
    ReservationRequest,
    UnknownPriceError,
)
from cineforge.contracts.providers import (
    PaidProviderNotAllowedError,
    Provider,
    ProviderError,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
    UnsupportedCapabilityError,
)

log = logging.getLogger(__name__)


class DefaultPaidCallGuard:
    def __init__(self, settings: Settings, budget: BudgetService, catalog: PriceCatalog) -> None:
        self.settings = settings
        self.budget = budget
        self.catalog = catalog

    def call(
        self,
        provider: Provider,
        request: ProviderRequest,
        *,
        agent_id: AgentId,
        attempt: int = 1,
        retry_reason: str | None = None,
    ) -> tuple[ProviderResponse, LedgerEvent]:
        info = provider.info
        if info.is_paid and not self.settings.allow_paid_providers:
            raise PaidProviderNotAllowedError(
                f"provider {info.name!r} can incur real spend; set ALLOW_PAID_PROVIDERS=true "
                "after explicit human approval"
            )
        if request.capability not in info.capabilities:
            raise UnsupportedCapabilityError(f"{info.name} does not support {request.capability}")

        usage = provider.estimate_usage(request)
        version, estimated_cost = self._price(info.name, request.model, usage)
        event = self.budget.reserve(
            ReservationRequest(
                tenant_id=request.tenant_id,
                production_id=request.production_id,
                scene_id=request.scene_id,
                shot_id=request.shot_id,
                agent_id=agent_id,
                provider=info.name,
                model=request.model,
                capability=request.capability,
                usage_units=usage.units,
                usage_unit=usage.unit,
                unit_price_version=version,
                estimated_cost=estimated_cost,
                attempt=attempt,
                retry_reason=retry_reason,
                idempotency_key=request.idempotency_key,
            )
        )
        if event.status == LedgerStatus.COMMITTED:
            return _replayed_response(event), event
        if event.status in (LedgerStatus.RELEASED, LedgerStatus.FAILED):
            raise ProviderError(
                f"call {request.idempotency_key!r} already {event.status}; "
                "retry with a new attempt key",
                retryable=event.status == LedgerStatus.FAILED,
            )

        try:
            response = provider.invoke(request)
        except ProviderError as exc:
            self.budget.release(event.event_id, reason=str(exc), failed=True)
            raise
        except BaseException as exc:
            self.budget.release(event.event_id, reason=f"{type(exc).__name__}: {exc}")
            raise

        try:
            _, actual = self._price(info.name, request.model, response.usage)
        except UnknownPriceError:
            log.warning(
                "%s returned usage in unpriced unit(s) %s; committing the estimate",
                info.name,
                _units_label(response.usage),
            )
            actual = event.reserved_cost
        committed = self.budget.commit(
            event.event_id,
            actual_cost=actual,
            usage_units=response.usage.units,
            provider_request_id=response.provider_request_id,
            cache_hit=response.cached,
            credits_used=response.usage.credits,
        )
        return response, committed

    def _price(self, provider: str, model: str, usage: ProviderUsage) -> tuple[str, Decimal]:
        """(price version, cost). With a breakdown every line must be priced; the aggregate
        unit is then only recorded, never priced. Raises UnknownPriceError (fail closed)."""
        if not usage.breakdown:
            entry = self.catalog.get(provider, model, usage.unit)
            return entry.version, money(usage.units * entry.unit_price)
        total = Decimal(0)
        versions: list[str] = []
        for line in usage.breakdown:
            entry = self.catalog.get(provider, model, line.unit)
            total += line.units * entry.unit_price
            if entry.version not in versions:
                versions.append(entry.version)
        return "+".join(versions), money(total)


def _units_label(usage: ProviderUsage) -> str:
    if usage.breakdown:
        return ", ".join(line.unit.value for line in usage.breakdown)
    return usage.unit.value


def _replayed_response(event: LedgerEvent) -> ProviderResponse:
    return ProviderResponse(
        provider=event.provider,
        model=event.model,
        capability=event.capability,
        provider_request_id=event.provider_request_id or "",
        output_data={"replayed": True, "ledger_event_id": event.event_id},
        usage=ProviderUsage(
            units=event.usage_units, unit=event.usage_unit, credits=event.credits_used
        ),
        cached=True,
    )
