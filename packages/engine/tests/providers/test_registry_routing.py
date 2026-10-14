"""Tenant-aware routing (ENG-12): readiness statuses, priorities, catalog and keys."""

from __future__ import annotations

from typing import Any

import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import (
    KeySource,
    ProviderCapability,
    ProviderNotReadyError,
    ProviderRegistry,
    ProviderSetting,
    ProviderStatus,
    UnsupportedCapabilityError,
)
from cineforge.providers.factory import build_provider_registry
from cineforge.providers.planned import PLANNED_PROVIDERS
from cineforge.providers.registry import key_hint
from cineforge.providers.settings_store import (
    InMemoryProviderSettingsRepository,
    MemorySecretStore,
)
from provider_fakes import Recorder, wikimedia_handler

C = ProviderCapability
T = "tenant_demo"
OTHER = "tenant_other"
STORED_KEY = "fake-ant-stored-key-abcdef9876"
ENV_KEY = "fake-ant-env-key-0000004321"


class Env:
    def __init__(self, **settings: Any) -> None:
        settings.setdefault("persistence_backend", "memory")
        self.settings = Settings(**settings)
        self.secrets = MemorySecretStore()
        self.prefs = InMemoryProviderSettingsRepository()
        self.http = Recorder(wikimedia_handler)
        self.registry = build_provider_registry(
            self.settings,
            secrets=self.secrets,
            provider_settings=self.prefs,
            http_client=self.http.client(self.settings),
        )

    def set(self, provider: str, *, enabled: bool, priority: int = 10, tenant: str = T) -> None:
        self.prefs.upsert(
            ProviderSetting(tenant_id=tenant, provider=provider, enabled=enabled, priority=priority)
        )

    def names(self, capability: ProviderCapability, tenant: str = T) -> list[str]:
        return [p.info.name for p in self.registry.route_all(capability, tenant_id=tenant)]

    def entry(self, name: str, tenant: str = T):
        return next(e for e in self.registry.catalog(tenant) if e.name == name)


def test_mock_mode_routes_only_mocks() -> None:
    env = Env()
    assert isinstance(env.registry, ProviderRegistry)
    assert env.registry.route(C.LLM_TEXT, tenant_id=T).info.name == "mock-llm"
    assert env.names(C.MEDIA_SEARCH) == ["mock-media-search"]
    assert env.names(C.WEB_RESEARCH) == ["mock-research"]
    for name in ("anthropic", "wikipedia", "wikimedia-commons", "openverse"):
        assert env.entry(name).status == ProviderStatus.BLOCKED_MOCK_MODE
    assert env.http.requests == []  # routing never touches the network


def test_live_mode_free_providers_win_by_priority() -> None:
    env = Env(provider_mode="live")
    assert env.registry.route(C.WEB_RESEARCH, tenant_id=T).info.name == "wikipedia"
    # Registration order breaks the priority tie: Commons before Openverse, mock last.
    assert env.names(C.MEDIA_SEARCH) == ["wikimedia-commons", "openverse", "mock-media-search"]
    env.set("openverse", enabled=True, priority=1)
    assert env.names(C.MEDIA_SEARCH) == ["openverse", "wikimedia-commons", "mock-media-search"]
    env.set("mock-media-search", enabled=True, priority=0)
    assert env.names(C.MEDIA_SEARCH)[0] == "mock-media-search"
    # Settings are per tenant.
    assert env.names(C.MEDIA_SEARCH, OTHER)[0] == "wikimedia-commons"


def test_paid_provider_statuses() -> None:
    env = Env(provider_mode="live")
    # Defaults: paid providers start disabled.
    assert env.entry("anthropic").status == ProviderStatus.DISABLED
    assert env.entry("anthropic").enabled is False
    assert env.registry.route(C.LLM_TEXT, tenant_id=T).info.name == "mock-llm"
    env.set("anthropic", enabled=True)
    assert env.entry("anthropic").status == ProviderStatus.BLOCKED_PAID_OFF

    paid = Env(provider_mode="live", allow_paid_providers=True)
    paid.set("anthropic", enabled=True)
    entry = paid.entry("anthropic")
    assert entry.status == ProviderStatus.MISSING_KEY
    assert "ANTHROPIC_API_KEY" in entry.status_detail
    paid.secrets.put(T, "anthropic", STORED_KEY)
    assert paid.entry("anthropic").status == ProviderStatus.READY
    assert paid.registry.route(C.LLM_TEXT, tenant_id=T).info.name == "anthropic"
    assert paid.names(C.LLM_TEXT) == ["anthropic", "mock-llm"]
    # Another tenant has neither the setting nor the key.
    assert paid.entry("anthropic", OTHER).status == ProviderStatus.DISABLED


def test_disabled_free_provider_and_not_ready_errors() -> None:
    env = Env(provider_mode="live")
    env.set("wikipedia", enabled=False)
    env.set("mock-research", enabled=False)
    assert env.entry("wikipedia").status == ProviderStatus.DISABLED
    with pytest.raises(ProviderNotReadyError, match="wikipedia: disabled"):
        env.registry.route(C.WEB_RESEARCH, tenant_id=T)
    assert env.registry.route_all(C.WEB_RESEARCH, tenant_id=T) == []
    with pytest.raises(UnsupportedCapabilityError):
        env.registry.route(C.TRANSCRIPTION, tenant_id=T)
    assert not isinstance(UnsupportedCapabilityError(), ProviderNotReadyError)


def test_env_key_beats_stored_key_and_hint_is_safe() -> None:
    env = Env(provider_mode="live", allow_paid_providers=True, anthropic_api_key=ENV_KEY)
    env.secrets.put(T, "anthropic", STORED_KEY)
    assert env.registry.resolve_key("anthropic", T) == (ENV_KEY, KeySource.ENVIRONMENT)
    env.set("anthropic", enabled=True)
    entry = env.entry("anthropic")
    assert entry.key_source == KeySource.ENVIRONMENT
    assert entry.key_hint == "...4321"
    assert ENV_KEY not in entry.model_dump_json() and STORED_KEY not in entry.model_dump_json()

    stored_only = Env(provider_mode="live")
    assert stored_only.registry.resolve_key("anthropic", T) == (None, KeySource.NONE)
    stored_only.secrets.put(T, "anthropic", STORED_KEY)
    assert stored_only.registry.resolve_key("anthropic", T) == (STORED_KEY, KeySource.STORED)
    entry = stored_only.entry("anthropic")
    assert entry.key_source == KeySource.STORED and entry.key_hint == "...9876"
    assert STORED_KEY not in entry.model_dump_json()
    for catalog_entry in stored_only.registry.catalog(T):
        assert STORED_KEY not in (catalog_entry.key_hint or "")
    stored_only.secrets.delete(T, "anthropic")
    assert stored_only.entry("anthropic").key_source == KeySource.NONE
    assert key_hint("short") == "...set" and key_hint(None) is None


def test_anthropic_key_resolver_is_wired_to_registry() -> None:
    env = Env(provider_mode="live")
    provider = env.registry.get("anthropic")
    assert provider.key_resolver(T) is None
    env.secrets.put(T, "anthropic", STORED_KEY)
    assert provider.key_resolver(T) == STORED_KEY
    assert provider.key_resolver(OTHER) is None


def test_catalog_includes_planned_entries() -> None:
    env = Env()
    catalog = env.registry.catalog(T)
    names = [e.name for e in catalog]
    assert len(names) == len(set(names)) == 13 + len(PLANNED_PROVIDERS)
    planned = [e for e in catalog if e.status == ProviderStatus.PLANNED]
    assert {e.name for e in planned} == {p.name for p in PLANNED_PROVIDERS}
    assert all(not e.enabled and e.planned_phase for e in planned)
    by_name = {e.name: e for e in catalog}
    assert by_name["pexels"].planned_phase == "Phase 1.5"
    assert by_name["runway"].planned_phase == "Phase 2"
    assert C.IMAGE_TO_VIDEO in by_name["runway"].capabilities
    covered = {cap for e in planned for cap in e.capabilities}
    assert {C.MEDIA_SEARCH, C.WEB_RESEARCH, C.IMAGE_GENERATION, C.VIDEO_GENERATION,
            C.IMAGE_TO_VIDEO, C.VOICE_TTS, C.SFX_GENERATION, C.MUSIC_GENERATION,
            C.LIP_SYNC} <= covered  # fmt: skip
    anthropic = by_name["anthropic"]
    assert anthropic.requires_key and anthropic.key_env_var == "ANTHROPIC_API_KEY"
    assert anthropic.models[0] == "claude-sonnet-4-5"
    assert by_name["wikipedia"].priority == 10 and by_name["mock-llm"].priority == 100
    assert env.registry.is_known("pexels") and env.registry.is_known("openverse")
    assert not env.registry.is_known("nope")
    with pytest.raises(LookupError):
        env.registry.get("pexels")  # planned providers are listed, never routable
    assert env.registry.status("pexels", T)[0] == ProviderStatus.PLANNED


def test_catalog_reads_settings_once_per_call() -> None:
    env = Env(provider_mode="live")
    calls = {"list": 0, "get": 0}
    inner = env.prefs

    class Counting:
        def list(self, tenant_id):
            calls["list"] += 1
            return inner.list(tenant_id)

        def get(self, tenant_id, provider):
            calls["get"] += 1
            return inner.get(tenant_id, provider)

        def upsert(self, setting):
            return inner.upsert(setting)

    env.registry.provider_settings = Counting()
    env.registry.catalog(T)
    env.registry.route_all(C.MEDIA_SEARCH, tenant_id=T)
    assert calls == {"list": 2, "get": 0}
