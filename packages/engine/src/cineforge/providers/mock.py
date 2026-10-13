"""Deterministic mock providers (Phase 0). No network, no spend, no sleeping.

Every output is a pure function of the request: usage, request id, text and
failure injection are seeded from ``request.idempotency_key`` via SHA-256, so a
retried attempt (new key) may succeed while replaying the same key never changes.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal

from cineforge.contracts.common import money
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderInfo,
    ProviderRequest,
    ProviderResponse,
    ProviderUsage,
)

C = ProviderCapability

UNIT_FOR_CAPABILITY: dict[ProviderCapability, PriceUnit] = {
    C.LLM_TEXT: PriceUnit.TOKENS_1K,
    C.WEB_RESEARCH: PriceUnit.REQUEST,
    C.MEDIA_SEARCH: PriceUnit.REQUEST,
    C.IMAGE_GENERATION: PriceUnit.IMAGE,
    C.IMAGE_EDIT: PriceUnit.IMAGE,
    C.VIDEO_GENERATION: PriceUnit.VIDEO_SECOND,
    C.IMAGE_TO_VIDEO: PriceUnit.VIDEO_SECOND,
    C.VOICE_TTS: PriceUnit.CHARACTERS_1K,
    C.MUSIC_GENERATION: PriceUnit.TRACK,
    C.SFX_GENERATION: PriceUnit.REQUEST,
    C.LIP_SYNC: PriceUnit.VIDEO_SECOND,
}
# Capabilities whose mock calls can fail when MOCK_FAILURE_RATE > 0.
MEDIA_CAPABILITIES = frozenset(
    {C.IMAGE_GENERATION, C.IMAGE_EDIT, C.VIDEO_GENERATION, C.IMAGE_TO_VIDEO, C.LIP_SYNC}
)
# Continuous units vary slightly between estimate and actual; counted units do not.
VARIABLE_UNITS = frozenset(
    {PriceUnit.TOKENS_1K, PriceUnit.CHARACTERS_1K, PriceUnit.VIDEO_SECOND, PriceUnit.AUDIO_SECOND}
)
ACTUAL_FACTOR_MIN = Decimal("0.90")
ACTUAL_FACTOR_MAX = Decimal("1.05")
DEFAULT_MAX_TOKENS = 800


@dataclass(frozen=True)
class MockSpec:
    name: str
    display_name: str
    capabilities: tuple[ProviderCapability, ...]
    models: tuple[str, ...]
    credits_per_unit: Decimal


# Mirrors packages/configurations/pricing/mock-2026-10.yaml (test-enforced).
MOCK_SPECS: tuple[MockSpec, ...] = (
    MockSpec("mock-llm", "Mock LLM", (C.LLM_TEXT,),
             ("mock-llm-standard", "mock-llm-premium"), Decimal("1")),
    MockSpec("mock-research", "Mock Web Research", (C.WEB_RESEARCH,),
             ("mock-search-v1",), Decimal("1")),
    MockSpec("mock-media-search", "Mock Media Search", (C.MEDIA_SEARCH,),
             ("mock-media-v1",), Decimal("1")),
    MockSpec("mock-image", "Mock Image Generator", (C.IMAGE_GENERATION,),
             ("mock-image-v1",), Decimal("4")),
    MockSpec("mock-video", "Mock Video Generator", (C.IMAGE_TO_VIDEO, C.VIDEO_GENERATION),
             ("mock-video-draft", "mock-video-cinematic"), Decimal("10")),
    MockSpec("mock-voice", "Mock Voice (TTS)", (C.VOICE_TTS,), ("mock-tts-v1",), Decimal("2")),
    MockSpec("mock-music", "Mock Music", (C.MUSIC_GENERATION,), ("mock-music-v1",), Decimal("5")),
    MockSpec("mock-sfx", "Mock SFX", (C.SFX_GENERATION,), ("mock-sfx-v1",), Decimal("1")),
    MockSpec("mock-lipsync", "Mock Lip-Sync", (C.LIP_SYNC,), ("mock-lipsync-v1",), Decimal("8")),
)  # fmt: skip


def unit_fraction(*parts: str) -> Decimal:
    """Deterministic value in [0, 1) derived from the parts."""
    digest = hashlib.sha256(":".join(parts).encode()).digest()
    return Decimal(int.from_bytes(digest[:8], "big")) / Decimal(2**64)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class MockProvider:
    def __init__(self, spec: MockSpec, *, failure_rate: float = 0.0) -> None:
        self.spec = spec
        self.failure_rate = Decimal(str(failure_rate))
        self.info = ProviderInfo(
            name=spec.name,
            display_name=spec.display_name,
            capabilities=list(spec.capabilities),
            models=list(spec.models),
            is_mock=True,
            is_paid=False,
        )

    def _validate(self, request: ProviderRequest) -> None:
        if request.capability not in self.spec.capabilities:
            raise ProviderError(
                f"{self.spec.name} does not support {request.capability}", retryable=False
            )
        if request.model not in self.spec.models:
            raise ProviderError(f"{self.spec.name} has no model {request.model!r}", retryable=False)

    def estimate_usage(self, request: ProviderRequest) -> ProviderUsage:
        self._validate(request)
        unit = UNIT_FOR_CAPABILITY[request.capability]
        units = money(self._estimated_units(request))
        return ProviderUsage(units=units, unit=unit, credits=self._credits(units))

    def _estimated_units(self, request: ProviderRequest) -> Decimal:
        params = request.parameters
        cap = request.capability
        if cap == C.LLM_TEXT:
            tokens = len(request.prompt or "") // 4 + int(
                params.get("max_tokens", DEFAULT_MAX_TOKENS)
            )
            return Decimal(tokens) / 1000
        if cap == C.VOICE_TTS:
            return Decimal(len(request.prompt or "")) / 1000
        if cap in (C.VIDEO_GENERATION, C.IMAGE_TO_VIDEO, C.LIP_SYNC):
            if "duration_sec" not in params:
                raise ProviderError(f"{cap} requires parameters['duration_sec']", retryable=False)
            return Decimal(str(params["duration_sec"]))
        return Decimal(str(params.get("count", 1)))

    def _credits(self, units: Decimal) -> Decimal:
        return money(units * self.spec.credits_per_unit)

    def invoke(self, request: ProviderRequest) -> ProviderResponse:
        estimate = self.estimate_usage(request)
        key = request.idempotency_key
        if (
            self.failure_rate > 0
            and request.capability in MEDIA_CAPABILITIES
            and unit_fraction(key, "fail") < self.failure_rate
        ):
            raise ProviderError(
                f"{self.spec.name}: simulated transient failure for {key}", retryable=True
            )
        units = estimate.units
        if estimate.unit in VARIABLE_UNITS:
            span = ACTUAL_FACTOR_MAX - ACTUAL_FACTOR_MIN
            factor = ACTUAL_FACTOR_MIN + span * unit_fraction(key, "usage")
            units = money(units * factor)
        digest = _digest(f"{self.spec.name}:{request.model}:{key}")
        return ProviderResponse(
            provider=self.spec.name,
            model=request.model,
            capability=request.capability,
            provider_request_id=f"mockreq_{digest[:20]}",
            output_text=f"[{self.spec.name}/{request.model}] mock {request.capability} "
            f"output {digest[:8]}",
            output_data={
                "mock": True,
                "seed": int(digest[:8], 16),
                "capability": request.capability.value,
            },
            usage=ProviderUsage(units=units, unit=estimate.unit, credits=self._credits(units)),
            latency_ms=0,
            cached=False,
        )


def build_mock_providers(*, failure_rate: float = 0.0) -> list[MockProvider]:
    return [MockProvider(spec, failure_rate=failure_rate) for spec in MOCK_SPECS]
