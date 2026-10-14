"""Frozen shared contracts (Phase 0).

Changing anything in this package is a CONTRACT CHANGE: it requires updating
docs/architecture/contracts.md, regenerating packages/schemas (``make contracts``)
and notifying every workstream. See AGENTS.md.
"""

from cineforge.contracts import (
    agents,
    api,
    common,
    cost,
    jobs,
    manifest,
    media,
    providers,
    repositories,
    review,
    theme,
    workflow,
)

__all__ = [
    "agents",
    "api",
    "common",
    "cost",
    "jobs",
    "manifest",
    "media",
    "providers",
    "repositories",
    "review",
    "theme",
    "workflow",
]
