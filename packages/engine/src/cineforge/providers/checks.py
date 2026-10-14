"""Connectivity checks behind ``POST /providers/{name}/test``.

Checks are free by construction (Anthropic: ``GET /v1/models``; Wikimedia: siteinfo;
Openverse: a one-result search), never go through the PaidCallGuard and never raise.
"""

from __future__ import annotations

import logging
import time
from typing import Protocol, runtime_checkable

from cineforge.contracts.api import ProviderTestResult
from cineforge.contracts.providers import ProviderRegistry

log = logging.getLogger(__name__)


@runtime_checkable
class CheckableProvider(Protocol):
    def check(self, tenant_id: str | None = None) -> tuple[bool, str]:
        """(ok, human-readable detail). Must not spend money or raise ProviderError."""
        ...


def check_provider(registry: ProviderRegistry, name: str, tenant_id: str) -> ProviderTestResult:
    try:
        provider = registry.get(name)
    except LookupError:
        planned = next((p for p in getattr(registry, "planned", []) if p.name == name), None)
        detail = (
            f"planned for {planned.planned_phase}: not implemented yet"
            if planned is not None
            else "unknown provider"
        )
        return ProviderTestResult(provider=name, ok=False, detail=detail)
    if provider.info.is_mock:
        return ProviderTestResult(provider=name, ok=True, detail="mock provider (offline)")
    if not isinstance(provider, CheckableProvider):
        return ProviderTestResult(provider=name, ok=False, detail="no connectivity check")
    started = time.monotonic()
    try:
        ok, detail = provider.check(tenant_id)
    except Exception as exc:  # a check must never break the API
        log.warning("provider check %s failed: %s", name, type(exc).__name__)
        ok, detail = False, f"check failed: {type(exc).__name__}: {exc}"
    return ProviderTestResult(
        provider=name,
        ok=ok,
        detail=detail,
        latency_ms=int((time.monotonic() - started) * 1000),
        paid_call=False,
    )
