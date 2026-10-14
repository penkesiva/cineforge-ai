"""Loads versioned YAML configuration (themes, production modes) from packages/configurations."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from cineforge.contracts.common import ProductionMode
from cineforge.contracts.theme import ProductionModePolicy, ThemeProfile, ThemeSummary


class ThemeNotFoundError(LookupError):
    pass


@lru_cache(maxsize=8)
def load_themes(configurations_dir: Path) -> dict[tuple[str, int], ThemeProfile]:
    themes: dict[tuple[str, int], ThemeProfile] = {}
    for path in sorted((configurations_dir / "themes").glob("*.yaml")):
        theme = ThemeProfile.model_validate(yaml.safe_load(path.read_text()))
        themes[(theme.id, theme.version)] = theme
    return themes


def get_theme(configurations_dir: Path, theme_id: str, version: int | None = None) -> ThemeProfile:
    themes = load_themes(configurations_dir)
    matches = [t for (tid, _), t in themes.items() if tid == theme_id]
    if version is not None:
        matches = [t for t in matches if t.version == version]
    if not matches:
        raise ThemeNotFoundError(f"theme {theme_id!r} (version {version}) not found")
    return max(matches, key=lambda t: t.version)


def theme_summaries(configurations_dir: Path) -> list[ThemeSummary]:
    latest: dict[str, ThemeProfile] = {}
    for theme in load_themes(configurations_dir).values():
        if theme.id not in latest or theme.version > latest[theme.id].version:
            latest[theme.id] = theme
    return [
        ThemeSummary(
            id=t.id,
            version=t.version,
            name=t.name,
            purpose=t.purpose,
            genres=t.genres,
            default_mode=t.production.default_mode,
        )
        for t in sorted(latest.values(), key=lambda t: t.id)
    ]


@lru_cache(maxsize=8)
def load_mode_policies(configurations_dir: Path) -> dict[ProductionMode, ProductionModePolicy]:
    raw = yaml.safe_load((configurations_dir / "modes.yaml").read_text())
    policies = [ProductionModePolicy.model_validate(item) for item in raw["modes"]]
    return {p.mode: p for p in policies}
