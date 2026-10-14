from __future__ import annotations

from decimal import Decimal

import pytest
from cineforge.config import Settings
from cineforge.configuration import load_mode_policies
from cineforge.contracts.common import AgentId, GenerationStrategy, ProductionMode
from cineforge.contracts.cost import CostEstimator, UnknownPriceError
from cineforge.contracts.manifest import ProductionManifest, ProviderPlan
from cineforge.contracts.providers import ProviderCapability as C
from cineforge.contracts.theme import ProductionModePolicy
from cineforge.cost.factory import build_cost_estimator, load_price_catalog
from cineforge.testing import sample_manifest

SETTINGS = Settings()
POLICIES = load_mode_policies(SETTINGS.configurations_dir)


@pytest.fixture
def estimator() -> CostEstimator:
    return build_cost_estimator(SETTINGS, load_price_catalog(SETTINGS))


def _with_strategy(
    manifest: ProductionManifest, strategy: GenerationStrategy
) -> ProductionManifest:
    m = manifest.model_copy(deep=True)
    for shot in m.iter_shots():
        if strategy == GenerationStrategy.GENERATIVE:
            shot.provider_plan = ProviderPlan(
                strategy=strategy,
                capability=C.VIDEO_GENERATION,
                provider="mock-video",
                model="mock-video-cinematic",
            )
        else:
            shot.provider_plan = ProviderPlan(
                strategy=strategy,
                capability=C.IMAGE_TO_VIDEO,
                provider="mock-video",
                model="mock-video-draft",
            )
    return m


def test_balanced_sample_estimate(estimator: CostEstimator) -> None:
    manifest = sample_manifest()
    est = estimator.estimate(manifest, POLICIES[ProductionMode.BALANCED])
    assert Decimal(0) < est.total_estimated < manifest.budget.limit
    assert set(est.by_scene) == {s.id for s in manifest.scenes}
    assert len(est.by_scene) == 5
    assert est.price_catalog_version.split("+")[0] == "mock-2026-10"
    assert est.mode == ProductionMode.BALANCED
    assert sum(est.by_agent.values()) == est.total_estimated
    assert sum(i.estimated_cost for i in est.line_items) == est.total_estimated
    scene_items = sum(i.estimated_cost for i in est.line_items if i.scene_id)
    assert sum(est.by_scene.values()) == scene_items
    keys = [i.key for i in est.line_items]
    assert len(keys) == len(set(keys))
    agents = {i.agent_id for i in est.line_items}
    assert {AgentId.MASTER_ORCHESTRATOR, AgentId.RESEARCH, AgentId.MEDIA_DISCOVERY,
            AgentId.CREATIVE_DIRECTOR, AgentId.SCRIPTWRITER, AgentId.SCENE_DIRECTOR,
            AgentId.VISUAL_PRODUCTION, AgentId.AUDIO_PERFORMANCE,
            AgentId.EDITOR_QC} <= agents  # fmt: skip


def test_line_item_details(estimator: CostEstimator) -> None:
    manifest = sample_manifest()
    est = estimator.estimate(manifest, POLICIES[ProductionMode.BALANCED])
    by_key = {i.key: i for i in est.line_items}
    gen = by_key["scene_01/scene_01_shot_02/a7_visual_production/video_generation"]
    assert gen.quantity == Decimal("3.5")
    assert gen.unit_price == Decimal("0.25")
    assert gen.expected_attempts == Decimal("1.2")
    assert gen.estimated_cost == Decimal("1.05")
    lip = by_key["scene_01/scene_01_shot_02/a8_audio_performance/lip_sync"]
    assert lip.quantity == Decimal("3.5")
    # Licensed-still-motion shots add one media search each (8 in the sample).
    searches = [i for i in est.line_items if i.capability == C.MEDIA_SEARCH and i.shot_id]
    assert len(searches) == 8
    assert sum(1 for i in est.line_items if i.capability == C.MUSIC_GENERATION) == 1
    assert sum(1 for i in est.line_items if i.capability == C.VOICE_TTS) == 5
    research = by_key["a2_research/web_research"]
    assert research.quantity == 3


def test_retries_multiply_generation_items(estimator: CostEstimator) -> None:
    manifest = sample_manifest()
    base = POLICIES[ProductionMode.BALANCED]
    no_retry = estimator.estimate(manifest, base.model_copy(update={"expected_retry_rate": 0.0}))
    retry = estimator.estimate(manifest, base.model_copy(update={"expected_retry_rate": 0.5}))
    a = {i.key: i for i in no_retry.line_items}
    for item in retry.line_items:
        if item.capability in {
            C.VIDEO_GENERATION,
            C.IMAGE_TO_VIDEO,
            C.LIP_SYNC,
            C.MUSIC_GENERATION,
        }:
            assert item.expected_attempts == Decimal("1.5")
            assert item.estimated_cost == pytest.approx(
                a[item.key].estimated_cost * 3 / 2, abs=1e-6
            )
        if item.capability in {C.LLM_TEXT, C.WEB_RESEARCH, C.MEDIA_SEARCH}:
            assert item.estimated_cost == a[item.key].estimated_cost
    assert retry.total_estimated > no_retry.total_estimated


def test_modes_are_ordered(estimator: CostEstimator) -> None:
    sample = sample_manifest()
    economy = estimator.estimate(
        _with_strategy(sample, GenerationStrategy.LICENSED_STILL_MOTION),
        POLICIES[ProductionMode.ECONOMY],
    )
    balanced = estimator.estimate(sample, POLICIES[ProductionMode.BALANCED])
    premium = estimator.estimate(
        _with_strategy(sample, GenerationStrategy.GENERATIVE), POLICIES[ProductionMode.PREMIUM]
    )
    assert economy.total_estimated < balanced.total_estimated < premium.total_estimated
    assert economy.total_estimated < POLICIES[ProductionMode.ECONOMY].default_budget_usd
    assert premium.total_estimated < POLICIES[ProductionMode.PREMIUM].default_budget_usd

    # Same manifest: retry rate and LLM tier alone still order the modes.
    same = [estimator.estimate(sample, POLICIES[m]).total_estimated for m in ProductionMode]
    assert same[0] < same[1] < same[2]


def test_unassigned_plan_uses_default_route_and_reuse_is_free(estimator: CostEstimator) -> None:
    m = sample_manifest()
    shots = list(m.iter_shots())
    shots[0].provider_plan = ProviderPlan(strategy=GenerationStrategy.GENERATIVE)
    shots[1].provider_plan = ProviderPlan(strategy=GenerationStrategy.REUSE)
    est = estimator.estimate(m, POLICIES[ProductionMode.BALANCED])
    first = [i for i in est.line_items if i.shot_id == shots[0].id]
    assert [(i.provider, i.model) for i in first] == [("mock-video", "mock-video-cinematic")]
    assert not [
        i for i in est.line_items if i.shot_id == shots[1].id and i.agent_id.value.startswith("a7")
    ]


def test_empty_narration_falls_back_to_duration(estimator: CostEstimator) -> None:
    m = sample_manifest()
    for scene in m.scenes:
        scene.narration = None
        for shot in scene.shots:
            shot.audio.narration_text = None
    est = estimator.estimate(m, POLICIES[ProductionMode.BALANCED])
    tts = {i.scene_id: i for i in est.line_items if i.capability == C.VOICE_TTS}
    assert tts["scene_01"].quantity == Decimal("0.105")  # 7 s x 15 chars/s


def test_unknown_price_in_plan_raises(estimator: CostEstimator) -> None:
    m = sample_manifest()
    next(m.iter_shots()).provider_plan = ProviderPlan(
        strategy=GenerationStrategy.GENERATIVE,
        capability=C.VIDEO_GENERATION,
        provider="real-vendor",
        model="v9",
    )
    with pytest.raises(UnknownPriceError):
        estimator.estimate(m, POLICIES[ProductionMode.BALANCED])


def test_manifest_without_scenes(estimator: CostEstimator) -> None:
    est = estimator.estimate(sample_manifest(with_scenes=False), POLICIES[ProductionMode.BALANCED])
    assert est.by_scene == {}
    assert est.total_estimated > 0


def test_policy_type() -> None:
    assert isinstance(POLICIES[ProductionMode.BALANCED], ProductionModePolicy)
