"""Composition-root factory for production / agent-run repositories."""

from __future__ import annotations

from cineforge.config import Settings
from cineforge.runtime import Repositories


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
