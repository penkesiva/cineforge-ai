"""Talking-avatar benchmark providers.

This is not the Lepakshi production path. Talking shots there still go through
Higgsfield ``wan2_7``. Adapters here are for a side-by-side lip-sync test.

A provider must say what it accepts before anyone pays for a clip. Unknown
capabilities stay unknown. Unverified candidates refuse to submit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Protocol, runtime_checkable

from cineforge.contracts.providers import PriceUnit, ProviderError

JobStatus = Literal["queued", "running", "succeeded", "failed"]


class AvatarAvailability(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"


class AudioOutput(StrEnum):
    PASSTHROUGH = "passthrough"
    GENERATED = "generated"
    UNKNOWN = "unknown"


class TalkingAvatarError(ProviderError):
    """Input or provider failure. ``retryable`` is only for a lost poll or a timeout."""


@dataclass(frozen=True)
class TalkingAvatarCapabilities:
    """What one model can do. ``None`` means we have not verified it yet."""

    provider: str
    model: str
    availability: AvatarAvailability
    supports_external_audio: bool | None
    requires_driving_video: bool | None
    supports_image_reference: bool | None
    aspect_ratios: tuple[str, ...]
    duration_min_sec: float | None
    duration_max_sec: float | None
    resolutions: tuple[str, ...]
    audio_output: AudioOutput
    pricing_unit: PriceUnit
    unit_price: Decimal
    is_mock: bool = False
    notes: str = ""


@dataclass(frozen=True)
class TalkingAvatarInputs:
    """Hashes of the shared benchmark files, not the files themselves."""

    idempotency_key: str
    image_sha256: str
    audio_sha256: str
    audio_duration_sec: float
    aspect_ratio: str = "9:16"
    resolution: str = "1080x1920"
    driving_video_sha256: str | None = None
    transcript: str = ""


@dataclass(frozen=True)
class TalkingAvatarUsage:
    units: Decimal
    unit: PriceUnit
    estimated_usd: Decimal


@dataclass
class TalkingAvatarJob:
    job_id: str
    provider: str
    model: str
    status: JobStatus
    idempotency_key: str
    duration_sec: float
    error: str | None = None
    retryable: bool = False
    output_sha256: str | None = None
    speed_changed: bool = False


@dataclass(frozen=True)
class TalkingAvatarResult:
    job_id: str
    raw: bytes
    duration_sec: float
    sha256: str


# Not verified against vendor docs. They cannot be called.
UNVERIFIED_CANDIDATES: tuple[TalkingAvatarCapabilities, ...] = (
    TalkingAvatarCapabilities(
        provider="heygen",
        model="avatar-iv",
        availability=AvatarAvailability.UNAVAILABLE,
        supports_external_audio=None,
        requires_driving_video=None,
        supports_image_reference=None,
        aspect_ratios=(),
        duration_min_sec=None,
        duration_max_sec=None,
        resolutions=(),
        audio_output=AudioOutput.UNKNOWN,
        pricing_unit=PriceUnit.VIDEO_SECOND,
        unit_price=Decimal("0"),
        notes="Docs not checked. No adapter, no calls.",
    ),
    TalkingAvatarCapabilities(
        provider="runway",
        model="act-two",
        availability=AvatarAvailability.UNAVAILABLE,
        supports_external_audio=None,
        requires_driving_video=None,
        supports_image_reference=None,
        aspect_ratios=(),
        duration_min_sec=None,
        duration_max_sec=None,
        resolutions=(),
        audio_output=AudioOutput.UNKNOWN,
        pricing_unit=PriceUnit.VIDEO_SECOND,
        unit_price=Decimal("0"),
        notes="Needs a driving performance. Blocked until that file exists. No adapter.",
    ),
    TalkingAvatarCapabilities(
        provider="higgsfield",
        model="lip-sync",
        availability=AvatarAvailability.UNAVAILABLE,
        supports_external_audio=None,
        requires_driving_video=None,
        supports_image_reference=None,
        aspect_ratios=(),
        duration_min_sec=None,
        duration_max_sec=None,
        resolutions=(),
        audio_output=AudioOutput.UNKNOWN,
        pricing_unit=PriceUnit.CREDIT,
        unit_price=Decimal("0"),
        notes="No dedicated lip-sync tool in the connector. wan2_7 is not this candidate.",
    ),
)


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


@runtime_checkable
class TalkingAvatarProvider(Protocol):
    capabilities: TalkingAvatarCapabilities

    def validate_inputs(self, inputs: TalkingAvatarInputs) -> None: ...

    def estimate_cost(self, inputs: TalkingAvatarInputs) -> TalkingAvatarUsage: ...

    def submit_generation(self, inputs: TalkingAvatarInputs) -> TalkingAvatarJob: ...

    def get_generation_status(self, job_id: str) -> TalkingAvatarJob: ...

    def download_result(self, job_id: str) -> TalkingAvatarResult: ...

    def normalize_output(self, result: TalkingAvatarResult) -> TalkingAvatarResult: ...

    def get_usage(self, job_id: str) -> TalkingAvatarUsage: ...


class MockTalkingAvatar:
    """Deterministic stand-in. Same idempotency key always returns the same job.

    ``fail_job_ids`` marks those submissions as failed after submit, so tests can
    cover a provider error without a network call.
    """

    def __init__(
        self,
        capabilities: TalkingAvatarCapabilities | None = None,
        *,
        fail_keys: frozenset[str] = frozenset(),
    ) -> None:
        self.capabilities = capabilities or TalkingAvatarCapabilities(
            provider="mock-talking",
            model="mock-avatar-v1",
            availability=AvatarAvailability.READY,
            supports_external_audio=True,
            requires_driving_video=False,
            supports_image_reference=True,
            aspect_ratios=("9:16",),
            duration_min_sec=1.0,
            duration_max_sec=20.0,
            resolutions=("1080x1920",),
            audio_output=AudioOutput.PASSTHROUGH,
            pricing_unit=PriceUnit.VIDEO_SECOND,
            unit_price=Decimal("0.10"),
            is_mock=True,
            notes="Test double. Does not render a picture.",
        )
        self._fail_keys = fail_keys
        self._jobs: dict[str, TalkingAvatarJob] = {}
        self._by_key: dict[str, str] = {}

    def validate_inputs(self, inputs: TalkingAvatarInputs) -> None:
        caps = self.capabilities
        if caps.availability is not AvatarAvailability.READY:
            raise TalkingAvatarError(f"{caps.provider}/{caps.model} is not available")
        if not inputs.image_sha256:
            raise TalkingAvatarError("character image is required")
        if caps.supports_external_audio and not inputs.audio_sha256:
            raise TalkingAvatarError("approved voice file is required")
        if caps.requires_driving_video and not inputs.driving_video_sha256:
            raise TalkingAvatarError("driving performance video is required")
        if caps.aspect_ratios and inputs.aspect_ratio not in caps.aspect_ratios:
            raise TalkingAvatarError(f"aspect ratio {inputs.aspect_ratio} is not supported")
        if caps.resolutions and inputs.resolution not in caps.resolutions:
            raise TalkingAvatarError(f"resolution {inputs.resolution} is not supported")
        duration = inputs.audio_duration_sec
        if duration <= 0:
            raise TalkingAvatarError("audio duration must be positive")
        if caps.duration_min_sec is not None and duration < caps.duration_min_sec:
            raise TalkingAvatarError(f"audio is shorter than {caps.duration_min_sec}s")
        if caps.duration_max_sec is not None and duration > caps.duration_max_sec:
            raise TalkingAvatarError(f"audio is longer than {caps.duration_max_sec}s")

    def estimate_cost(self, inputs: TalkingAvatarInputs) -> TalkingAvatarUsage:
        self.validate_inputs(inputs)
        units = Decimal(str(inputs.audio_duration_sec))
        return TalkingAvatarUsage(
            units=units,
            unit=self.capabilities.pricing_unit,
            estimated_usd=(units * self.capabilities.unit_price).quantize(Decimal("0.0001")),
        )

    def submit_generation(self, inputs: TalkingAvatarInputs) -> TalkingAvatarJob:
        self.validate_inputs(inputs)
        existing = self._by_key.get(inputs.idempotency_key)
        if existing is not None:
            return self._jobs[existing]
        job_id = _sha256(f"{self.capabilities.provider}:{inputs.idempotency_key}".encode())[:16]
        failed = inputs.idempotency_key in self._fail_keys
        job = TalkingAvatarJob(
            job_id=job_id,
            provider=self.capabilities.provider,
            model=self.capabilities.model,
            status="failed" if failed else "succeeded",
            idempotency_key=inputs.idempotency_key,
            duration_sec=inputs.audio_duration_sec,
            error="mock provider failure" if failed else None,
            retryable=failed,
        )
        if not failed:
            raw = self._raw(job_id, inputs.audio_duration_sec)
            job.output_sha256 = _sha256(raw)
        self._jobs[job_id] = job
        self._by_key[inputs.idempotency_key] = job_id
        return job

    def get_generation_status(self, job_id: str) -> TalkingAvatarJob:
        job = self._jobs.get(job_id)
        if job is None:
            raise TalkingAvatarError(f"unknown job {job_id}")
        return job

    def download_result(self, job_id: str) -> TalkingAvatarResult:
        job = self.get_generation_status(job_id)
        if job.status != "succeeded" or job.output_sha256 is None:
            raise TalkingAvatarError(f"job {job_id} has no output ({job.status})")
        raw = self._raw(job_id, job.duration_sec)
        return TalkingAvatarResult(
            job_id=job_id, raw=raw, duration_sec=job.duration_sec, sha256=_sha256(raw)
        )

    def normalize_output(self, result: TalkingAvatarResult) -> TalkingAvatarResult:
        """Inspection copy. Speech speed is unchanged, so the duration stays put."""
        stamped = b"normalized:9:16:1080x1920:30fps:h264:aac:" + result.raw
        return TalkingAvatarResult(
            job_id=result.job_id,
            raw=stamped,
            duration_sec=result.duration_sec,
            sha256=_sha256(stamped),
        )

    def get_usage(self, job_id: str) -> TalkingAvatarUsage:
        job = self.get_generation_status(job_id)
        units = Decimal(str(job.duration_sec))
        return TalkingAvatarUsage(
            units=units,
            unit=self.capabilities.pricing_unit,
            estimated_usd=(units * self.capabilities.unit_price).quantize(Decimal("0.0001")),
        )

    @staticmethod
    def _raw(job_id: str, duration: float) -> bytes:
        return f"mock-talking:{job_id}:{duration:.3f}".encode()


def unverified_provider(name: str) -> MockTalkingAvatar:
    caps = next(c for c in UNVERIFIED_CANDIDATES if c.provider == name)
    return MockTalkingAvatar(caps)
