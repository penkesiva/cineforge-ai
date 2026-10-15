"""AI/media provider interfaces, provider settings and secrets.

Phase 0 shipped mocks only. Phase 1 adds real providers (Anthropic LLM, Wikipedia
research, Wikimedia Commons and Openverse media search), per-tenant provider settings
(enabled, priority) and write-only API keys behind ``SecretStore``.

Payload conventions (``ProviderRequest.parameters`` / ``ProviderResponse.output_data``):

- LLM structured output: request ``parameters["response_schema"]`` (JSON Schema dict),
  ``parameters["schema_name"]`` and optional ``parameters["system"]``; the response puts
  the parsed object in ``output_data["structured"]`` (absent for mocks/free text).
- Web research: response ``output_data["sources"]`` = list of ``ResearchSource`` dicts.
- Media search: response ``output_data["items"]`` = list of ``MediaSearchItem`` dicts.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import Field

from cineforge.contracts.common import AgentId, ContractModel, utcnow
from cineforge.contracts.media import LicenseInfo

if TYPE_CHECKING:
    from cineforge.contracts.cost import LedgerEvent


class ProviderCapability(StrEnum):
    LLM_TEXT = "llm_text"
    WEB_RESEARCH = "web_research"
    MEDIA_SEARCH = "media_search"
    IMAGE_GENERATION = "image_generation"
    IMAGE_EDIT = "image_edit"
    VIDEO_GENERATION = "video_generation"
    IMAGE_TO_VIDEO = "image_to_video"
    VOICE_TTS = "voice_tts"
    MUSIC_GENERATION = "music_generation"
    SFX_GENERATION = "sfx_generation"
    LIP_SYNC = "lip_sync"
    TRANSCRIPTION = "transcription"
    EMBEDDING = "embedding"


class PriceUnit(StrEnum):
    TOKENS_1K = "1k_tokens"
    INPUT_TOKENS_1K = "1k_input_tokens"
    OUTPUT_TOKENS_1K = "1k_output_tokens"
    CHARACTERS_1K = "1k_characters"
    IMAGE = "image"
    VIDEO_SECOND = "video_second"
    AUDIO_SECOND = "audio_second"
    TRACK = "track"
    REQUEST = "request"
    COMPUTE_SECOND = "compute_second"
    GB_MONTH = "gb_month"
    CREDIT = "credit"


class ProviderInfo(ContractModel):
    name: str
    display_name: str
    capabilities: list[ProviderCapability]
    models: list[str]
    is_mock: bool
    is_paid: bool = Field(description="True if invoking it can incur real spend")
    description: str = ""
    requires_key: bool = False
    key_env_var: str | None = None
    docs_url: str | None = None
    auth_method: Literal["api_key", "oauth"] = Field(
        default="api_key", description="oauth: the stored 'key' is a token set from sign-in"
    )


class ProviderRequest(ContractModel):
    tenant_id: str
    production_id: str
    scene_id: str | None = None
    shot_id: str | None = None
    capability: ProviderCapability
    model: str
    prompt: str | None = None
    negative_prompt: str | None = None
    seed: int | None = None
    reference_asset_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str


class UsageLine(ContractModel):
    unit: PriceUnit
    units: Decimal = Field(ge=0)


class ProviderUsage(ContractModel):
    """``units``/``unit`` is what the ledger records. When ``breakdown`` is set (e.g. input
    vs output tokens) the guard prices each line separately and sums them; ``unit`` is
    then the aggregate unit (``1k_tokens``) and need not be priced itself."""

    units: Decimal = Field(ge=0)
    unit: PriceUnit
    credits: Decimal | None = None
    breakdown: list[UsageLine] = Field(default_factory=list)


class ProviderResponse(ContractModel):
    provider: str
    model: str
    capability: ProviderCapability
    provider_request_id: str
    output_text: str | None = None
    output_data: dict[str, Any] = Field(default_factory=dict)
    output_asset_id: str | None = None
    usage: ProviderUsage
    latency_ms: int = 0
    cached: bool = False


class ProviderError(RuntimeError):
    """Provider call failed. ``retryable`` drives bounded retries."""

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class PaidProviderNotAllowedError(RuntimeError):
    """Raised when a paid provider is invoked without ALLOW_PAID_PROVIDERS=true."""


class UnsupportedCapabilityError(LookupError):
    """No registered provider supports the requested capability."""


class ProviderNotReadyError(UnsupportedCapabilityError):
    """Providers exist for the capability but none is enabled and ready for this tenant
    (disabled, missing key, paid calls off, or PROVIDER_MODE=mock)."""


# --------------------------------------------------------------------------- #
# Typed payloads carried in ProviderResponse.output_data
# --------------------------------------------------------------------------- #
class ResearchSource(ContractModel):
    url: str
    title: str
    publisher: str | None = None
    extract: str = Field(default="", description="Plain-text excerpt the claims may cite")
    published_at: date | None = None
    retrieved_at: datetime = Field(default_factory=utcnow)


class MediaSearchItem(ContractModel):
    provider: str
    media_type: Literal["image", "video", "audio"] = "image"
    title: str
    source_url: str = Field(description="Landing page of the item (not the binary)")
    file_url: str | None = Field(default=None, description="Original file; not downloaded yet")
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    description: str | None = None
    license: LicenseInfo | None = None


# --------------------------------------------------------------------------- #
# Provider catalog, settings and secrets (Sources page)
# --------------------------------------------------------------------------- #
class ProviderStatus(StrEnum):
    READY = "ready"
    MISSING_KEY = "missing_key"
    DISABLED = "disabled"
    BLOCKED_PAID_OFF = "blocked_paid_off"
    BLOCKED_MOCK_MODE = "blocked_mock_mode"
    PLANNED = "planned"


class KeySource(StrEnum):
    NONE = "none"
    ENVIRONMENT = "environment"
    STORED = "stored"


class ProviderSetting(ContractModel):
    """Per-tenant routing preference. Lower ``priority`` wins."""

    tenant_id: str
    provider: str
    enabled: bool
    priority: int = Field(default=100, ge=0, le=1000)
    updated_at: datetime = Field(default_factory=utcnow)


class ProviderCatalogEntry(ContractModel):
    name: str
    display_name: str
    description: str = ""
    capabilities: list[ProviderCapability]
    models: list[str] = Field(default_factory=list)
    is_mock: bool
    is_paid: bool
    requires_key: bool = False
    key_env_var: str | None = None
    docs_url: str | None = None
    auth_method: Literal["api_key", "oauth"] = "api_key"
    planned_phase: str | None = Field(
        default=None, description="Set for providers listed but not implemented yet"
    )
    enabled: bool
    priority: int
    status: ProviderStatus
    status_detail: str = ""
    key_source: KeySource = KeySource.NONE
    key_hint: str | None = Field(default=None, description="e.g. '...a1b2'; never the key")


@runtime_checkable
class Provider(Protocol):
    info: ProviderInfo

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage: ...

    def invoke(self, request: ProviderRequest) -> ProviderResponse: ...


@runtime_checkable
class ProviderRegistry(Protocol):
    def register(self, provider: Provider) -> None: ...

    def get(self, name: str) -> Provider: ...

    def for_capability(self, capability: ProviderCapability) -> Provider:
        """First registered provider for the capability, ignoring tenant settings.
        Raises UnsupportedCapabilityError if none. Prefer ``route``."""
        ...

    def route(self, capability: ProviderCapability, *, tenant_id: str) -> Provider:
        """Highest-priority provider that is enabled and READY for the tenant.
        Raises ProviderNotReadyError / UnsupportedCapabilityError."""
        ...

    def route_all(self, capability: ProviderCapability, *, tenant_id: str) -> list[Provider]:
        """Every READY provider for the capability, best first (federated search)."""
        ...

    def list(self) -> list[ProviderInfo]: ...

    def catalog(self, tenant_id: str) -> list[ProviderCatalogEntry]:
        """Registered + planned providers with tenant settings and readiness."""
        ...


@runtime_checkable
class SecretStore(Protocol):
    """Write-only API key storage. Values are never returned by the API."""

    name: str

    def put(self, tenant_id: str, key_name: str, value: str) -> None: ...

    def get(self, tenant_id: str, key_name: str) -> str | None: ...

    def delete(self, tenant_id: str, key_name: str) -> None: ...


@runtime_checkable
class ProviderSettingsRepository(Protocol):
    def list(self, tenant_id: str) -> list[ProviderSetting]: ...

    def get(self, tenant_id: str, provider: str) -> ProviderSetting | None: ...

    def upsert(self, setting: ProviderSetting) -> ProviderSetting: ...


@runtime_checkable
class PaidCallGuard(Protocol):
    """The ONLY sanctioned way to call a provider.

    Sequence: price lookup -> estimate -> atomic budget reservation -> invoke ->
    commit actual cost (or release/fail the reservation on error). Refuses paid
    providers unless explicitly allowed by configuration.
    """

    def call(
        self,
        provider: Provider,
        request: ProviderRequest,
        *,
        agent_id: AgentId,
        attempt: int = 1,
        retry_reason: str | None = None,
    ) -> tuple[ProviderResponse, LedgerEvent]: ...
