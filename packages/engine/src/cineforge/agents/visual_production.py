"""A7 Visual Production Agent: one provider call per shot attempt (via PaidCallGuard).

Retries are owned by the orchestrator (bounded by the mode policy). A ``ProviderError``
propagates so the orchestrator can record the failed attempt and decide to retry.
"""

from __future__ import annotations

from cineforge.agents.base import BaseAgent
from cineforge.contracts.agents import AgentContext, RenderedShotRef, ShotProductionInput
from cineforge.contracts.common import AgentId
from cineforge.contracts.providers import ProviderCapability


class VisualProductionAgent(BaseAgent):
    agent_id = AgentId.VISUAL_PRODUCTION
    input_model = ShotProductionInput
    output_model = RenderedShotRef

    def execute(self, ctx: AgentContext, payload: ShotProductionInput) -> RenderedShotRef:
        shot = payload.shot
        plan = shot.provider_plan
        capability = plan.capability or ProviderCapability.IMAGE_TO_VIDEO
        self.render_prompt(
            ctx,
            shot_id=shot.id,
            strategy=plan.strategy.value,
            capability=capability.value,
            model=plan.model,
            attempt=payload.attempt,
            retry_reason=payload.retry_reason or "none",
            prompt=plan.prompt or shot.description,
        )
        model = plan.model if plan.model != "unassigned" else None
        parameters = {"duration_sec": shot.duration_sec, **plan.parameters}
        if payload.retry_reason:
            parameters["retry_reason"] = payload.retry_reason
        response, event = self.call_provider(
            ctx,
            capability,
            provider_name=plan.provider,
            model=model,
            prompt=plan.prompt or shot.description,
            negative_prompt=plan.negative_prompt,
            seed=plan.seed,
            scene_id=payload.scene_id,
            shot_id=shot.id,
            reference_asset_ids=plan.reference_asset_ids,
            parameters=parameters,
            attempt=payload.attempt,
            retry_reason=payload.retry_reason,
        )
        return RenderedShotRef(
            scene_id=payload.scene_id,
            shot_id=shot.id,
            asset_id=response.output_asset_id,
            provider=response.provider,
            model=response.model,
            attempt=payload.attempt,
            cost=event.actual_cost,
            ledger_event_id=event.event_id,
        )
