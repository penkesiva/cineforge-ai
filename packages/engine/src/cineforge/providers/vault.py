"""Supabase Vault secret store (SECRETS_BACKEND=vault).

Secrets are encrypted at rest in ``vault.secrets`` under the name
``cineforge:<tenant>:<key_name>`` and decrypted only through ``vault.decrypted_secrets``
by the database role the API and workers use. Values are never logged.
"""

from __future__ import annotations

from cineforge.db import connection
from cineforge.providers.settings_store import validate_secret_ref, validate_secret_value

PREFIX = "cineforge"


def secret_name(tenant_id: str, key_name: str) -> str:
    validate_secret_ref(tenant_id, key_name)
    return f"{PREFIX}:{tenant_id}:{key_name}"


class VaultSecretStore:
    name = "vault"

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def put(self, tenant_id: str, key_name: str, value: str) -> None:
        name = secret_name(tenant_id, key_name)
        validate_secret_value(value)
        description = f"CineForge API key for {key_name} (tenant {tenant_id})"
        with connection(self.database_url) as conn:
            # Serialize writers of the same name: vault.secrets.name is unique.
            conn.execute("select pg_advisory_xact_lock(hashtext(%s))", (name,))
            row = conn.execute("select id from vault.secrets where name = %s", (name,)).fetchone()
            if row is None:
                conn.execute("select vault.create_secret(%s, %s, %s)", (value, name, description))
            else:
                conn.execute("select vault.update_secret(%s, %s)", (row["id"], value))

    def get(self, tenant_id: str, key_name: str) -> str | None:
        try:
            name = secret_name(tenant_id, key_name)
        except ValueError:
            return None
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select decrypted_secret from vault.decrypted_secrets where name = %s", (name,)
            ).fetchone()
        return row["decrypted_secret"] if row and row["decrypted_secret"] else None

    def delete(self, tenant_id: str, key_name: str) -> None:
        name = secret_name(tenant_id, key_name)
        with connection(self.database_url) as conn:
            conn.execute("delete from vault.secrets where name = %s", (name,))
