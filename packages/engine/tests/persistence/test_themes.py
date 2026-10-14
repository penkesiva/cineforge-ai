"""Theme registry (ENG-01) against the memory and (integration) Postgres backends."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from cineforge.config import Settings
from cineforge.configuration import ThemeNotFoundError
from cineforge.contracts.repositories import ThemeVersionConflictError
from cineforge.persistence.themes import InMemoryThemeRepository, PostgresThemeRepository

SETTINGS = Settings()
CFG = SETTINGS.configurations_dir
DB_URL = SETTINGS.database_url


@pytest.fixture(params=["memory", pytest.param("postgres", marks=pytest.mark.integration)])
def repo(request: pytest.FixtureRequest) -> Iterator[tuple[object, str]]:
    """A registry plus a throwaway theme id (a copy of a YAML seed) to version."""
    theme_id = f"test-theme-{uuid.uuid4().hex[:8]}"
    if request.param == "memory":
        registry = InMemoryThemeRepository(CFG)
    else:
        from cineforge.db import connection, ping

        if not ping(DB_URL):
            pytest.skip("Postgres not reachable")
        registry = PostgresThemeRepository(DB_URL, CFG)
    seed = registry.get("time-traveler").model_copy(update={"id": theme_id, "version": 1})
    assert registry._insert(seed)
    try:
        yield registry, theme_id
    finally:
        if request.param == "postgres":
            with connection(DB_URL) as conn:
                conn.execute("delete from public.theme_profiles where id = %s", (theme_id,))


def test_yaml_seeds_are_listed(repo) -> None:
    registry, _ = repo
    ids = {s.id for s in registry.summaries()}
    assert {"time-traveler", "mystery-explorer", "fascinating-places"} <= ids


def test_create_version_is_immutable_and_optimistic(repo) -> None:
    registry, theme_id = repo
    v1 = registry.get(theme_id)
    v2 = registry.create_version(v1.model_copy(update={"tone": "Hushed"}), base_version=1)
    assert v2.version == 2 and v2.tone == "Hushed"
    assert registry.get(theme_id).version == 2
    assert registry.get(theme_id, 1).tone == v1.tone
    assert [t.version for t in registry.versions(theme_id)] == [1, 2]
    with pytest.raises(ThemeVersionConflictError):
        registry.create_version(v1.model_copy(update={"tone": "Stale"}), base_version=1)
    assert registry.get(theme_id).tone == "Hushed"


def test_missing_theme_or_version(repo) -> None:
    registry, theme_id = repo
    with pytest.raises(ThemeNotFoundError):
        registry.get("no-such-theme")
    with pytest.raises(ThemeNotFoundError):
        registry.get(theme_id, 99)
