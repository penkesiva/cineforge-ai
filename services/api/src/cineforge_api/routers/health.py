"""Liveness and dependency health."""

from __future__ import annotations

from cineforge import db
from cineforge.contracts.api import DependencyHealth, HealthResponse, HealthStatus
from cineforge.contracts.common import new_id
from cineforge.runtime import Runtime
from fastapi import APIRouter

from cineforge_api.deps import RuntimeDep

router = APIRouter(tags=["health"])


@router.get("/health/live", summary="Liveness (no dependency checks)")
def live() -> dict[str, str]:
    return {"status": "ok"}


def _check_database(rt: Runtime) -> DependencyHealth:
    if rt.settings.persistence_backend != "postgres":
        return DependencyHealth(name="database", status=HealthStatus.OK, detail="memory backend")
    ok = db.ping(rt.settings.database_url)
    return DependencyHealth(
        name="database",
        status=HealthStatus.OK if ok else HealthStatus.DOWN,
        detail="postgres reachable" if ok else "postgres unreachable",
    )


def _check_redis(rt: Runtime) -> DependencyHealth:
    if rt.settings.queue_backend != "redis":
        return DependencyHealth(name="redis", status=HealthStatus.OK, detail="inline queue")
    try:
        from redis import Redis

        client = Redis.from_url(rt.settings.redis_url, socket_connect_timeout=2, socket_timeout=2)
        try:
            client.ping()
        finally:
            client.close()
    except Exception as exc:
        return DependencyHealth(
            name="redis", status=HealthStatus.DOWN, detail=f"{type(exc).__name__}: {exc}"[:200]
        )
    return DependencyHealth(name="redis", status=HealthStatus.OK, detail="redis reachable")


def _check_storage(rt: Runtime) -> DependencyHealth:
    key = f"_health/{new_id('probe')}.txt"
    try:
        storage = rt.storage
        storage.put_bytes(key, b"ok", "text/plain")
        storage.delete(key)
    except Exception as exc:
        return DependencyHealth(
            name="storage", status=HealthStatus.DOWN, detail=f"{type(exc).__name__}: {exc}"[:200]
        )
    return DependencyHealth(
        name="storage", status=HealthStatus.OK, detail=f"{storage.name} read/write ok"
    )


@router.get("/health", response_model=HealthResponse, summary="Dependency health")
def health(rt: RuntimeDep) -> HealthResponse:
    checks = [_check_database(rt), _check_redis(rt), _check_storage(rt)]
    degraded = any(c.status != HealthStatus.OK for c in checks)
    return HealthResponse(
        status=HealthStatus.DEGRADED if degraded else HealthStatus.OK,
        version=rt.settings.app_version,
        environment=rt.settings.cineforge_env,
        paid_providers_enabled=rt.settings.allow_paid_providers,
        provider_mode=rt.settings.provider_mode,
        checks=checks,
    )
