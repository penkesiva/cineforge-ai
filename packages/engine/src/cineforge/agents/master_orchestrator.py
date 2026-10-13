"""A1 Master Orchestrator: production plan (steps, agents, scene target, budget envelope)."""

from __future__ import annotations

from cineforge.agents.base import BaseAgent, note
from cineforge.agents.planning import target_scene_count
from cineforge.contracts.agents import AgentContext, PlannedStep, PlanningInput, ProductionPlan
from cineforge.contracts.common import AgentId
from cineforge.contracts.workflow import ProductionState

A = AgentId
S = ProductionState

PLAN_STEPS: tuple[PlannedStep, ...] = (
    PlannedStep(
        state=S.RESEARCHING,
        agent_ids=[A.MASTER_ORCHESTRATOR, A.CREATIVE_DIRECTOR, A.RESEARCH, A.MEDIA_DISCOVERY],
    ),
    PlannedStep(state=S.SCRIPTING, agent_ids=[A.SCRIPTWRITER]),
    PlannedStep(state=S.STORYBOARDING, agent_ids=[A.SCENE_DIRECTOR, A.COST_OPTIMIZER]),
    PlannedStep(state=S.GENERATING, agent_ids=[A.VISUAL_PRODUCTION, A.AUDIO_PERFORMANCE]),
    PlannedStep(state=S.ASSEMBLING, agent_ids=[A.EDITOR_QC]),
    PlannedStep(state=S.REVIEWING, agent_ids=[A.EDITOR_QC]),
)


class MasterOrchestratorAgent(BaseAgent):
    agent_id = AgentId.MASTER_ORCHESTRATOR
    input_model = PlanningInput
    output_model = ProductionPlan

    def execute(self, ctx: AgentContext, payload: PlanningInput) -> ProductionPlan:
        scenes = target_scene_count(ctx.theme, payload.duration_target_sec)
        prompt = self.render_prompt(
            ctx,
            topic=payload.brief.topic,
            theme_name=ctx.theme.name,
            mode=payload.mode.value,
            duration_sec=payload.duration_target_sec,
            budget_limit=payload.budget_limit,
            scene_count=scenes,
        )
        response = self._llm(ctx, prompt, "plan")
        notes = [
            f"Theme '{ctx.theme.name}' v{ctx.theme.version}, mode {payload.mode.value}.",
            f"{scenes} scenes for {payload.duration_target_sec:g}s "
            f"(theme range {ctx.theme.production.min_scenes}-{ctx.theme.production.max_scenes}).",
            f"Max {ctx.mode_policy.max_attempts_per_shot} attempts per shot; "
            f"hard budget cap {payload.budget_limit} USD enforced by the ledger.",
        ]
        if ctx.mode_policy.storyboard_preflight:
            notes.append("Storyboard preflight: cost estimate gates generation.")
        llm_note = note(response.output_text if response else None)
        if llm_note:
            notes.append(f"LLM: {llm_note}")
        return ProductionPlan(
            production_id=payload.production_id,
            mode=payload.mode,
            steps=[s.model_copy(deep=True) for s in PLAN_STEPS],
            scene_count_target=scenes,
            budget_envelope=payload.budget_limit,
            notes=notes,
        )
