"""PaidCallGuard: the only sanctioned way to invoke a provider.

Order: paid-provider gate -> usage estimate -> catalog price (UnknownPriceError
stops the call) -> atomic budget reservation (BudgetExceededError stops the call)
-> invoke -> commit actual cost, or release the reservation on error.

The ledger idempotency key is ``request.idempotency_key``; callers build it as
``"{agent_run_key}:{provider}:{model}"`` (one key per attempt). Replaying a key
whose event is already committed returns the recorded result without invoking.
"""

from __future__ import annotations

import logging

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
        entry = self.catalog.get(info.name, request.model, usage.unit)
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
                unit_price_version=entry.version,
                estimated_cost=money(usage.units * entry.unit_price),
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

        actual_entry = entry
        if response.usage.unit != usage.unit:
            try:
                actual_entry = self.catalog.get(info.name, request.model, response.usage.unit)
            except UnknownPriceError:
                log.warning(
                    "%s returned usage in unpriced unit %s; committing the estimate",
                    info.name,
                    response.usage.unit,
                )
        if actual_entry.unit == response.usage.unit:
            actual = money(response.usage.units * actual_entry.unit_price)
        else:
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
