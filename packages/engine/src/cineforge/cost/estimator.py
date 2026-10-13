"""Deterministic preflight cost estimate (per shot, scene, agent) from a manifest.

Pricing rules (Phase 0, mock catalog):

- Shot visuals (A7): ``shot.provider_plan`` capability/provider/model; video
  capabilities priced per ``video_second`` x shot duration, images per image.
  Unassigned plans fall back to a default route for the shot's strategy.
- Licensed-still-motion shots (A3): one ``media_search`` request each.
- Lip-sync (A8): per second of shot duration when ``performance.lip_sync_required``.
- Narration (A8): ``voice_tts`` per 1k characters of the scene narration (or the
  joined shot narration); ~15 characters/second of scene duration if empty.
- Music (A8): one ``music_generation`` track per production.
- Planning/review LLM allowances (A1, A2, A4, A5, A6, A9) plus A2 web research
  and A3 production-level media searches.

Generation and audio items carry ``expected_attempts = 1 + expected_retry_rate``.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from cineforge.contracts.common import AgentId, GenerationStrategy, money
from cineforge.contracts.cost import CostEstimate, CostLineItem, PriceCatalog
from cineforge.contracts.manifest import ProductionManifest, Scene, Shot
from cineforge.contracts.providers import PriceUnit, ProviderCapability
from cineforge.contracts.theme import ProductionModePolicy

C = ProviderCapability

LLM_PROVIDER = "mock-llm"
LLM_MODEL_STANDARD = "mock-llm-standard"
LLM_MODEL_PREMIUM = "mock-llm-premium"
RESEARCH_ROUTE = ("mock-research", "mock-search-v1")
MEDIA_SEARCH_ROUTE = ("mock-media-search", "mock-media-v1")
TTS_ROUTE = ("mock-voice", "mock-tts-v1")
MUSIC_ROUTE = ("mock-music", "mock-music-v1")
LIP_SYNC_ROUTE = ("mock-lipsync", "mock-lipsync-v1")

# Token allowance (input + output) per planning/review agent call.
LLM_TOKEN_ALLOWANCE: dict[AgentId, int] = {
    AgentId.MASTER_ORCHESTRATOR: 1500,
    AgentId.RESEARCH: 3000,
    AgentId.CREATIVE_DIRECTOR: 2000,
    AgentId.SCRIPTWRITER: 4000,
    AgentId.SCENE_DIRECTOR: 3000,
    AgentId.EDITOR_QC: 2500,
}
RESEARCH_REQUESTS = 3
DISCOVERY_SEARCH_REQUESTS = 2
NARRATION_CHARS_PER_SEC = 15

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
VIDEO_CAPABILITIES = frozenset({C.VIDEO_GENERATION, C.IMAGE_TO_VIDEO, C.LIP_SYNC})

# Default visual route when A6 left the provider plan unassigned.
DEFAULT_VISUAL_ROUTE: dict[GenerationStrategy, tuple[ProviderCapability, str, str] | None] = {
    GenerationStrategy.LICENSED_STILL_MOTION: (C.IMAGE_TO_VIDEO, "mock-video", "mock-video-draft"),
    GenerationStrategy.HYBRID: (C.IMAGE_TO_VIDEO, "mock-video", "mock-video-draft"),
    GenerationStrategy.GENERATIVE: (C.VIDEO_GENERATION, "mock-video", "mock-video-cinematic"),
    GenerationStrategy.REUSE: None,
}


class DefaultCostEstimator:
    def __init__(self, catalog: PriceCatalog) -> None:
        self.catalog = catalog

    def estimate(
        self, manifest: ProductionManifest, mode_policy: ProductionModePolicy
    ) -> CostEstimate:
        retry_attempts = Decimal(1) + Decimal(str(mode_policy.expected_retry_rate))
        llm_model = LLM_MODEL_PREMIUM if mode_policy.quality_tier == "high" else LLM_MODEL_STANDARD
        items: list[CostLineItem] = []

        for agent_id, tokens in LLM_TOKEN_ALLOWANCE.items():
            items.append(
                self._item(
                    agent_id=agent_id,
                    capability=C.LLM_TEXT,
                    provider=LLM_PROVIDER,
                    model=llm_model,
                    quantity=Decimal(tokens) / 1000,
                )
            )
        items.append(
            self._item(
                agent_id=AgentId.RESEARCH,
                capability=C.WEB_RESEARCH,
                provider=RESEARCH_ROUTE[0],
                model=RESEARCH_ROUTE[1],
                quantity=Decimal(RESEARCH_REQUESTS),
            )
        )
        items.append(
            self._item(
                agent_id=AgentId.MEDIA_DISCOVERY,
                capability=C.MEDIA_SEARCH,
                provider=MEDIA_SEARCH_ROUTE[0],
                model=MEDIA_SEARCH_ROUTE[1],
                quantity=Decimal(DISCOVERY_SEARCH_REQUESTS),
            )
        )

        for scene in manifest.scenes:
            for shot in scene.shots:
                items.extend(self._shot_items(scene, shot, retry_attempts))
            items.append(
                self._item(
                    agent_id=AgentId.AUDIO_PERFORMANCE,
                    capability=C.VOICE_TTS,
                    provider=TTS_ROUTE[0],
                    model=TTS_ROUTE[1],
                    quantity=Decimal(_narration_chars(scene)) / 1000,
                    scene_id=scene.id,
                    attempts=retry_attempts,
                )
            )

        items.append(
            self._item(
                agent_id=AgentId.AUDIO_PERFORMANCE,
                capability=C.MUSIC_GENERATION,
                provider=MUSIC_ROUTE[0],
                model=MUSIC_ROUTE[1],
                quantity=Decimal(1),
                attempts=retry_attempts,
            )
        )

        by_scene: dict[str, Decimal] = {scene.id: Decimal(0) for scene in manifest.scenes}
        by_agent: dict[str, Decimal] = defaultdict(Decimal)
        for item in items:
            if item.scene_id is not None:
                by_scene[item.scene_id] += item.estimated_cost
            by_agent[item.agent_id.value] += item.estimated_cost

        return CostEstimate(
            production_id=manifest.production_id,
            currency=getattr(self.catalog, "currency", manifest.budget.currency),
            mode=mode_policy.mode,
            price_catalog_version=self.catalog.version,
            line_items=items,
            total_estimated=money(sum((i.estimated_cost for i in items), Decimal(0))),
            by_scene={k: money(v) for k, v in by_scene.items()},
            by_agent={k: money(v) for k, v in sorted(by_agent.items())},
        )

    def _shot_items(self, scene: Scene, shot: Shot, retry_attempts: Decimal) -> list[CostLineItem]:
        plan = shot.provider_plan
        duration = Decimal(str(shot.duration_sec))
        items: list[CostLineItem] = []

        route: tuple[ProviderCapability, str, str] | None
        if plan.capability is not None and plan.provider != "unassigned":
            route = (plan.capability, plan.provider, plan.model)
        else:
            route = DEFAULT_VISUAL_ROUTE[plan.strategy]
        if route is not None:
            capability, provider, model = route
            items.append(
                self._item(
                    agent_id=AgentId.VISUAL_PRODUCTION,
                    capability=capability,
                    provider=provider,
                    model=model,
                    quantity=duration if capability in VIDEO_CAPABILITIES else Decimal(1),
                    scene_id=scene.id,
                    shot_id=shot.id,
                    attempts=retry_attempts,
                )
            )

        if plan.strategy == GenerationStrategy.LICENSED_STILL_MOTION:
            items.append(
                self._item(
                    agent_id=AgentId.MEDIA_DISCOVERY,
                    capability=C.MEDIA_SEARCH,
                    provider=MEDIA_SEARCH_ROUTE[0],
                    model=MEDIA_SEARCH_ROUTE[1],
                    quantity=Decimal(1),
                    scene_id=scene.id,
                    shot_id=shot.id,
                )
            )

        if shot.performance.lip_sync_required:
            items.append(
                self._item(
                    agent_id=AgentId.AUDIO_PERFORMANCE,
                    capability=C.LIP_SYNC,
                    provider=LIP_SYNC_ROUTE[0],
                    model=LIP_SYNC_ROUTE[1],
                    quantity=duration,
                    scene_id=scene.id,
                    shot_id=shot.id,
                    attempts=retry_attempts,
                )
            )
        return items

    def _item(
        self,
        *,
        agent_id: AgentId,
        capability: ProviderCapability,
        provider: str,
        model: str,
        quantity: Decimal,
        scene_id: str | None = None,
        shot_id: str | None = None,
        attempts: Decimal = Decimal(1),
    ) -> CostLineItem:
        unit = UNIT_FOR_CAPABILITY[capability]
        entry = self.catalog.get(provider, model, unit)
        key = "/".join(
            part for part in (scene_id, shot_id, agent_id.value, capability.value) if part
        )
        return CostLineItem(
            key=key,
            scene_id=scene_id,
            shot_id=shot_id,
            agent_id=agent_id,
            provider=provider,
            model=model,
            capability=capability,
            unit=unit,
            quantity=money(quantity),
            unit_price=entry.unit_price,
            expected_attempts=attempts,
            estimated_cost=money(quantity * entry.unit_price * attempts),
        )


def _narration_chars(scene: Scene) -> int:
    text = (scene.narration or "").strip()
    if not text:
        text = " ".join(
            s.audio.narration_text.strip() for s in scene.shots if s.audio.narration_text
        ).strip()
    if text:
        return len(text)
    return round(scene.duration_sec * NARRATION_CHARS_PER_SEC)
