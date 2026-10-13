"""Read-only catalog endpoints: agents, themes, production modes, pricing."""

from __future__ import annotations

from cineforge.configuration import get_theme, load_mode_policies, theme_summaries
from cineforge.contracts.agents import AgentDefinition
from cineforge.contracts.common import ProductionMode
from cineforge.contracts.cost import PriceCatalogEntry
from cineforge.contracts.theme import ProductionModePolicy, ThemeProfile, ThemeSummary
from fastapi import APIRouter

from cineforge_api.deps import RuntimeDep

router = APIRouter(prefix="/api/v1")


@router.get("/agents", response_model=list[AgentDefinition], tags=["agents"])
def list_agents(rt: RuntimeDep) -> list[AgentDefinition]:
    return rt.agents.definitions()


@router.get("/themes", response_model=list[ThemeSummary], tags=["themes"])
def list_themes(rt: RuntimeDep) -> list[ThemeSummary]:
    return theme_summaries(rt.settings.configurations_dir)


@router.get("/themes/{theme_id}", response_model=ThemeProfile, tags=["themes"])
def get_theme_profile(theme_id: str, rt: RuntimeDep) -> ThemeProfile:
    return get_theme(rt.settings.configurations_dir, theme_id)


@router.get("/modes", response_model=list[ProductionModePolicy], tags=["themes"])
def list_modes(rt: RuntimeDep) -> list[ProductionModePolicy]:
    policies = load_mode_policies(rt.settings.configurations_dir)
    return [policies[mode] for mode in ProductionMode if mode in policies]


@router.get("/pricing", response_model=list[PriceCatalogEntry], tags=["costs"])
def list_pricing(rt: RuntimeDep) -> list[PriceCatalogEntry]:
    return rt.price_catalog.entries()
