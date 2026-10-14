from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest
from cineforge.config import Settings
from cineforge.contracts.media import (
    AssetKind,
    AssetOrigin,
    AssetRecord,
    AssetRepository,
    LicenseInfo,
    RightsStatus,
    storage_key,
)
from cineforge.media.assets import InMemoryAssetRepository, PostgresAssetRepository
from cineforge.media.factory import build_asset_repository
from cineforge.media.rights import DefaultRightsGate
from fakes_d import DATABASE_URL, PgScratch, db_available

GATE = DefaultRightsGate()


@dataclass
class AssetBackend:
    repo: AssetRepository
    tenant_a: str
    tenant_b: str
    pg: PgScratch | None = None

    def production(self, tenant_id: str) -> str:
        if self.pg is not None:
            return self.pg.add_production(tenant_id=tenant_id)
        return f"prod_mem_{uuid.uuid4().hex[:8]}"


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def backend(request: pytest.FixtureRequest) -> Iterator[AssetBackend]:
    if request.param == "memory":
        yield AssetBackend(InMemoryAssetRepository(), "tenant_a", "tenant_b")
        return
    if not db_available():
        pytest.skip("Postgres not reachable")
    pg = PgScratch()
    try:
        yield AssetBackend(PostgresAssetRepository(DATABASE_URL), pg.tenant_id, pg.add_tenant(), pg)
    finally:
        pg.cleanup()


def _asset(
    tenant_id: str,
    production_id: str | None,
    *,
    license: LicenseInfo | None = None,
    created_at: datetime | None = None,
) -> AssetRecord:
    asset_id = f"asset_{uuid.uuid4().hex[:16]}"
    key = storage_key(tenant_id, production_id, AssetKind.IMAGE, f"{asset_id}.jpg")
    return AssetRecord(
        id=asset_id,
        tenant_id=tenant_id,
        production_id=production_id,
        kind=AssetKind.IMAGE,
        origin=AssetOrigin.OPEN_LICENSE if license else AssetOrigin.GENERATED,
        storage_backend="local",
        storage_key=key,
        uri=f"local://{key}",
        content_type="image/jpeg",
        size_bytes=1234,
        sha256="ab" * 32,
        width=1080,
        height=1920,
        source_url="https://example.org/photo" if license else None,
        source_provider="mock-media-search" if license else None,
        license=license,
        rights=GATE.evaluate(license or LicenseInfo(license_type="generated")),
        generation=None if license else {"provider": "mock-image", "model": "mock-image-v1"},
        usage_cost=Decimal("0.04"),
        metadata={"note": "test"},
        **({"created_at": created_at} if created_at else {}),
    )


def test_add_get_round_trip(backend: AssetBackend) -> None:
    pid = backend.production(backend.tenant_a)
    record = _asset(backend.tenant_a, pid)
    stored = backend.repo.add(record)
    assert stored.id == record.id
    got = backend.repo.get(record.id, backend.tenant_a)
    assert got is not None
    assert got.model_dump(exclude={"created_at"}) == record.model_dump(exclude={"created_at"})
    assert got.rights.status == RightsStatus.APPROVED
    # add is idempotent on id
    assert backend.repo.add(record).id == record.id
    assert len(backend.repo.list_for_production(pid, backend.tenant_a)) == 1


def test_license_round_trip(backend: AssetBackend) -> None:
    pid = backend.production(backend.tenant_a)
    license_info = LicenseInfo(
        license_type="CC-BY-4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        author="Jane Doe",
        attribution_text="Photo: Jane Doe / CC BY 4.0",
        attribution_required=True,
        commercial_use_allowed=True,
        modifications_allowed=True,
        restrictions=["credit-in-description"],
        source_provider="mock-media-search",
        source_url="https://example.org/photo",
        retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
    )
    record = _asset(backend.tenant_a, pid, license=license_info)
    assert record.rights.status == RightsStatus.PENDING  # restrictions need review
    backend.repo.add(record)
    got = backend.repo.get(record.id, backend.tenant_a)
    assert got.license == license_info
    assert got.rights == record.rights


def test_tenant_isolation(backend: AssetBackend) -> None:
    """ENG-15: another tenant can never read an asset."""
    pid_a = backend.production(backend.tenant_a)
    pid_b = backend.production(backend.tenant_b)
    a = backend.repo.add(_asset(backend.tenant_a, pid_a))
    b = backend.repo.add(_asset(backend.tenant_b, pid_b))
    assert backend.repo.get(a.id, backend.tenant_b) is None
    assert backend.repo.get(b.id, backend.tenant_a) is None
    assert backend.repo.list_for_production(pid_a, backend.tenant_b) == []
    assert [x.id for x in backend.repo.list_for_production(pid_b, backend.tenant_b)] == [b.id]


def test_list_ordering(backend: AssetBackend) -> None:
    pid = backend.production(backend.tenant_a)
    base = datetime(2026, 10, 13, tzinfo=UTC)
    later = backend.repo.add(_asset(backend.tenant_a, pid, created_at=base + timedelta(seconds=5)))
    earlier = backend.repo.add(_asset(backend.tenant_a, pid, created_at=base))
    ids = [x.id for x in backend.repo.list_for_production(pid, backend.tenant_a)]
    assert ids == [earlier.id, later.id]
    assert backend.repo.get("asset_missing", backend.tenant_a) is None


@pytest.mark.integration
def test_postgres_license_snapshot_row() -> None:
    if not db_available():
        pytest.skip("Postgres not reachable")
    pg = PgScratch()
    try:
        repo = PostgresAssetRepository(DATABASE_URL)
        pid = pg.add_production()
        blocked = _asset(
            pg.tenant_id,
            pid,
            license=LicenseInfo(license_type="CC-BY-NC-4.0", attribution_text="x"),
        )
        no_license = _asset(pg.tenant_id, pid)
        repo.add(blocked)
        repo.add(no_license)
        repo.add(blocked)  # replay must not duplicate the snapshot
        with psycopg.connect(DATABASE_URL) as conn:
            rows = conn.execute(
                "select asset_id, tenant_id, license_type, decision, policy_version, "
                "decision_reasons from asset_licenses where tenant_id = %s",
                (pg.tenant_id,),
            ).fetchall()
            status = conn.execute(
                "select rights_status from assets where id = %s", (blocked.id,)
            ).fetchone()
        assert len(rows) == 1
        asset_id, tenant_id, license_type, decision, policy, reasons = rows[0]
        assert (asset_id, tenant_id, license_type) == (blocked.id, pg.tenant_id, "CC-BY-NC-4.0")
        assert decision == RightsStatus.BLOCKED.value and policy == "v1" and reasons
        assert status[0] == "blocked"
    finally:
        pg.cleanup()


def test_factory() -> None:
    assert isinstance(
        build_asset_repository(Settings(persistence_backend="memory")), InMemoryAssetRepository
    )
    assert isinstance(build_asset_repository(Settings()), PostgresAssetRepository)
