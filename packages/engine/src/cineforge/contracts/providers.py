"""AI/media provider interfaces. Phase 0 ships mock implementations only."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import Field

from cineforge.contracts.common import AgentId, ContractModel

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


class ProviderUsage(ContractModel):
    units: Decimal = Field(ge=0)
    unit: PriceUnit
    credits: Decimal | None = None


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
        """Route to a provider. Raises UnsupportedCapabilityError if none."""
        ...

    def list(self) -> list[ProviderInfo]: ...


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
