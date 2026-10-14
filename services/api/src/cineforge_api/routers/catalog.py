"""Catalog endpoints: agents, theme registry (ENG-01), production modes, pricing."""

from __future__ import annotations

from typing import Annotated

from cineforge.configuration import load_mode_policies
from cineforge.contracts.agents import AgentDefinition
from cineforge.contracts.api import CreateThemeVersionRequest
from cineforge.contracts.common import ProductionMode
from cineforge.contracts.cost import PriceCatalogEntry
from cineforge.contracts.theme import ProductionModePolicy, ThemeProfile, ThemeSummary
from fastapi import APIRouter, Query, status

from cineforge_api.deps import RuntimeDep

router = APIRouter(prefix="/api/v1")


@router.get("/agents", response_model=list[AgentDefinition], tags=["agents"])
def list_agents(rt: RuntimeDep) -> list[AgentDefinition]:
    return rt.agents.definitions()


@router.get("/themes", response_model=list[ThemeSummary], tags=["themes"])
def list_themes(rt: RuntimeDep) -> list[ThemeSummary]:
    return rt.themes.summaries()


@router.get("/themes/{theme_id}", response_model=ThemeProfile, tags=["themes"])
def get_theme_profile(
    theme_id: str,
    rt: RuntimeDep,
    version: Annotated[int | None, Query(ge=1, description="Default: latest")] = None,
) -> ThemeProfile:
    return rt.themes.get(theme_id, version)


@router.get("/themes/{theme_id}/versions", response_model=list[ThemeProfile], tags=["themes"])
def list_theme_versions(theme_id: str, rt: RuntimeDep) -> list[ThemeProfile]:
    return rt.themes.versions(theme_id)


@router.post(
    "/themes/{theme_id}/versions",
    response_model=ThemeProfile,
    status_code=status.HTTP_201_CREATED,
    tags=["themes"],
    summary="Save an edited theme as a new immutable version (409 if base is stale)",
)
def create_theme_version(
    theme_id: str, body: CreateThemeVersionRequest, rt: RuntimeDep
) -> ThemeProfile:
    profile = body.profile.model_copy(update={"id": theme_id})
    return rt.themes.create_version(profile, base_version=body.base_version)


@router.get("/modes", response_model=list[ProductionModePolicy], tags=["themes"])
def list_modes(rt: RuntimeDep) -> list[ProductionModePolicy]:
    policies = load_mode_policies(rt.settings.configurations_dir)
    return [policies[mode] for mode in ProductionMode if mode in policies]


@router.get("/pricing", response_model=list[PriceCatalogEntry], tags=["costs"])
def list_pricing(rt: RuntimeDep) -> list[PriceCatalogEntry]:
    return rt.price_catalog.entries()
