"""Environment-based settings. Switching local Supabase -> Supabase Cloud is config only."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from cineforge.contracts.common import DEMO_TENANT_ID, ProductionMode

_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    cineforge_env: str = "development"
    app_version: str = "0.1.0"
    log_level: str = "INFO"
    default_tenant_id: str = DEMO_TENANT_ID
    default_production_mode: ProductionMode = ProductionMode.BALANCED

    persistence_backend: Literal["postgres", "memory"] = "postgres"
    database_url: str = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"

    queue_backend: Literal["redis", "inline"] = "redis"
    redis_url: str = "redis://127.0.0.1:6379/0"

    storage_backend: Literal["local", "supabase"] = "local"
    storage_local_root: Path = _REPO_ROOT / "var" / "media"
    supabase_url: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "cineforge-media"

    # mock: only mock providers are routable (offline, $0). live: real providers that are
    # enabled on the Sources page and ready (key present, paid calls allowed) win by priority.
    provider_mode: Literal["mock", "live"] = "mock"
    allow_paid_providers: bool = False
    # Comma-separated catalog versions, merged (packages/configurations/pricing/<v>.yaml).
    price_catalog_version: str = "mock-2026-10,open-sources-2026-10,anthropic-2026-10"
    # Where API keys entered on the Sources page live. vault = Supabase Vault (encrypted in
    # Postgres, shared by api + workers); memory = per-process (tests only).
    secrets_backend: Literal["vault", "memory"] = "vault"
    # Keys from the environment take priority over stored keys.
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_base_url: str = "https://api.anthropic.com"
    http_timeout_sec: float = Field(default=20.0, gt=0, le=120)
    # Wikimedia APIs require a descriptive User-Agent with contact info.
    http_user_agent: str = "CineForgeAI/0.2 (https://github.com/penkesiva/cineforge-ai)"
    # Demo knobs (mock providers only): pause between workflow steps so progress is
    # visible, and a deterministic failure rate to exercise bounded retries.
    mock_step_delay_sec: float = Field(default=0.0, ge=0, le=10)
    mock_failure_rate: float = Field(default=0.0, ge=0, le=0.5)

    configurations_dir: Path = _REPO_ROOT / "packages" / "configurations"
    prompts_dir: Path = _REPO_ROOT / "packages" / "prompts"

    cors_origins: str = Field(default="http://localhost:3000", description="Comma-separated")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
