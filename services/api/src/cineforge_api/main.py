"""FastAPI application: thin routes over the CineForge engine.

Run locally: ``uv run uvicorn cineforge_api.main:app --reload --port 8000``.
"""

from __future__ import annotations

import logging

from cineforge.config import Settings, get_settings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cineforge_api.errors import install_error_handlers
from cineforge_api.routers import (
    assets,
    catalog,
    connectors,
    external,
    health,
    personas,
    productions,
    providers,
)

TAGS = [
    {"name": "health", "description": "Liveness and dependency checks."},
    {"name": "productions", "description": "Create, run, approve, cancel and deliver."},
    {"name": "costs", "description": "Budgets, cost ledger, price catalog and reports."},
    {"name": "agents", "description": "The 10 logical agents (A1-A10)."},
    {"name": "themes", "description": "Theme profiles and production modes."},
    {"name": "assets", "description": "Tenant-scoped media content."},
    {"name": "personas", "description": "Recurring AI hosts: profile, voice, canon, images."},
    {"name": "providers", "description": "Sources page: provider settings, keys and checks."},
]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level.upper())
    app = FastAPI(
        title="CineForge AI API",
        version=settings.app_version,
        description=(
            "Theme-driven multi-agent cinematic short-video engine "
            f"(provider mode: {settings.provider_mode})."
        ),
        openapi_tags=TAGS,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_error_handlers(app)
    app.include_router(health.router)
    app.include_router(catalog.router)
    app.include_router(productions.router)
    app.include_router(external.router)
    app.include_router(assets.router)
    app.include_router(providers.router)
    app.include_router(connectors.router)
    app.include_router(personas.router)
    return app


app = create_app()
