"""Discovery runs, the 15-minute response cache, and daily YouTube method quotas."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import Any

from psycopg.types.json import Json

from cineforge.config import Settings
from cineforge.contracts.discovery import DiscoveryRun
from cineforge.db import connection
from cineforge.providers.youtube import QuotaExhausted


class MemoryDiscoveryStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.runs: dict[tuple[str, str], DiscoveryRun] = {}
        self.by_key: dict[tuple[str, str], str] = {}
        self.cache: dict[tuple[str, str], tuple[datetime, dict[str, Any]]] = {}
        self.quota: dict[tuple[str, str, date], int] = {}

    def purge(self, now: datetime, *, hours: int) -> int:
        cutoff = now - timedelta(hours=hours)
        with self._lock:
            stale = [key for key, run in self.runs.items() if run.retrieved_at < cutoff]
            for key in stale:
                run = self.runs.pop(key)
                self.by_key.pop((run.tenant_id, run.idempotency_key), None)
            expired = [key for key, (exp, _) in self.cache.items() if exp <= now]
            for key in expired:
                self.cache.pop(key, None)
        return len(stale) + len(expired)

    def find_idempotent(self, tenant_id: str, key: str) -> DiscoveryRun | None:
        with self._lock:
            run_id = self.by_key.get((tenant_id, key))
            if run_id is None:
                return None
            return self.runs.get((tenant_id, run_id))

    def get(self, tenant_id: str, run_id: str) -> DiscoveryRun | None:
        with self._lock:
            return self.runs.get((tenant_id, run_id))

    def insert(self, run: DiscoveryRun) -> DiscoveryRun:
        with self._lock:
            existing = self.by_key.get((run.tenant_id, run.idempotency_key))
            if existing is not None:
                return self.runs[(run.tenant_id, existing)]
            self.runs[(run.tenant_id, run.id)] = run
            self.by_key[(run.tenant_id, run.idempotency_key)] = run.id
            return run

    def save(self, run: DiscoveryRun) -> None:
        with self._lock:
            self.runs[(run.tenant_id, run.id)] = run

    def cache_get(self, tenant_id: str, key: str, now: datetime) -> dict[str, Any] | None:
        with self._lock:
            row = self.cache.get((tenant_id, key))
            if row is None or row[0] <= now:
                self.cache.pop((tenant_id, key), None)
                return None
            return row[1]

    def cache_put(
        self, tenant_id: str, key: str, payload: dict[str, Any], expires: datetime
    ) -> None:
        with self._lock:
            self.cache[(tenant_id, key)] = (expires, payload)

    def reserve(self, credential_hash: str, method: str, day: date, allowance: int) -> None:
        if allowance <= 0:
            raise QuotaExhausted(method)
        with self._lock:
            key = (credential_hash, method, day)
            used = self.quota.get(key, 0)
            if used + 1 > allowance:
                raise QuotaExhausted(method)
            self.quota[key] = used + 1


class PostgresDiscoveryStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def purge(self, now: datetime, *, hours: int) -> int:
        cutoff = now - timedelta(hours=hours)
        with connection(self.database_url) as conn:
            runs = conn.execute(
                "delete from discovery_runs where retrieved_at < %s", (cutoff,)
            ).rowcount
            cache = conn.execute(
                "delete from discovery_cache where expires_at <= %s", (now,)
            ).rowcount
        return int(runs or 0) + int(cache or 0)

    def find_idempotent(self, tenant_id: str, key: str) -> DiscoveryRun | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select payload from discovery_runs where tenant_id = %s and idempotency_key = %s",
                (tenant_id, key),
            ).fetchone()
        return DiscoveryRun.model_validate(row["payload"]) if row else None

    def get(self, tenant_id: str, run_id: str) -> DiscoveryRun | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                "select payload from discovery_runs where tenant_id = %s and id = %s",
                (tenant_id, run_id),
            ).fetchone()
        return DiscoveryRun.model_validate(row["payload"]) if row else None

    def insert(self, run: DiscoveryRun) -> DiscoveryRun:
        payload = Json(run.model_dump(mode="json"))
        with connection(self.database_url) as conn:
            row = conn.execute(
                """
                insert into discovery_runs (id, tenant_id, idempotency_key, payload, retrieved_at)
                values (%s, %s, %s, %s, %s)
                on conflict (tenant_id, idempotency_key) do nothing
                returning id
                """,
                (run.id, run.tenant_id, run.idempotency_key, payload, run.retrieved_at),
            ).fetchone()
            if row is None:
                existing = conn.execute(
                    """
                    select payload from discovery_runs
                    where tenant_id = %s and idempotency_key = %s
                    """,
                    (run.tenant_id, run.idempotency_key),
                ).fetchone()
                return DiscoveryRun.model_validate(existing["payload"])
        return run

    def save(self, run: DiscoveryRun) -> None:
        with connection(self.database_url) as conn:
            conn.execute(
                "update discovery_runs set payload = %s where tenant_id = %s and id = %s",
                (Json(run.model_dump(mode="json")), run.tenant_id, run.id),
            )

    def cache_get(self, tenant_id: str, key: str, now: datetime) -> dict[str, Any] | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                """
                select payload from discovery_cache
                where tenant_id = %s and cache_key = %s and expires_at > %s
                """,
                (tenant_id, key, now),
            ).fetchone()
        return row["payload"] if row else None

    def cache_put(
        self, tenant_id: str, key: str, payload: dict[str, Any], expires: datetime
    ) -> None:
        with connection(self.database_url) as conn:
            conn.execute(
                """
                insert into discovery_cache (tenant_id, cache_key, payload, expires_at)
                values (%s, %s, %s, %s)
                on conflict (tenant_id, cache_key) do update
                set payload = excluded.payload, expires_at = excluded.expires_at
                """,
                (tenant_id, key, Json(payload), expires),
            )

    def reserve(self, credential_hash: str, method: str, day: date, allowance: int) -> None:
        if allowance <= 0:
            raise QuotaExhausted(method)
        with connection(self.database_url) as conn:
            row = conn.execute(
                """
                insert into discovery_quota (credential_hash, method, day, used, allowance)
                values (%s, %s, %s, 1, %s)
                on conflict (credential_hash, method, day) do update
                set used = discovery_quota.used + 1, allowance = excluded.allowance
                where discovery_quota.used + 1 <= excluded.allowance
                returning used
                """,
                (credential_hash, method, day, allowance),
            ).fetchone()
        if row is None:
            raise QuotaExhausted(method)


def build_discovery_store(settings: Settings) -> MemoryDiscoveryStore | PostgresDiscoveryStore:
    if settings.persistence_backend == "memory":
        return MemoryDiscoveryStore()
    return PostgresDiscoveryStore(settings.database_url)
