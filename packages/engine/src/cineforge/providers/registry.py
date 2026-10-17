"""In-process provider registry with tenant-aware capability routing (ENG-12).

Readiness per provider and tenant, first failing rule wins:

1. PROVIDER_MODE=mock and the provider is real            -> blocked_mock_mode
2. tenant setting disabled (defaults: mock + free on, paid off) -> disabled
3. paid provider and ALLOW_PAID_PROVIDERS=false            -> blocked_paid_off
4. key required but neither env var nor stored key present -> missing_key
5. otherwise                                               -> ready

``route`` picks the READY provider with the lowest priority number (defaults: real 10,
mock 100), ties broken by registration order.
"""

from __future__ import annotations

import builtins
import threading
from dataclasses import dataclass

from cineforge.config import Settings
from cineforge.contracts.common import DEMO_TENANT_ID
from cineforge.contracts.providers import (
    KeySource,
    Provider,
    ProviderCapability,
    ProviderCatalogEntry,
    ProviderInfo,
    ProviderNotReadyError,
    ProviderSetting,
    ProviderSettingsRepository,
    ProviderStatus,
    SecretStore,
    UnsupportedCapabilityError,
)

REAL_DEFAULT_PRIORITY = 10
MOCK_DEFAULT_PRIORITY = 100


@dataclass(frozen=True)
class PlannedProvider:
    """Listed on the Sources page so options stay visible; not routable yet."""

    name: str
    display_name: str
    capabilities: tuple[ProviderCapability, ...]
    is_paid: bool
    requires_key: bool
    description: str = ""
    docs_url: str | None = None
    planned_phase: str = "Phase 2"


def key_hint(value: str | None) -> str | None:
    if not value:
        return None
    return f"...{value[-4:]}" if len(value) > 8 else "...set"


class InMemoryProviderRegistry:
    def __init__(
        self,
        providers: builtins.list[Provider] | None = None,
        *,
        settings: Settings | None = None,
        secrets: SecretStore | None = None,
        provider_settings: ProviderSettingsRepository | None = None,
        planned: builtins.list[PlannedProvider] | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._providers: dict[str, Provider] = {}
        self.settings = settings
        self.secrets = secrets
        self.provider_settings = provider_settings
        self.planned = list(planned or [])
        for provider in providers or []:
            self.register(provider)

    # ------------------------------------------------------------------ registry
    def register(self, provider: Provider) -> None:
        with self._lock:
            if provider.info.name in self._providers:
                raise ValueError(f"provider {provider.info.name!r} already registered")
            self._providers[provider.info.name] = provider

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError:
            raise LookupError(f"provider {name!r} is not registered") from None

    def for_capability(self, capability: ProviderCapability) -> Provider:
        """First registered provider supporting ``capability`` (registration order)."""
        for provider in self._providers.values():
            if capability in provider.info.capabilities:
                return provider
        raise UnsupportedCapabilityError(f"no registered provider supports {capability}")

    def list(self) -> builtins.list[ProviderInfo]:
        return [p.info for p in self._providers.values()]

    # ------------------------------------------------------------------ routing
    def route(self, capability: ProviderCapability, *, tenant_id: str) -> Provider:
        stored = self._stored_settings(tenant_id)
        ready = self._ready(capability, tenant_id, stored)
        if ready:
            return ready[0]
        candidates = [p for p in self._providers.values() if capability in p.info.capabilities]
        if not candidates:
            raise UnsupportedCapabilityError(f"no registered provider supports {capability}")
        reasons = ", ".join(
            f"{p.info.name}: {self._status(p.info, tenant_id, stored)[0].value}" for p in candidates
        )
        raise ProviderNotReadyError(f"no ready provider for {capability} ({reasons})")

    def route_all(
        self, capability: ProviderCapability, *, tenant_id: str
    ) -> builtins.list[Provider]:
        return self._ready(capability, tenant_id, self._stored_settings(tenant_id))

    def _ready(
        self,
        capability: ProviderCapability,
        tenant_id: str,
        stored: dict[str, ProviderSetting],
    ) -> builtins.list[Provider]:
        ranked: builtins.list[tuple[int, int, Provider]] = []
        for index, provider in enumerate(self._providers.values()):
            if capability not in provider.info.capabilities:
                continue
            status, _ = self._status(provider.info, tenant_id, stored)
            if status == ProviderStatus.READY:
                priority = self._setting(provider.info, tenant_id, stored).priority
                ranked.append((priority, index, provider))
        return [p for _, _, p in sorted(ranked, key=lambda r: (r[0], r[1]))]

    def status(self, provider_name: str, tenant_id: str) -> tuple[ProviderStatus, str]:
        """Readiness of one registered or planned provider for the tenant."""
        provider = self._providers.get(provider_name)
        if provider is None:
            if any(p.name == provider_name for p in self.planned):
                return ProviderStatus.PLANNED, "Not implemented yet"
            raise LookupError(f"provider {provider_name!r} is not registered")
        return self._status(provider.info, tenant_id, self._stored_settings(tenant_id))

    # ------------------------------------------------------------------ keys
    def resolve_key(self, provider_name: str, tenant_id: str) -> tuple[str | None, KeySource]:
        provider = self._providers.get(provider_name)
        env_var = provider.info.key_env_var if provider else None
        if env_var and self.settings is not None:
            value = getattr(self.settings, env_var.lower(), "") or ""
            if value:
                return value, KeySource.ENVIRONMENT
        if self.secrets is not None:
            stored = self.secrets.get(tenant_id, provider_name)
            if stored:
                return stored, KeySource.STORED
        return None, KeySource.NONE

    # ------------------------------------------------------------------ catalog
    def catalog(self, tenant_id: str) -> builtins.list[ProviderCatalogEntry]:
        entries: builtins.list[ProviderCatalogEntry] = []
        stored = self._stored_settings(tenant_id)
        for provider in self._providers.values():
            info = provider.info
            setting = self._setting(info, tenant_id, stored)
            status, detail = self._status(info, tenant_id, stored)
            key, source = (
                self.resolve_key(info.name, tenant_id)
                if info.requires_key
                else (
                    None,
                    KeySource.NONE,
                )
            )
            entries.append(
                ProviderCatalogEntry(
                    name=info.name,
                    display_name=info.display_name,
                    description=info.description,
                    capabilities=list(info.capabilities),
                    models=list(info.models),
                    is_mock=info.is_mock,
                    is_paid=info.is_paid,
                    requires_key=info.requires_key,
                    key_env_var=info.key_env_var,
                    docs_url=info.docs_url,
                    auth_method=info.auth_method,
                    enabled=setting.enabled,
                    priority=setting.priority,
                    status=status,
                    status_detail=detail,
                    key_source=source,
                    key_hint=("connected" if key else None)
                    if info.auth_method == "oauth"
                    else key_hint(key),
                )
            )
        for planned in self.planned:
            entries.append(
                ProviderCatalogEntry(
                    name=planned.name,
                    display_name=planned.display_name,
                    description=planned.description,
                    capabilities=list(planned.capabilities),
                    is_mock=False,
                    is_paid=planned.is_paid,
                    requires_key=planned.requires_key,
                    docs_url=planned.docs_url,
                    planned_phase=planned.planned_phase,
                    enabled=False,
                    priority=REAL_DEFAULT_PRIORITY,
                    status=ProviderStatus.PLANNED,
                    status_detail=f"Not implemented yet ({planned.planned_phase})",
                )
            )
        return entries

    def is_known(self, name: str) -> bool:
        return name in self._providers or any(p.name == name for p in self.planned)

    # ------------------------------------------------------------------ internals
    def _stored_settings(self, tenant_id: str) -> dict[str, ProviderSetting]:
        """All stored settings for the tenant in one repository call."""
        if self.provider_settings is None:
            return {}
        return {s.provider: s for s in self.provider_settings.list(tenant_id)}

    def _setting(
        self, info: ProviderInfo, tenant_id: str, stored: dict[str, ProviderSetting]
    ) -> ProviderSetting:
        if info.name in stored:
            return stored[info.name]
        priority = MOCK_DEFAULT_PRIORITY if info.is_mock else REAL_DEFAULT_PRIORITY
        provider = self._providers.get(info.name)
        custom = getattr(provider, "default_priority", None) if provider is not None else None
        if custom is not None:
            priority = int(custom)
        return ProviderSetting(
            tenant_id=tenant_id or DEMO_TENANT_ID,
            provider=info.name,
            enabled=not info.is_paid,
            priority=priority,
        )

    def _status(
        self, info: ProviderInfo, tenant_id: str, stored: dict[str, ProviderSetting]
    ) -> tuple[ProviderStatus, str]:
        mode = self.settings.provider_mode if self.settings is not None else "mock"
        allow_paid = self.settings.allow_paid_providers if self.settings is not None else False
        if mode == "mock" and not info.is_mock:
            return ProviderStatus.BLOCKED_MOCK_MODE, "PROVIDER_MODE=mock: only mock providers run"
        if not self._setting(info, tenant_id, stored).enabled:
            return ProviderStatus.DISABLED, "Disabled on the Sources page"
        if info.is_paid and not allow_paid:
            return ProviderStatus.BLOCKED_PAID_OFF, "ALLOW_PAID_PROVIDERS=false"
        if info.requires_key and self.resolve_key(info.name, tenant_id)[0] is None:
            if info.auth_method == "oauth":
                return ProviderStatus.MISSING_KEY, f"Sign in to {info.display_name}"
            hint = f" or set {info.key_env_var}" if info.key_env_var else ""
            return ProviderStatus.MISSING_KEY, f"Add an API key{hint}"
        return ProviderStatus.READY, "Ready"
