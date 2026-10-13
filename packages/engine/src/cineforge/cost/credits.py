"""Simulated starting credit balances for mock providers (Phase 0).

Used by both budget services (for tenants without a stored row) and by
scripts/generate_seed.py (credit_balances seed rows for the demo tenant).
"""

from __future__ import annotations

from decimal import Decimal

from cineforge.contracts.cost import CreditBalance

SIMULATED_CREDIT_BALANCES: dict[str, Decimal] = {
    "mock-llm": Decimal("100000"),
    "mock-research": Decimal("10000"),
    "mock-media-search": Decimal("10000"),
    "mock-image": Decimal("5000"),
    "mock-video": Decimal("20000"),
    "mock-voice": Decimal("50000"),
    "mock-music": Decimal("1000"),
    "mock-sfx": Decimal("5000"),
    "mock-lipsync": Decimal("5000"),
}


def with_default_balances(
    tenant_id: str, stored: dict[str, CreditBalance], defaults: dict[str, Decimal]
) -> list[CreditBalance]:
    """Stored balances plus untouched simulated starting balances, sorted by provider."""
    merged = dict(stored)
    for provider, balance in defaults.items():
        merged.setdefault(
            provider, CreditBalance(tenant_id=tenant_id, provider=provider, balance=balance)
        )
    return [merged[p] for p in sorted(merged)]
