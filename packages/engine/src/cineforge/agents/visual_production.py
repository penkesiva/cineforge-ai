"""A7 Visual Production Agent: one provider call per shot attempt (via PaidCallGuard).

Retries are owned by the orchestrator (bounded by the mode policy). A ``ProviderError``
propagates so the orchestrator can record the failed attempt and decide to retry.

Fully generative shots run twice: ``stage="still"`` makes the storyboard frame
(image generation) and ``stage="clip"`` animates it. The orchestrator prepares the
shot's provider plan for the stage (capability, model, prompt, media references);
the CDN URL of the result is returned for the orchestrator to download and register.
"""

from __future__ import annotations

from cineforge.agents.base import BaseAgent
from cineforge.contracts.agents import AgentContext, RenderedShotRef, ShotProductionInput
from cineforge.contracts.common import AgentId
from cineforge.contracts.providers import ProviderCapability

MAX_NOTE_CHARS = 400


class VisualProductionAgent(BaseAgent):
    agent_id = AgentId.VISUAL_PRODUCTION
    input_model = ShotProductionInput
    output_model = RenderedShotRef

    def execute(self, ctx: AgentContext, payload: ShotProductionInput) -> RenderedShotRef:
        shot = payload.shot
        plan = shot.provider_plan
        default = (
            ProviderCapability.IMAGE_GENERATION
            if payload.stage == "still"
            else ProviderCapability.IMAGE_TO_VIDEO
        )
        capability = plan.capability or default
        prompt = plan.prompt or shot.description
        if payload.note:
            prompt = f"{prompt} Director's note: {payload.note.strip()[:MAX_NOTE_CHARS]}"
        self.render_prompt(
            ctx,
            shot_id=shot.id,
            strategy=plan.strategy.value,
            capability=capability.value,
            model=plan.model,
            attempt=payload.attempt,
            retry_reason=payload.retry_reason or "none",
            prompt=prompt,
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
            prompt=prompt,
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
            stage=payload.stage,
            output_url=response.output_data.get("result_url"),
            prompt=prompt,
            parameters={k: v for k, v in parameters.items() if k != "still_prompt"},
        )
