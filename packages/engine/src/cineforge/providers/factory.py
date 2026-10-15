"""Composition-root factories for providers (names fixed by the contract)."""

from __future__ import annotations

import httpx

from cineforge.config import Settings
from cineforge.contracts.cost import BudgetService, PriceCatalog
from cineforge.contracts.providers import (
    PaidCallGuard,
    ProviderRegistry,
    ProviderSettingsRepository,
    SecretStore,
)
from cineforge.providers.anthropic import AnthropicProvider
from cineforge.providers.commons import CommonsMediaProvider
from cineforge.providers.guard import DefaultPaidCallGuard
from cineforge.providers.higgsfield import NAME as HIGGSFIELD
from cineforge.providers.higgsfield import HiggsfieldProvider
from cineforge.providers.http import build_http_client
from cineforge.providers.mock import build_mock_providers
from cineforge.providers.oauth import McpOAuth
from cineforge.providers.openverse import OpenverseMediaProvider
from cineforge.providers.planned import PLANNED_PROVIDERS
from cineforge.providers.registry import InMemoryProviderRegistry
from cineforge.providers.settings_store import (
    InMemoryProviderSettingsRepository,
    MemorySecretStore,
)
from cineforge.providers.wikipedia import WikipediaResearchProvider


def build_secret_store(settings: Settings) -> SecretStore:
    """PERSISTENCE_BACKEND=memory always uses memory; otherwise SECRETS_BACKEND decides."""
    if settings.persistence_backend == "memory" or settings.secrets_backend == "memory":
        return MemorySecretStore()
    from cineforge.providers.vault import VaultSecretStore

    return VaultSecretStore(settings.database_url)


def build_provider_settings_repository(settings: Settings) -> ProviderSettingsRepository:
    if settings.persistence_backend == "memory":
        return InMemoryProviderSettingsRepository()
    from cineforge.providers.settings_store import PostgresProviderSettingsRepository

    return PostgresProviderSettingsRepository(settings.database_url)


def anthropic_models(settings: Settings) -> list[str]:
    """Anthropic models priced in the configured catalog(s), ANTHROPIC_MODEL first."""
    from cineforge.cost.factory import load_price_catalog

    priced = [e.model for e in load_price_catalog(settings).entries() if e.provider == "anthropic"]
    return list(dict.fromkeys([settings.anthropic_model, *priced]))


def build_provider_registry(
    settings: Settings,
    *,
    secrets: SecretStore | None = None,
    provider_settings: ProviderSettingsRepository | None = None,
    http_client: httpx.Client | None = None,
) -> ProviderRegistry:
    """Mocks first (so ``for_capability`` stays offline), then real providers; routing
    decides readiness per tenant. ``http_client`` lets tests inject a MockTransport."""
    registry = InMemoryProviderRegistry(
        build_mock_providers(failure_rate=settings.mock_failure_rate),
        settings=settings,
        secrets=secrets,
        provider_settings=provider_settings,
        planned=list(PLANNED_PROVIDERS),
    )
    client = http_client or build_http_client(settings)
    registry.register(
        AnthropicProvider(
            settings,
            key_resolver=lambda tenant_id: registry.resolve_key("anthropic", tenant_id)[0],
            models=anthropic_models(settings),
            client=client,
        )
    )
    registry.register(WikipediaResearchProvider(settings, client=client))
    registry.register(CommonsMediaProvider(settings, client=client))
    registry.register(OpenverseMediaProvider(settings, client=client))
    auth = build_higgsfield_auth(settings, secrets, client) if secrets is not None else None
    registry.register(
        HiggsfieldProvider(
            settings,
            token_for=(lambda t, force: auth.token(t, force)) if auth else (lambda t, f: None),
            http=build_mcp_http_client(settings, transport=_transport(http_client)),
        )
    )
    return registry


def build_higgsfield_auth(
    settings: Settings, secrets: SecretStore, http: httpx.Client | None = None
) -> McpOAuth:
    return McpOAuth(
        provider=HIGGSFIELD,
        resource_url=settings.higgsfield_mcp_url,
        redirect_uri=f"{settings.api_public_url}/api/v1/providers/{HIGGSFIELD}/oauth/callback",
        secrets=secrets,
        http=http or build_http_client(settings),
    )


def build_mcp_http_client(
    settings: Settings, *, transport: httpx.BaseTransport | None = None
) -> httpx.Client:
    """MCP tool calls can hold the connection while a job runs (``sync`` polling)."""
    return httpx.Client(
        timeout=httpx.Timeout(90.0, connect=settings.http_timeout_sec),
        headers={"User-Agent": settings.http_user_agent},
        transport=transport,
        follow_redirects=False,
    )


def _transport(client: httpx.Client | None) -> httpx.BaseTransport | None:
    return client._transport if client is not None else None


def build_paid_call_guard(
    settings: Settings, budget: BudgetService, catalog: PriceCatalog
) -> PaidCallGuard:
    return DefaultPaidCallGuard(settings, budget, catalog)
