"""In-process provider registry with capability routing."""

from __future__ import annotations

import builtins
import threading

from cineforge.contracts.providers import (
    Provider,
    ProviderCapability,
    ProviderInfo,
    UnsupportedCapabilityError,
)


class InMemoryProviderRegistry:
    def __init__(self, providers: builtins.list[Provider] | None = None) -> None:
        self._lock = threading.Lock()
        self._providers: dict[str, Provider] = {}
        for provider in providers or []:
            self.register(provider)

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
