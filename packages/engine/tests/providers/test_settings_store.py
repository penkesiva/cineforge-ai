"""Provider settings + secret stores: memory always, Postgres/Vault as integration tests."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass

import psycopg
import pytest
from cineforge.config import Settings
from cineforge.contracts.providers import (
    KeySource,
    ProviderSetting,
    ProviderSettingsRepository,
    SecretStore,
)
from cineforge.providers.factory import (
    build_provider_registry,
    build_provider_settings_repository,
    build_secret_store,
)
from cineforge.providers.settings_store import (
    InMemoryProviderSettingsRepository,
    MemorySecretStore,
)
from fakes_d import DATABASE_URL, PgScratch, db_available

SECRET = "fake-ant-integration-" + "x" * 12 + "7f3a"


@dataclass
class Stores:
    name: str
    tenant_id: str
    settings: ProviderSettingsRepository
    secrets: SecretStore
    other_tenant: str


def _cleanup(tenants: list[str]) -> None:
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn:
        for tenant in tenants:
            with suppress(psycopg.Error):
                conn.execute("delete from provider_settings where tenant_id = %s", (tenant,))
            with suppress(psycopg.Error):
                conn.execute(
                    "delete from vault.secrets where name like %s", (f"cineforge:{tenant}:%",)
                )


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def stores(request: pytest.FixtureRequest) -> Iterator[Stores]:
    if request.param == "memory":
        yield Stores(
            "memory",
            "tenant_mem_a",
            InMemoryProviderSettingsRepository(),
            MemorySecretStore(),
            "tenant_mem_b",
        )
        return
    if not db_available():
        pytest.skip("Postgres not reachable")
    from cineforge.providers.settings_store import PostgresProviderSettingsRepository
    from cineforge.providers.vault import VaultSecretStore

    pg = PgScratch()
    other = pg.add_tenant()
    try:
        yield Stores(
            "postgres",
            pg.tenant_id,
            PostgresProviderSettingsRepository(DATABASE_URL),
            VaultSecretStore(DATABASE_URL),
            other,
        )
    finally:
        _cleanup(pg.tenants)
        pg.cleanup()


def test_settings_upsert_get_list(stores: Stores) -> None:
    repo = stores.settings
    assert isinstance(repo, ProviderSettingsRepository)
    t = stores.tenant_id
    assert repo.get(t, "wikipedia") is None and repo.list(t) == []
    first = repo.upsert(ProviderSetting(tenant_id=t, provider="wikipedia", enabled=False))
    assert first.enabled is False and first.priority == 100
    updated = repo.upsert(
        ProviderSetting(tenant_id=t, provider="wikipedia", enabled=True, priority=5)
    )
    assert (updated.enabled, updated.priority) == (True, 5)
    assert updated.updated_at >= first.updated_at
    repo.upsert(ProviderSetting(tenant_id=t, provider="anthropic", enabled=True, priority=1))
    assert [s.provider for s in repo.list(t)] == ["anthropic", "wikipedia"]
    assert repo.get(t, "wikipedia").priority == 5
    assert repo.list(stores.other_tenant) == []


def test_secrets_put_get_update_delete(stores: Stores) -> None:
    secrets = stores.secrets
    assert isinstance(secrets, SecretStore) and secrets.name == stores.name.replace(
        "postgres", "vault"
    )
    t = stores.tenant_id
    assert secrets.get(t, "anthropic") is None
    secrets.put(t, "anthropic", SECRET)
    assert secrets.get(t, "anthropic") == SECRET
    secrets.put(t, "anthropic", SECRET + "-rotated")
    assert secrets.get(t, "anthropic") == SECRET + "-rotated"
    assert secrets.get(stores.other_tenant, "anthropic") is None
    secrets.delete(t, "anthropic")
    assert secrets.get(t, "anthropic") is None
    secrets.delete(t, "anthropic")  # idempotent
    with pytest.raises(ValueError):
        secrets.put(t, "anthropic", "  ")
    with pytest.raises(ValueError):
        secrets.put(t, "bad:name", SECRET)


@pytest.mark.integration
def test_vault_stores_ciphertext_only() -> None:
    if not db_available():
        pytest.skip("Postgres not reachable")
    from cineforge.providers.vault import VaultSecretStore, secret_name

    tenant = f"tenant_vault_{uuid.uuid4().hex[:8]}"
    store = VaultSecretStore(DATABASE_URL)
    try:
        store.put(tenant, "anthropic", SECRET)
        with psycopg.connect(DATABASE_URL) as conn:
            row = conn.execute(
                "select secret, description from vault.secrets where name = %s",
                (secret_name(tenant, "anthropic"),),
            ).fetchone()
        assert row is not None and SECRET not in row[0] and SECRET not in row[1]
    finally:
        _cleanup([tenant])


@pytest.mark.integration
def test_postgres_registry_end_to_end() -> None:
    if not db_available():
        pytest.skip("Postgres not reachable")
    pg = PgScratch()
    try:
        settings = Settings(
            persistence_backend="postgres",
            secrets_backend="vault",
            provider_mode="live",
            allow_paid_providers=True,
            database_url=DATABASE_URL,
        )
        secrets = build_secret_store(settings)
        prefs = build_provider_settings_repository(settings)
        registry = build_provider_registry(settings, secrets=secrets, provider_settings=prefs)
        t = pg.tenant_id
        prefs.upsert(ProviderSetting(tenant_id=t, provider="anthropic", enabled=True, priority=10))
        secrets.put(t, "anthropic", SECRET)
        entry = next(e for e in registry.catalog(t) if e.name == "anthropic")
        assert entry.status == "ready" and entry.key_source == KeySource.STORED
        assert entry.key_hint == "...7f3a"
        assert registry.route_all("llm_text", tenant_id=t)[0].info.name == "anthropic"
    finally:
        _cleanup(pg.tenants)
        pg.cleanup()


def test_factory_backend_selection() -> None:
    memory = Settings(persistence_backend="memory", secrets_backend="vault")
    assert isinstance(build_secret_store(memory), MemorySecretStore)
    assert isinstance(
        build_provider_settings_repository(memory), InMemoryProviderSettingsRepository
    )
    pg_memory_secrets = Settings(persistence_backend="postgres", secrets_backend="memory")
    assert isinstance(build_secret_store(pg_memory_secrets), MemorySecretStore)

    from cineforge.providers.settings_store import PostgresProviderSettingsRepository
    from cineforge.providers.vault import VaultSecretStore

    vault = Settings(persistence_backend="postgres", secrets_backend="vault")
    assert isinstance(build_secret_store(vault), VaultSecretStore)
    assert isinstance(build_provider_settings_repository(vault), PostgresProviderSettingsRepository)
