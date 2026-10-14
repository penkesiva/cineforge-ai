"""Provider settings repositories and secret stores (memory implementations)."""

from __future__ import annotations

import builtins
import threading

from cineforge.contracts.common import utcnow
from cineforge.contracts.providers import ProviderSetting


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


class MemorySecretStore:
    """Per-process only: keys vanish on restart and are not shared between the API and
    workers. Tests and single-process demos only (SECRETS_BACKEND=memory)."""

    name = "memory"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str], str] = {}

    def put(self, tenant_id: str, key_name: str, value: str) -> None:
        with self._lock:
            self._values[(tenant_id, key_name)] = value

    def get(self, tenant_id: str, key_name: str) -> str | None:
        with self._lock:
            return self._values.get((tenant_id, key_name))

    def delete(self, tenant_id: str, key_name: str) -> None:
        with self._lock:
            self._values.pop((tenant_id, key_name), None)
