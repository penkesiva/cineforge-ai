"""Shared, deterministic sample data for tests and fixtures in every workstream."""

from __future__ import annotations

from datetime import UTC, datetime

from cineforge.contracts.common import DEMO_TENANT_ID, GenerationStrategy, ProductionMode, money
from cineforge.contracts.manifest import (
    AudioSpec,
    BudgetSnapshot,
    CreativeBrief,
    Disclosure,
    PerformanceSpec,
    ProductionManifest,
    ProviderPlan,
    Scene,
    Shot,
    ThemeRef,
    VisualSpec,
)
from cineforge.contracts.providers import ProviderCapability

SAMPLE_PRODUCTION_ID = "prod_sample0000000001"
SAMPLE_TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"
_FIXED_TIME = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)

_SCENES = [
    ("Hook", "opening hook", 7.0, "close_up", "slow_push", True),
    ("Arrival", "arrival", 9.0, "wide", "drone_reveal", False),
    ("Context", "context", 10.0, "medium", "tracking", False),
    ("Reveal", "reveal", 11.0, "wide", "tilt_up", True),
    ("Legacy", "legacy and call-to-action", 8.0, "medium", "slow_pull", False),
]


def sample_manifest(
    *,
    production_id: str = SAMPLE_PRODUCTION_ID,
    tenant_id: str = DEMO_TENANT_ID,
    with_scenes: bool = True,
    budget_limit: float = 10.0,
) -> ProductionManifest:
    """45-second, 5-scene Time Traveler manifest (the PRD 3 MVP shape)."""
    scenes: list[Scene] = []
    if with_scenes:
        for idx, (title, beat, duration, shot_type, motion, generative) in enumerate(_SCENES, 1):
            scene_id = f"scene_{idx:02d}"
            half = round(duration / 2, 2)
            kind = "reconstruction" if generative else "detail"
            shots = [
                Shot(
                    id=f"{scene_id}_shot_01",
                    order=1,
                    duration_sec=half,
                    description=f"{title}: establishing visual",
                    visual=VisualSpec(
                        shot_type="wide", camera_motion="ken_burns", lighting="golden_hour"
                    ),
                    provider_plan=ProviderPlan(
                        strategy=GenerationStrategy.LICENSED_STILL_MOTION,
                        capability=ProviderCapability.IMAGE_TO_VIDEO,
                        provider="mock-video",
                        model="mock-video-draft",
                    ),
                ),
                Shot(
                    id=f"{scene_id}_shot_02",
                    order=2,
                    duration_sec=round(duration - half, 2),
                    description=f"{title}: cinematic {kind}",
                    visual=VisualSpec(
                        shot_type=shot_type, camera_motion=motion, atmosphere="light_haze"
                    ),
                    performance=PerformanceSpec(
                        character_ref="asset://characters/host-v1" if idx == 1 else None,
                        emotion="curious" if idx == 1 else None,
                        lip_sync_required=idx == 1,
                    ),
                    audio=AudioSpec(narration_text=f"Narration for {title.lower()}."),
                    provider_plan=ProviderPlan(
                        strategy=(
                            GenerationStrategy.GENERATIVE
                            if generative
                            else GenerationStrategy.LICENSED_STILL_MOTION
                        ),
                        capability=(
                            ProviderCapability.VIDEO_GENERATION
                            if generative
                            else ProviderCapability.IMAGE_TO_VIDEO
                        ),
                        provider="mock-video",
                        model="mock-video-cinematic" if generative else "mock-video-draft",
                    ),
                    disclosure=Disclosure(
                        synthetic_media=generative,
                        reconstruction=generative,
                        label_text="Reconstruction" if generative else None,
                    ),
                    depends_on=[f"{scene_id}_shot_01"],
                ),
            ]
            scenes.append(
                Scene(
                    id=scene_id,
                    order=idx,
                    title=title,
                    duration_sec=duration,
                    story_beat=beat,
                    narration=f"Narration for {title.lower()}.",
                    facts=[f"claim_{idx:02d}"],
                    shots=shots,
                )
            )
    return ProductionManifest(
        production_id=production_id,
        tenant_id=tenant_id,
        title="Eiffel Tower, 1889",
        theme_profile=ThemeRef(id="time-traveler", version=1),
        mode=ProductionMode.BALANCED,
        creative_brief=CreativeBrief(topic=SAMPLE_TOPIC, genre="documentary-adventure"),
        budget=BudgetSnapshot(limit=money(budget_limit)),
        character_bible_ref="asset://characters/host-v1",
        scenes=scenes,
        created_at=_FIXED_TIME,
        updated_at=_FIXED_TIME,
    )
