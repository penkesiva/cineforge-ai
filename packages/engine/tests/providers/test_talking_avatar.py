from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest
from cineforge.providers.talking import (
    UNVERIFIED_CANDIDATES,
    AvatarAvailability,
    MockTalkingAvatar,
    TalkingAvatarError,
    TalkingAvatarInputs,
    TalkingAvatarProvider,
    unverified_provider,
)


def _inputs(**overrides: object) -> TalkingAvatarInputs:
    inputs = TalkingAvatarInputs(
        idempotency_key="bench:lena:1",
        image_sha256="a" * 64,
        audio_sha256="b" * 64,
        audio_duration_sec=6.2,
        transcript="Wait, how is this giant stone pillar not touching the floor?",
    )
    if not overrides:
        return inputs
    return replace(inputs, **overrides)  # type: ignore[arg-type]


def test_mock_matches_the_provider_shape() -> None:
    provider = MockTalkingAvatar()
    assert isinstance(provider, TalkingAvatarProvider)
    assert provider.capabilities.availability is AvatarAvailability.READY
    assert provider.capabilities.is_mock is True


def test_mock_quotes_submits_and_keeps_duration() -> None:
    provider = MockTalkingAvatar()
    inputs = _inputs()
    quote = provider.estimate_cost(inputs)
    assert quote.units == Decimal("6.2")
    assert quote.estimated_usd == Decimal("0.6200")

    job = provider.submit_generation(inputs)
    assert job.status == "succeeded"
    assert job.duration_sec == 6.2
    assert provider.submit_generation(inputs).job_id == job.job_id

    raw = provider.download_result(job.job_id)
    normalized = provider.normalize_output(raw)
    assert normalized.duration_sec == raw.duration_sec
    assert normalized.sha256 != raw.sha256
    assert provider.get_usage(job.job_id).estimated_usd == quote.estimated_usd


def test_mock_rejects_a_bad_benchmark_input() -> None:
    provider = MockTalkingAvatar()
    with pytest.raises(TalkingAvatarError, match="voice file"):
        provider.validate_inputs(_inputs(audio_sha256=""))
    with pytest.raises(TalkingAvatarError, match="aspect ratio"):
        provider.validate_inputs(_inputs(aspect_ratio="16:9"))
    with pytest.raises(TalkingAvatarError, match="longer"):
        provider.validate_inputs(_inputs(audio_duration_sec=30))


def test_driving_video_is_required_when_the_model_says_so() -> None:
    caps = MockTalkingAvatar().capabilities
    provider = MockTalkingAvatar(replace(caps, requires_driving_video=True, model="needs-driver"))
    with pytest.raises(TalkingAvatarError, match="driving"):
        provider.validate_inputs(_inputs())
    ok = _inputs(driving_video_sha256="c" * 64)
    assert provider.submit_generation(ok).status == "succeeded"


def test_failed_submit_is_retryable_and_has_no_file() -> None:
    provider = MockTalkingAvatar(fail_keys=frozenset({"bench:lena:1"}))
    job = provider.submit_generation(_inputs())
    assert job.status == "failed" and job.retryable is True
    with pytest.raises(TalkingAvatarError, match="no output"):
        provider.download_result(job.job_id)


def test_unknown_job_is_an_error() -> None:
    with pytest.raises(TalkingAvatarError, match="unknown job"):
        MockTalkingAvatar().get_generation_status("missing")


def test_unverified_candidates_refuse_to_run() -> None:
    names = {c.provider for c in UNVERIFIED_CANDIDATES}
    assert names == {"heygen", "runway", "higgsfield"}
    for name in names:
        provider = unverified_provider(name)
        assert provider.capabilities.supports_external_audio is None
        with pytest.raises(TalkingAvatarError, match="not available"):
            provider.submit_generation(_inputs())
