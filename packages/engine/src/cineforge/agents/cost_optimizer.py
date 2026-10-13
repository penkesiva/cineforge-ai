"""A10 Cost & Optimization Agent: within-budget decision and routing advice.

The estimate itself comes from the deterministic ``CostEstimator``; this agent never
calls a provider (no capabilities) and never enforces the budget (the ledger does).
"""

from __future__ import annotations

from decimal import Decimal

from cineforge.agents.base import BaseAgent
from cineforge.contracts.agents import AgentContext, CostPlan, CostPlanningInput
from cineforge.contracts.common import AgentId, GenerationStrategy

_STATIC_MOTIONS = {"static", "ken_burns", "slow_push", "slow_pull"}


class CostOptimizerAgent(BaseAgent):
    agent_id = AgentId.COST_OPTIMIZER
    input_model = CostPlanningInput
    output_model = CostPlan

    def execute(self, ctx: AgentContext, payload: CostPlanningInput) -> CostPlan:
        manifest, estimate, policy = payload.manifest, payload.estimate, payload.mode_policy
        self.render_prompt(
            ctx,
            production_id=manifest.production_id,
            total_estimated=estimate.total_estimated,
            limit=manifest.budget.limit,
            mode=policy.mode.value,
        )
        limit = manifest.budget.limit
        total = estimate.total_estimated
        within = total <= limit
        pct = (total / limit * 100) if limit > 0 else Decimal(0)
        recs = [
            f"Estimated {total} of {limit} {estimate.currency} ({pct:.0f}% of the hard cap, "
            f"incl. expected retries at {policy.expected_retry_rate:.0%})."
        ]
        shots = list(manifest.iter_shots())
        static_premium = [
            sh.id
            for sh in shots
            if sh.visual.camera_motion in _STATIC_MOTIONS
            and sh.provider_plan.strategy != GenerationStrategy.GENERATIVE
            and "draft" not in sh.provider_plan.model
        ]
        if static_premium:
            recs.append(
                f"Use the draft model for {len(static_premium)} static shot(s): "
                + ", ".join(static_premium[:5])
            )
        else:
            recs.append("Use draft model for static shots (already applied).")
        generative = [
            sh for sh in shots if sh.provider_plan.strategy == GenerationStrategy.GENERATIVE
        ]
        if not within:
            gap = total - limit
            recs.append(
                f"Over budget by {gap}: raise the cap or switch "
                f"{len(generative)} generative shot(s) to licensed-still-motion."
            )
        if generative and not policy.draft_first:
            recs.append("Enable draft-first previews to catch failed generative takes early.")
        if estimate.by_scene:
            top_scene, top_cost = max(estimate.by_scene.items(), key=lambda kv: kv[1])
            recs.append(f"Most expensive scene: {top_scene} ({top_cost}).")
        return CostPlan(
            production_id=manifest.production_id,
            estimate=estimate,
            within_budget=within,
            recommendations=recs,
        )
