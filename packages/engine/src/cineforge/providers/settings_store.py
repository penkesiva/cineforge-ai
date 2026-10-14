"""Provider settings repositories and secret stores (memory + Postgres settings).

The Supabase Vault secret store lives in ``providers/vault.py``.
"""

from __future__ import annotations

import builtins
import threading

from cineforge.contracts.common import utcnow
from cineforge.contracts.providers import ProviderSetting
from cineforge.db import connection


def validate_secret_ref(tenant_id: str, key_name: str) -> None:
    """Both parts end up in a Vault secret name ``cineforge:<tenant>:<key_name>``."""
    for label, value in (("tenant_id", tenant_id), ("key_name", key_name)):
        if not value or ":" in value or value != value.strip():
            raise ValueError(f"invalid {label} {value!r} for a secret reference")


def validate_secret_value(value: str) -> None:
    if not value or not value.strip():
        raise ValueError("secret value must not be empty")


class InMemoryProviderSettingsRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str], ProviderSetting] = {}

    def list(self, tenant_id: str) -> builtins.list[ProviderSetting]:
        with self._lock:
            return [s for (t, _), s in sorted(self._rows.items()) if t == tenant_id]

    def get(self, tenant_id: str, provider: str) -> ProviderSetting | None:
        with self._lock:
            return self._rows.get((tenant_id, provider))

    def upsert(self, setting: ProviderSetting) -> ProviderSetting:
        stored = setting.model_copy(update={"updated_at": utcnow()})
        with self._lock:
            self._rows[(setting.tenant_id, setting.provider)] = stored
        return stored


class PostgresProviderSettingsRepository:
    """Table ``public.provider_settings`` (primary key tenant_id + provider)."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def list(self, tenant_id: str) -> builtins.list[ProviderSetting]:
        with connection(self.database_url) as conn:
            found = conn.execute(
                "select * from provider_settings where tenant_id = %s order by provider",
                (tenant_id,),
            ).fetchall()
        return [ProviderSetting.model_validate(r) for r in found]

    def get(self, tenant_id: str, provider: str) -> ProviderSetting | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select * from provider_settings where tenant_id = %s and provider = %s",
                (tenant_id, provider),
            ).fetchone()
        return ProviderSetting.model_validate(row) if row else None

    def upsert(self, setting: ProviderSetting) -> ProviderSetting:
        with connection(self.database_url) as conn:
            row = conn.execute(
                """
                insert into provider_settings (tenant_id, provider, enabled, priority, updated_at)
                values (%s, %s, %s, %s, now())
                on conflict (tenant_id, provider) do update
                set enabled = excluded.enabled, priority = excluded.priority, updated_at = now()
                returning *
                """,
                (setting.tenant_id, setting.provider, setting.enabled, setting.priority),
            ).fetchone()
        return ProviderSetting.model_validate(row)


class MemorySecretStore:
    """Per-process only: keys vanish on restart and are not shared between the API and
    workers. Tests and single-process demos only (SECRETS_BACKEND=memory)."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], str] = {}

    def put(self, tenant_id: str, key_name: str, value: str) -> None:
        validate_secret_ref(tenant_id, key_name)
        validate_secret_value(value)
        with self._lock:
            self._values[(tenant_id, key_name)] = value

    def get(self, tenant_id: str, key_name: str) -> str | None:
        with self._lock:
            return self._values.get((tenant_id, key_name))

    def delete(self, tenant_id: str, key_name: str) -> None:
        with self._lock:
            self._values.pop((tenant_id, key_name), None)
