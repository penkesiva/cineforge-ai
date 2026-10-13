"""Asset metadata repositories (memory + Postgres). Every read is tenant-scoped (ENG-15)."""

from __future__ import annotations

import threading
from typing import Any

from psycopg.types.json import Jsonb

from cineforge.contracts.common import money
from cineforge.contracts.media import AssetRecord, LicenseInfo, RightsDecision
from cineforge.db import connection


class InMemoryAssetRepository:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._assets: dict[str, AssetRecord] = {}

    def add(self, record: AssetRecord) -> AssetRecord:
        with self._lock:
            existing = self._assets.setdefault(record.id, record.model_copy(deep=True))
            return existing.model_copy(deep=True)

    def get(self, asset_id: str, tenant_id: str) -> AssetRecord | None:
        with self._lock:
            record = self._assets.get(asset_id)
            if record is None or record.tenant_id != tenant_id:
                return None
            return record.model_copy(deep=True)

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AssetRecord]:
        with self._lock:
            found = [
                a
                for a in self._assets.values()
                if a.production_id == production_id and a.tenant_id == tenant_id
            ]
        return [a.model_copy(deep=True) for a in sorted(found, key=lambda a: a.created_at)]


_SELECT = """
select a.*, l.license_type, l.license_url, l.author, l.attribution_text,
       l.attribution_required, l.commercial_use_allowed, l.modifications_allowed,
       l.restrictions, l.source_provider as license_source_provider,
       l.source_url as license_source_url, l.retrieved_at, l.id as license_row_id
from assets a
left join lateral (
    select * from asset_licenses al where al.asset_id = a.id order by al.id desc limit 1
) l on true
"""


def _record(row: dict[str, Any]) -> AssetRecord:
    license_info = None
    if row["license_row_id"] is not None:
        license_info = LicenseInfo(
            license_type=row["license_type"],
            license_url=row["license_url"],
            author=row["author"],
            attribution_text=row["attribution_text"],
            attribution_required=row["attribution_required"],
            commercial_use_allowed=row["commercial_use_allowed"],
            modifications_allowed=row["modifications_allowed"],
            restrictions=row["restrictions"] or [],
            source_provider=row["license_source_provider"],
            source_url=row["license_source_url"],
            retrieved_at=row["retrieved_at"],
        )
    return AssetRecord(
        id=row["id"],
        tenant_id=row["tenant_id"],
        production_id=row["production_id"],
        kind=row["kind"],
        origin=row["origin"],
        storage_backend=row["storage_backend"],
        storage_key=row["storage_key"],
        uri=row["uri"],
        content_type=row["content_type"],
        size_bytes=row["size_bytes"],
        sha256=row["sha256"],
        perceptual_hash=row["perceptual_hash"],
        width=row["width"],
        height=row["height"],
        duration_sec=row["duration_sec"],
        source_url=row["source_url"],
        source_provider=row["source_provider"],
        license=license_info,
        rights=RightsDecision.model_validate(row["rights"]),
        generation=row["generation"],
        usage_cost=money(row["usage_cost"]),
        metadata=row["metadata"] or {},
        created_at=row["created_at"],
    )


class PostgresAssetRepository:
    """Rows in ``assets`` plus an immutable license snapshot in ``asset_licenses``."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def add(self, record: AssetRecord) -> AssetRecord:
        with connection(self.database_url) as conn:
            inserted = conn.execute(
                """
                insert into assets (id, tenant_id, production_id, kind, origin, storage_backend,
                    storage_key, uri, content_type, size_bytes, sha256, perceptual_hash, width,
                    height, duration_sec, source_url, source_provider, rights_status, rights,
                    generation, usage_cost, metadata, created_at)
                values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
                on conflict (id) do nothing
                returning id
                """,
                (record.id, record.tenant_id, record.production_id, record.kind.value,
                 record.origin.value, record.storage_backend, record.storage_key, record.uri,
                 record.content_type, record.size_bytes, record.sha256, record.perceptual_hash,
                 record.width, record.height, record.duration_sec, record.source_url,
                 record.source_provider, record.rights.status.value,
                 Jsonb(record.rights.model_dump(mode="json")),
                 Jsonb(record.generation) if record.generation is not None else None,
                 record.usage_cost, Jsonb(record.metadata), record.created_at),
            ).fetchone()  # fmt: skip
            if inserted is not None and record.license is not None:
                lic = record.license
                conn.execute(
                    """
                    insert into asset_licenses (asset_id, tenant_id, license_type, license_url,
                        author, attribution_text, attribution_required, commercial_use_allowed,
                        modifications_allowed, restrictions, source_provider, source_url,
                        retrieved_at, decision, decision_reasons, policy_version)
                    values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (record.id, record.tenant_id, lic.license_type, lic.license_url, lic.author,
                     lic.attribution_text, lic.attribution_required, lic.commercial_use_allowed,
                     lic.modifications_allowed, Jsonb(lic.restrictions), lic.source_provider,
                     lic.source_url, lic.retrieved_at, record.rights.status.value,
                     Jsonb(record.rights.reasons), record.rights.policy_version),
                )  # fmt: skip
            row = conn.execute(f"{_SELECT} where a.id = %s", (record.id,)).fetchone()
            return _record(row)

    def get(self, asset_id: str, tenant_id: str) -> AssetRecord | None:
        with connection(self.database_url) as conn:
            row = conn.execute(
                f"{_SELECT} where a.id = %s and a.tenant_id = %s", (asset_id, tenant_id)
            ).fetchone()
        return _record(row) if row else None

    def list_for_production(self, production_id: str, tenant_id: str) -> list[AssetRecord]:
        with connection(self.database_url) as conn:
            found = conn.execute(
                f"{_SELECT} where a.production_id = %s and a.tenant_id = %s "
                "order by a.created_at, a.id",
                (production_id, tenant_id),
            ).fetchall()
        return [_record(r) for r in found]
