"""Composition-root factory for production / agent-run repositories."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.contracts.repositories import ThemeRepository
from cineforge.runtime import Repositories


def build_theme_repository(settings: Settings) -> ThemeRepository:
    from cineforge.persistence.themes import InMemoryThemeRepository, PostgresThemeRepository

    if settings.persistence_backend == "memory":
        return InMemoryThemeRepository(settings.configurations_dir)
    return PostgresThemeRepository(settings.database_url, settings.configurations_dir)


def build_repositories(settings: Settings) -> Repositories:
    if settings.persistence_backend == "memory":
        from cineforge.persistence.memory import (
            InMemoryAgentRunRepository,
            InMemoryProductionRepository,
        )

        return Repositories(
            productions=InMemoryProductionRepository(),
            agent_runs=InMemoryAgentRunRepository(),
        )
    from cineforge.persistence.postgres import (
        PostgresAgentRunRepository,
        PostgresProductionRepository,
    )

    return Repositories(
        productions=PostgresProductionRepository(settings.database_url),
        agent_runs=PostgresAgentRunRepository(settings.database_url),
    )
