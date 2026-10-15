"""Credit-based preflight estimate for fully generative (vlog) productions.

Every shot costs a storyboard still plus a clip; spoken shots (A-roll or voice-over) add
one voice line. Rates come from the theme's ``GenerativeRules`` (credits per call / per
second), priced with the provider's credit row in the catalog. Planning LLM calls use the
standard allowance.
"""

from __future__ import annotations

from decimal import Decimal

from cineforge.contracts.common import AgentId, money
from cineforge.contracts.cost import CostEstimate, CostLineItem, PriceCatalog
from cineforge.contracts.manifest import ProductionManifest, Shot, ShotKind
from cineforge.contracts.providers import PriceUnit, ProviderCapability
from cineforge.contracts.theme import GenerativeRules, ProductionModePolicy
from cineforge.cost.estimator import (
    LLM_MODEL_PREMIUM,
    LLM_MODEL_STANDARD,
    LLM_PROVIDER,
    LLM_TOKEN_ALLOWANCE,
)

C = ProviderCapability
STAGES = ("still", "voice", "clip")


def credits_for(rules: GenerativeRules, shot: Shot, stage: str) -> Decimal:
    """Estimated credits of one call (``still``, ``voice`` or ``clip``) for a shot."""
    if stage == "still":
        value = rules.still.estimate_credits(0)
    elif stage == "voice":
        value = rules.voice_credits if shot.audio.dialogue_text else 0
    else:
        model = rules.a_roll if shot.kind == ShotKind.A_ROLL else rules.b_roll
        value = model.estimate_credits(shot.duration_sec)
    return Decimal(str(round(value, 2)))


def route_for(rules: GenerativeRules, shot: Shot, stage: str) -> tuple[ProviderCapability, str]:
    if stage == "still":
        return C.IMAGE_GENERATION, rules.still.model
    if stage == "voice":
        return C.VOICE_TTS, rules.voice_model
    model = rules.a_roll if shot.kind == ShotKind.A_ROLL else rules.b_roll
    return C.IMAGE_TO_VIDEO, model.model


def estimate_vlog(
    manifest: ProductionManifest,
    rules: GenerativeRules,
    mode_policy: ProductionModePolicy,
    catalog: PriceCatalog,
) -> CostEstimate:
    items: list[CostLineItem] = []
    llm_model = LLM_MODEL_PREMIUM if mode_policy.quality_tier == "high" else LLM_MODEL_STANDARD
    llm = catalog.get(LLM_PROVIDER, llm_model, PriceUnit.TOKENS_1K)
    for agent_id, tokens in LLM_TOKEN_ALLOWANCE.items():
        quantity = Decimal(tokens) / 1000
        items.append(
            CostLineItem(
                key=f"{agent_id.value}/{C.LLM_TEXT.value}",
                agent_id=agent_id,
                provider=LLM_PROVIDER,
                model=llm_model,
                capability=C.LLM_TEXT,
                unit=PriceUnit.TOKENS_1K,
                quantity=money(quantity),
                unit_price=llm.unit_price,
                estimated_cost=money(quantity * llm.unit_price),
            )
        )
    for scene in manifest.scenes:
        for shot in scene.shots:
            for stage in STAGES:
                credits = credits_for(rules, shot, stage)
                if credits <= 0:
                    continue
                capability, model = route_for(rules, shot, stage)
                entry = catalog.get(rules.provider, model, PriceUnit.CREDIT)
                agent = AgentId.AUDIO_PERFORMANCE if stage == "voice" else AgentId.VISUAL_PRODUCTION
                items.append(
                    CostLineItem(
                        key=f"{scene.id}/{shot.id}/{stage}/{capability.value}",
                        scene_id=scene.id,
                        shot_id=shot.id,
                        agent_id=agent,
                        provider=rules.provider,
                        model=model,
                        capability=capability,
                        unit=PriceUnit.CREDIT,
                        quantity=money(credits),
                        unit_price=entry.unit_price,
                        estimated_cost=money(credits * entry.unit_price),
                    )
                )
    by_scene = {
        s.id: money(sum((i.estimated_cost for i in items if i.scene_id == s.id), Decimal(0)))
        for s in manifest.scenes
    }
    by_agent: dict[str, Decimal] = {}
    for item in items:
        by_agent[item.agent_id.value] = by_agent.get(item.agent_id.value, Decimal(0)) + (
            item.estimated_cost
        )
    return CostEstimate(
        production_id=manifest.production_id,
        currency=getattr(catalog, "currency", manifest.budget.currency),
        mode=mode_policy.mode,
        price_catalog_version=catalog.version,
        line_items=items,
        total_estimated=money(sum((i.estimated_cost for i in items), Decimal(0))),
        by_scene=by_scene,
        by_agent={k: money(v) for k, v in sorted(by_agent.items())},
    )


def estimate_credits(manifest: ProductionManifest, rules: GenerativeRules) -> Decimal:
    return sum(
        (credits_for(rules, shot, stage) for shot in manifest.iter_shots() for stage in STAGES),
        Decimal(0),
    )
