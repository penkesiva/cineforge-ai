"""Theme registry (ENG-01): YAML seeds + immutable versions created from the dashboard."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from cineforge.configuration import ThemeNotFoundError, load_themes
from cineforge.contracts.repositories import ThemeVersionConflictError
from cineforge.contracts.theme import ThemeProfile, ThemeSummary
from cineforge.db import connection


def _summary(theme: ThemeProfile) -> ThemeSummary:
    return ThemeSummary(
        id=theme.id,
        version=theme.version,
        name=theme.name,
        purpose=theme.purpose,
        genres=theme.genres,
        default_mode=theme.production.default_mode,
    )


class _ThemeRegistryBase:
    def _all(self) -> dict[tuple[str, int], ThemeProfile]:
        raise NotImplementedError

    def _insert(self, profile: ThemeProfile) -> bool:
        """Insert a new version; False if (id, version) already exists."""
        raise NotImplementedError

    def summaries(self) -> list[ThemeSummary]:
        latest: dict[str, ThemeProfile] = {}
        for theme in self._all().values():
            if theme.id not in latest or theme.version > latest[theme.id].version:
                latest[theme.id] = theme
        return [_summary(t) for t in sorted(latest.values(), key=lambda t: t.id)]

    def versions(self, theme_id: str) -> list[ThemeProfile]:
        found = sorted(
            (t for (tid, _), t in self._all().items() if tid == theme_id),
            key=lambda t: t.version,
        )
        if not found:
            raise ThemeNotFoundError(f"theme {theme_id!r} not found")
        return found

    def get(self, theme_id: str, version: int | None = None) -> ThemeProfile:
        versions = self.versions(theme_id)
        if version is None:
            return versions[-1]
        for theme in versions:
            if theme.version == version:
                return theme
        raise ThemeNotFoundError(f"theme {theme_id!r} (version {version}) not found")

    def create_version(self, profile: ThemeProfile, *, base_version: int) -> ThemeProfile:
        latest = self.versions(profile.id)[-1]
        if base_version != latest.version:
            raise ThemeVersionConflictError(
                f"theme {profile.id!r}: latest is v{latest.version}, not v{base_version}"
            )
        created = profile.model_copy(update={"version": latest.version + 1})
        created = ThemeProfile.model_validate(created.model_dump())
        if not self._insert(created):
            raise ThemeVersionConflictError(
                f"theme {profile.id!r} v{created.version} was created concurrently"
            )
        return created


class InMemoryThemeRepository(_ThemeRegistryBase):
    def __init__(self, configurations_dir: Path) -> None:
        self._lock = threading.Lock()
        self._themes = dict(load_themes(configurations_dir))

    def _all(self) -> dict[tuple[str, int], ThemeProfile]:
        with self._lock:
            return dict(self._themes)

    def _insert(self, profile: ThemeProfile) -> bool:
        with self._lock:
            key = (profile.id, profile.version)
            if key in self._themes:
                return False
            self._themes[key] = profile
            return True


class PostgresThemeRepository(_ThemeRegistryBase):
    """``public.theme_profiles`` holds every version; YAML seeds are upserted lazily so
    a fresh database (or one seeded by supabase/seed.sql) always has them."""

    def __init__(self, database_url: str, configurations_dir: Path) -> None:
        self.database_url = database_url
        self.configurations_dir = configurations_dir
        self._seeded = False
        self._lock = threading.Lock()

    def _seed(self) -> None:
        with self._lock:
            if self._seeded:
                return
            with connection(self.database_url) as conn:
                for theme in load_themes(self.configurations_dir).values():
                    conn.execute(
                        "insert into public.theme_profiles (id, version, name, config) "
                        "values (%s, %s, %s, %s::jsonb) on conflict (id, version) do nothing",
                        (theme.id, theme.version, theme.name, theme.model_dump_json()),
                    )
            self._seeded = True

    def _all(self) -> dict[tuple[str, int], ThemeProfile]:
        self._seed()
        with connection(self.database_url) as conn:
            rows = conn.execute("select config from public.theme_profiles").fetchall()
        themes: dict[tuple[str, int], ThemeProfile] = {}
        for row in rows:
            config = row["config"]
            data = config if isinstance(config, dict) else json.loads(config)
            theme = ThemeProfile.model_validate(data)
            themes[(theme.id, theme.version)] = theme
        return themes

    def _insert(self, profile: ThemeProfile) -> bool:
        self._seed()
        with connection(self.database_url) as conn:
            cur = conn.execute(
                "insert into public.theme_profiles (id, version, name, config) "
                "values (%s, %s, %s, %s::jsonb) on conflict (id, version) do nothing",
                (profile.id, profile.version, profile.name, profile.model_dump_json()),
            )
            return cur.rowcount == 1
