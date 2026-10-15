"""Production workflow engine (docs/architecture/contracts.md section 4).

One ``advance`` call executes the CURRENT state's work, transitions, then enqueues the
next ``advance`` (job id ``{production_id}:{state}:{n}``). It stops at gates
(AWAITING_APPROVAL without auto-approve), the media hand-off (ASSEMBLING without a
master) and terminal/exception states. ``advance`` is idempotent: a stale job (its id
names a state the production is no longer in) is a no-op, and agent runs are keyed
``{production_id}:{state}:{agent_id}:{scope}:{attempt}`` so a SUCCEEDED run is reused.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_DOWN, Decimal
from typing import Any

from pydantic import BaseModel

from cineforge.agents.base import LEDGER_EVENTS
from cineforge.agents.planning import target_scene_count
from cineforge.configuration import (
    PersonaNotFoundError,
    get_persona,
    load_canon,
    load_mode_policies,
)
from cineforge.contracts.agents import (
    AgentContext,
    AgentRun,
    AgentRunStatus,
    AssetSelection,
    AudioInput,
    AudioPackage,
    CostPlan,
    CostPlanningInput,
    CreativeInput,
    CreativeTreatment,
    MasterRender,
    MediaDiscoveryInput,
    PlanningInput,
    RenderedShotRef,
    ResearchBrief,
    ResearchInput,
    ReviewInput,
    SceneDirectionInput,
    SceneGraph,
    Script,
    ScriptInput,
    ShotProductionInput,
    agent_definition,
)
from cineforge.contracts.api import (
    ApproveProductionRequest,
    CreateProductionRequest,
    RegenerateShotRequest,
    ReviewClaimsRequest,
    StageQuote,
)
from cineforge.contracts.common import MONEY_QUANTUM, AgentId, money, new_id, utcnow
from cineforge.contracts.cost import BudgetExceededError, CostEstimate, LedgerEvent
from cineforge.contracts.jobs import (
    JOB_ADVANCE_PRODUCTION,
    JOB_REGENERATE_SHOT,
    JOB_RENDER_MASTER,
    QUEUE_AGENTS,
    QUEUE_MEDIA,
)
from cineforge.contracts.manifest import (
    ApprovalPolicy,
    ApprovalStage,
    AssetRef,
    AssetRole,
    AuditEntry,
    BudgetSnapshot,
    Caption,
    CaptionTrack,
    ClaimReview,
    CreativeBrief,
    OutputProfile,
    ProductionManifest,
    ProviderAttempt,
    Scene,
    Shot,
    Soundtrack,
    ThemeRef,
    WorkStatus,
)
from cineforge.contracts.media import RightsStatus
from cineforge.contracts.persona import Episode, PersonaCanon, PersonaProfile
from cineforge.contracts.providers import PriceUnit, ProviderError
from cineforge.contracts.repositories import NotFoundError
from cineforge.contracts.review import ReviewStatus
from cineforge.contracts.theme import ProductionModePolicy, ThemeProfile
from cineforge.contracts.workflow import (
    WORKING_STATES,
    InvalidStateTransitionError,
    ProductionEvent,
    ProductionState,
    assert_transition,
)
from cineforge.cost.vlog import estimate_vlog
from cineforge.orchestration.studio import VlogStudio, is_done, next_stage, stage_state
from cineforge.persistence.serde import dump, load
from cineforge.runtime import Runtime

log = logging.getLogger(__name__)

S = ProductionState
A = AgentId
_DONE = (WorkStatus.COMPLETE, WorkStatus.APPROVED)
SCENE_BUDGET_HEADROOM = Decimal("1.5")
REWRITE_ACTION = "script_rewrite_requested"
CLAIM_REVIEW_STATES = (S.AWAITING_APPROVAL, S.PAUSED_BUDGET)
VLOG_BUDGET_MARGIN = Decimal("1.00")
CAPTION_WORDS = 6
EPISODE_LOOKBACK = 200


class WorkflowError(RuntimeError):
    pass


class ApprovalBlockedError(WorkflowError):
    """Approval refused by a deterministic rule (e.g. the script cites a rejected claim)."""


class InvalidClaimReviewError(WorkflowError):
    pass


class RegenerateError(WorkflowError):
    """A shot redo is not allowed now (wrong state, stage or shot)."""


def rejected_claim_ids(m: ProductionManifest) -> set[str]:
    latest: dict[str, str] = {}
    for review in m.claim_reviews:
        latest[review.claim_id] = review.decision
    return {cid for cid, decision in latest.items() if decision == "rejected"}


def script_revision(m: ProductionManifest) -> int:
    """1 for the first script; +1 per rewrite request (keys new A5/A6/A10 runs)."""
    return 1 + sum(1 for a in m.audit if a.action == REWRITE_ACTION)


class ShotFailedError(WorkflowError):
    def __init__(self, shot_id: str, attempts: int, reason: str) -> None:
        super().__init__(f"shot {shot_id} failed after {attempts} attempt(s): {reason}")
        self.shot_id = shot_id
        self.attempts = attempts
        self.reason = reason


class _Interrupted(Exception):
    """The production left the state being worked on (e.g. cancelled mid-step)."""


@dataclass(frozen=True)
class ActionResult:
    manifest: ProductionManifest
    job_id: str | None = None
    message: str = ""


@dataclass
class Invocation:
    output: Any
    run: AgentRun
    ledger_events: list[LedgerEvent] = field(default_factory=list)
    reused: bool = False


@dataclass
class StepOutcome:
    manifest: ProductionManifest
    next_state: ProductionState | None
    reason: str
    payload: dict[str, Any] = field(default_factory=dict)
    events: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)


def parse_job_state(production_id: str, idempotency_key: str) -> ProductionState | None:
    """State named by a job id ``{production_id}:{state}:{n}``; None if not in that form."""
    parts = idempotency_key.split(":")
    if len(parts) >= 2 and parts[0] == production_id:
        try:
            return ProductionState(parts[1])
        except ValueError:
            return None
    return None


def summarize_payload(payload: BaseModel) -> dict[str, Any]:
    """Small, JSON-safe summary of an agent input (stored on AgentRun.input_summary)."""
    out: dict[str, Any] = {"input_model": type(payload).__name__}
    for name in type(payload).model_fields:
        value = getattr(payload, name)
        if value is None or isinstance(value, bool | int | float):
            out[name] = value
        elif isinstance(value, str):
            out[name] = value[:200]
        elif isinstance(value, Decimal):
            out[name] = float(value)
        elif isinstance(value, list):
            out[name] = f"{len(value)} items"
        elif isinstance(value, CreativeBrief):
            out["topic"] = value.topic[:200]
        elif isinstance(value, Shot):
            out["shot_id"] = value.id
        elif isinstance(value, ProductionManifest):
            out[name] = {"production_id": value.production_id, "scenes": len(value.scenes)}
        elif isinstance(value, BaseModel):
            out[name] = type(value).__name__
    return out


def _spoken_cues(text: str, start: float, duration: float) -> list[Caption]:
    """Short burned-in cues for a spoken line, timed by word share of the shot."""
    words = text.split()
    if not words:
        return []
    chunks = [words[i : i + CAPTION_WORDS] for i in range(0, len(words), CAPTION_WORDS)]
    per_word = duration / len(words)
    cues, t = [], start
    for chunk in chunks:
        end = t + per_word * len(chunk)
        cues.append(Caption(start_sec=round(t, 2), end_sec=round(end, 2), text=" ".join(chunk)))
        t = end
    return cues


def _sum_actual(events: list[LedgerEvent]) -> Decimal:
    return money(sum((e.actual_cost for e in events), Decimal(0)))


def _floor_money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(MONEY_QUANTUM, rounding=ROUND_DOWN)


class WorkflowEngine:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.settings = runtime.settings
        self._handlers: dict[ProductionState, Callable[[ProductionManifest], StepOutcome]] = {
            S.RESEARCHING: self._research,
            S.SCRIPTING: self._script,
            S.STORYBOARDING: self._storyboard,
            S.GENERATING: self._generate,
            S.ASSEMBLING: self._assemble,
            S.REVIEWING: self._review,
        }
        self.studio = VlogStudio(self)

    # ================================================================== config
    def theme_for(self, m: ProductionManifest) -> ThemeProfile:
        return self.rt.themes.get(m.theme_profile.id, m.theme_profile.version)

    def policy_for(self, m: ProductionManifest) -> ProductionModePolicy:
        return load_mode_policies(self.settings.configurations_dir)[m.mode]

    def persona_for(self, m: ProductionManifest) -> PersonaProfile | None:
        if not m.persona_id:
            return None
        try:
            return get_persona(self.settings.configurations_dir, m.persona_id, m.persona_version)
        except PersonaNotFoundError:
            log.warning("%s: persona %s not found", m.production_id, m.persona_id)
            return None

    def canon_for(self, m: ProductionManifest) -> PersonaCanon | None:
        if not m.persona_id:
            return None
        return self.persona_canon(m.tenant_id, m.persona_id, exclude=m.production_id)

    def persona_canon(
        self, tenant_id: str, persona_id: str, *, exclude: str | None = None
    ) -> PersonaCanon:
        """Curated canon plus this tenant's finished productions with the same persona."""
        canon = load_canon(self.settings.configurations_dir, persona_id)
        known = {e.production_id for e in canon.episodes if e.production_id}
        past = [
            Episode(
                title=p.title,
                summary=p.creative_brief.topic,
                production_id=p.production_id,
                on=p.created_at.date(),
            )
            for p in self.rt.productions.list(tenant_id, limit=EPISODE_LOOKBACK)
            if p.persona_id == persona_id
            and p.production_id != exclude
            and p.production_id not in known
            and p.state in (S.READY, S.DELIVERED)
        ]
        episodes = sorted([*canon.episodes, *past], key=lambda e: e.on or date.min)
        return canon.model_copy(update={"episodes": episodes})

    def _persona_version(self, theme: ThemeProfile) -> int | None:
        if not theme.performance.persona_id:
            return None
        cfg = self.settings.configurations_dir
        return get_persona(cfg, theme.performance.persona_id).version

    def _default_limit(self, theme: ThemeProfile, policy: ProductionModePolicy) -> Decimal:
        rules = theme.production.generative
        if rules is None:
            return policy.default_budget_usd
        entry = self.rt.price_catalog.get(rules.provider, rules.a_roll.model, PriceUnit.CREDIT)
        return money(Decimal(rules.credit_cap) * entry.unit_price + VLOG_BUDGET_MARGIN)

    # ================================================================== commands
    def create_production(self, req: CreateProductionRequest, tenant_id: str) -> ProductionManifest:
        cfg = self.settings.configurations_dir
        theme = self.rt.themes.get(req.theme_id, req.theme_version)
        policy = load_mode_policies(cfg)[req.mode]
        limit = money(
            req.budget_limit_usd
            if req.budget_limit_usd is not None
            else self._default_limit(theme, policy)
        )
        width, _, height = theme.production.resolution.partition("x")
        production_id = new_id("prod")
        manifest = ProductionManifest(
            production_id=production_id,
            tenant_id=tenant_id,
            title=req.title or req.topic[:120],
            theme_profile=ThemeRef(id=theme.id, version=theme.version),
            mode=req.mode,
            creative_brief=CreativeBrief(
                topic=req.topic,
                genre=theme.genres[0],
                language=req.language,
                audience=theme.audience,
            ),
            output=OutputProfile(
                aspect_ratio=theme.production.aspect_ratio,
                width=int(width) if width.isdigit() else 1080,
                height=int(height) if height.isdigit() else 1920,
                duration_target_sec=req.duration_target_sec,
            ),
            budget=BudgetSnapshot(limit=limit),
            approval=ApprovalPolicy(auto_approve=req.auto_approve),
            character_bible_ref=theme.performance.recurring_character,
            persona_id=theme.performance.persona_id,
            persona_version=self._persona_version(theme),
            audit=[
                AuditEntry(
                    actor="system",
                    action="created",
                    details={
                        "theme": f"{theme.id}@v{theme.version}",
                        "mode": req.mode.value,
                        "budget_limit": float(limit),
                        "auto_approve": req.auto_approve,
                    },
                )
            ],
        )
        key = f"{tenant_id}:{req.idempotency_key}" if req.idempotency_key else None
        created = self.rt.productions.create(manifest, idempotency_key=key)
        if created.production_id != production_id:
            return created  # idempotent replay: budget and events already exist
        self.rt.budget.create_budget(
            tenant_id=tenant_id,
            production_id=production_id,
            limit=limit,
            currency=manifest.budget.currency,
        )
        self._event(
            created,
            "created",
            f"Production created ({theme.name}, {req.mode.value}, {limit} USD cap)",
            {"theme_id": theme.id, "mode": req.mode.value, "budget_limit": float(limit)},
        )
        return created

    def start(self, production_id: str, tenant_id: str) -> ActionResult:
        m = self._load(production_id, tenant_id)
        m = self._command_transition(m, S.RESEARCHING, "Run requested", "run_requested")
        job_id = self._enqueue_advance(m)
        return ActionResult(m, job_id, "Production started")

    def approve(
        self, production_id: str, tenant_id: str, req: ApproveProductionRequest
    ) -> ActionResult:
        m = self._load(production_id, tenant_id)
        if m.state not in (S.AWAITING_APPROVAL, S.PAUSED_BUDGET):
            raise InvalidStateTransitionError(m.state, S.GENERATING)
        self._check_claims_for_approval(m)
        from_state = m.state
        self._advance_stage(m)
        if req.raise_budget_to_usd is not None:
            self._set_production_limit(m, money(req.raise_budget_to_usd))
        m.approval = m.approval.model_copy(
            update={"approved_by": req.approved_by, "approved_at": utcnow(), "note": req.note}
        )
        details = {
            "from_state": from_state.value,
            "stage": m.approval_stage.value if m.approval_stage else None,
            "approved_by": req.approved_by,
            "note": req.note,
            "raise_budget_to_usd": (
                float(req.raise_budget_to_usd) if req.raise_budget_to_usd is not None else None
            ),
        }
        m = self._command_transition(
            m,
            S.GENERATING,
            f"Approved by {req.approved_by}",
            "approved",
            details,
            actor=req.approved_by,
        )
        self._event(m, "approved", f"Approved by {req.approved_by}", details)
        job_id = self._enqueue_advance(m)
        return ActionResult(m, job_id, "Production approved; generation queued")

    def review_claims(
        self, production_id: str, tenant_id: str, req: ReviewClaimsRequest
    ) -> ActionResult:
        """Record human claim decisions at the gate (latest decision per claim wins)."""
        m = self._load(production_id, tenant_id)
        if m.state not in CLAIM_REVIEW_STATES:
            raise InvalidStateTransitionError(m.state, m.state)
        research = self._artifact(m, ResearchBrief, required=False)
        known = {c.id for c in research.claims} if research else set()
        unknown = sorted({d.claim_id for d in req.decisions} - known)
        if unknown:
            raise InvalidClaimReviewError(f"unknown claim id(s): {', '.join(unknown)}")
        now = utcnow()
        for decision in req.decisions:
            m.claim_reviews.append(
                ClaimReview(
                    claim_id=decision.claim_id,
                    decision=decision.decision,
                    reviewed_by=req.reviewed_by,
                    reviewed_at=now,
                    note=decision.note,
                )
            )
        rejected = sorted(rejected_claim_ids(m))
        blocking = sorted(self._lines_citing(m, set(rejected)))
        details = {
            "reviewed_by": req.reviewed_by,
            "decisions": {d.claim_id: d.decision for d in req.decisions},
            "rejected": rejected,
            "blocking_scenes": blocking,
        }
        self._audit(m, req.reviewed_by, "claims_reviewed", details)
        self.rt.productions.save(m)
        message = f"{len(req.decisions)} claim decision(s) by {req.reviewed_by}"
        if blocking:
            message += f"; script must be rewritten (scenes {', '.join(map(str, blocking))})"
        self._event(m, "claims_reviewed", message, details)
        return ActionResult(self._load(production_id, tenant_id), None, message)

    def rewrite_script(
        self, production_id: str, tenant_id: str, *, requested_by: str = "operator"
    ) -> ActionResult:
        """Back to SCRIPTING (via NEEDS_REVIEW) so A5 rewrites without rejected claims."""
        m = self._load(production_id, tenant_id)
        if m.state == S.AWAITING_APPROVAL:
            m = self._command_transition(
                m, S.NEEDS_REVIEW, "Script rewrite requested", "rewrite_gate_left",
                actor=requested_by,
            )  # fmt: skip
        if m.state != S.NEEDS_REVIEW:
            raise InvalidStateTransitionError(m.state, S.SCRIPTING)
        revision = script_revision(m) + 1
        details = {"revision": revision, "excluded_claims": sorted(rejected_claim_ids(m))}
        m = self._command_transition(
            m, S.SCRIPTING, f"Script rewrite (revision {revision})", REWRITE_ACTION, details,
            actor=requested_by,
        )  # fmt: skip
        self._event(m, "script_rewrite_requested", f"Script revision {revision} queued", details)
        job_id = self._enqueue_advance(m)
        return ActionResult(m, job_id, f"Script revision {revision} queued")

    def regenerate_shot(
        self, production_id: str, tenant_id: str, shot_id: str, req: RegenerateShotRequest
    ) -> ActionResult:
        """Queue a redo of one shot's still, voice line or clip at a vlog gate."""
        m = self._load(production_id, tenant_id)
        if not self.theme_for(m).production.fully_generative:
            raise RegenerateError("shot redo is only for fully generative productions")
        if m.state != S.AWAITING_APPROVAL or m.approval_stage in (None, ApprovalStage.SCRIPT):
            raise RegenerateError("shot redo is possible at the preview, pilot or final gate")
        shot = m.find_shot(shot_id)
        if shot is None:
            raise NotFoundError(f"shot {shot_id} not found")
        if shot.status == WorkStatus.IN_PROGRESS:
            raise RegenerateError(f"shot {shot_id} is already regenerating")
        state = stage_state(shot, req.target)
        if not state.get("attempt"):
            raise RegenerateError(f"shot {shot_id} has no {req.target} to redo yet")
        n = int(state["attempt"]) + 1
        shot.status = WorkStatus.IN_PROGRESS
        details = {"shot_id": shot_id, "target": req.target, "attempt": n, "note": req.note}
        self._audit(m, req.requested_by, "regenerate_requested", details)
        self.rt.productions.save(m)
        job_id = f"{production_id}:regenerate:{shot_id}:{req.target}:{n}"
        message = f"Redo of {req.target} for {shot_id} queued"
        self._event(m, "regenerate_requested", message, details)
        self.rt.queue.enqueue(
            QUEUE_AGENTS,
            JOB_REGENERATE_SHOT,
            {
                "production_id": production_id,
                "tenant_id": tenant_id,
                "shot_id": shot_id,
                "request": req.model_dump(mode="json"),
            },
            job_id=job_id,
        )
        return ActionResult(self._load(production_id, tenant_id), job_id, message)

    def run_regeneration(
        self, production_id: str, tenant_id: str, shot_id: str, request: dict[str, Any]
    ) -> ProductionManifest | None:
        req = RegenerateShotRequest.model_validate(request)
        m = self.rt.productions.get(production_id, tenant_id)
        if m is None:
            return None
        shot = m.find_shot(shot_id)
        if m.state != S.AWAITING_APPROVAL or shot is None or shot.status != WorkStatus.IN_PROGRESS:
            log.info("regenerate %s/%s: nothing to do (%s)", production_id, shot_id, m.state)
            return m
        theme, policy = self.theme_for(m), self.policy_for(m)
        try:
            self.studio.regenerate(m, theme, policy, shot_id, req)
            ok, message = True, f"New {req.target} for {shot_id} ready"
        except Exception as exc:
            log.exception("regenerate %s/%s failed", production_id, shot_id)
            ok, message = False, f"Redo of {req.target} for {shot_id} failed: {exc}"[:500]
        shot = m.find_shot(shot_id)
        if shot is not None and shot.status == WorkStatus.IN_PROGRESS:
            shot.status = WorkStatus.COMPLETE if is_done(shot, "clip") else WorkStatus.PLANNED
        for scene in m.scenes:
            scene.duration_sec = round(sum(sh.duration_sec for sh in scene.shots), 2)
        m.captions = [self._captions(m)]
        self._sync_costs(m)
        details = {"shot_id": shot_id, "target": req.target, "ok": ok}
        self._audit(m, "system", "regenerate_finished", {**details, "message": message})
        self.rt.productions.save(m)
        self._event(m, "regenerate_finished", message, details)
        return self._load(production_id, tenant_id)

    def stage_quote(self, production_id: str, tenant_id: str) -> StageQuote | None:
        m = self._load(production_id, tenant_id)
        theme = self.theme_for(m)
        if not theme.production.fully_generative:
            return None
        return self.studio.quote(m, theme)

    def cancel(
        self, production_id: str, tenant_id: str, reason: str = "Cancelled by operator"
    ) -> ActionResult:
        m = self._load(production_id, tenant_id)
        m = self._command_transition(m, S.CANCELLED, reason, "cancelled")
        return ActionResult(m, None, "Production cancelled")

    def deliver(self, production_id: str, tenant_id: str) -> ActionResult:
        m = self._load(production_id, tenant_id)
        m = self._command_transition(m, S.DELIVERED, "Delivered", "delivered")
        return ActionResult(m, None, "Production delivered")

    # ================================================================== advance
    def advance(
        self, production_id: str, tenant_id: str, idempotency_key: str
    ) -> ProductionManifest | None:
        m = self.rt.productions.get(production_id, tenant_id)
        if m is None:
            log.warning("advance: production %s not found for %s", production_id, tenant_id)
            return None
        expected = parse_job_state(production_id, idempotency_key)
        if expected is not None and expected != m.state:
            log.info(
                "advance %s: stale job for %s (now %s); skipped", idempotency_key, expected, m.state
            )
            return m
        state = m.state
        if state == S.AWAITING_APPROVAL:
            return self._auto_approve(m) if m.approval.auto_approve else m
        handler = self._handlers.get(state)
        if handler is None or state not in WORKING_STATES:
            return m
        log.info("advance %s: running %s", production_id, state)
        try:
            outcome = handler(m)
        except _Interrupted:
            return self.rt.productions.get(production_id, tenant_id)
        except BudgetExceededError as exc:
            return self._pause_for_budget(production_id, tenant_id, state, exc)
        except Exception as exc:
            log.exception("advance %s: %s failed", production_id, state)
            return self._fail(production_id, tenant_id, state, exc)
        return self._complete_step(state, outcome)

    def _complete_step(
        self, from_state: ProductionState, outcome: StepOutcome
    ) -> ProductionManifest:
        m = outcome.manifest
        self.rt.productions.save(m)
        if outcome.next_state is None:
            return self._load(m.production_id, m.tenant_id)
        try:
            moved = self.rt.productions.transition(
                m.production_id,
                m.tenant_id,
                outcome.next_state,
                reason=outcome.reason,
                payload=outcome.payload,
            )
        except InvalidStateTransitionError:
            current = self._load(m.production_id, m.tenant_id)
            if current.state != from_state:
                log.info(
                    "%s moved to %s during %s; not transitioning",
                    m.production_id,
                    current.state,
                    from_state,
                )
                return current
            raise
        for event_type, message, payload in outcome.events:
            self._event(moved, event_type, message, payload)
        self._continue(moved)
        return moved

    def _continue(self, m: ProductionManifest) -> str | None:
        """Sleep (demo pacing) and enqueue the next advance unless at a stop point."""
        auto_gate = m.state == S.AWAITING_APPROVAL and m.approval.auto_approve
        if m.state not in WORKING_STATES and not auto_gate:
            return None
        if self.settings.mock_step_delay_sec > 0:
            time.sleep(self.settings.mock_step_delay_sec)
        return self._enqueue_advance(m)

    def _auto_approve(self, m: ProductionManifest) -> ProductionManifest:
        try:
            self._advance_stage(m)
        except ApprovalBlockedError as exc:
            self._event(m, "approval_blocked", str(exc), {"auto": True})
            return m
        m.approval = m.approval.model_copy(
            update={"approved_by": "auto", "approved_at": utcnow(), "note": "auto_approve policy"}
        )
        details = {"from_state": m.state.value, "approved_by": "auto", "auto": True}
        m = self._command_transition(m, S.GENERATING, "Auto-approved", "approved", details)
        self._event(m, "approved", "Auto-approved by policy", details)
        self._continue(m)
        return m

    def _advance_stage(self, m: ProductionManifest) -> None:
        """Vlog gates: refuse approval while blocked, then move to the next stage."""
        theme = self.theme_for(m)
        rules = theme.production.generative
        if rules is None:
            return
        blockers = self.studio.blockers(m, theme)
        if self.settings.provider_mode == "live":
            quote = self.studio.quote(m, theme)
            if (
                quote.credit_cap is not None
                and quote.credits_used + quote.credits > quote.credit_cap
            ):
                blockers.append(
                    f"next stage needs {quote.credits} credits; {quote.credits_used} of "
                    f"{quote.credit_cap} already used"
                )
        if blockers:
            raise ApprovalBlockedError("; ".join(blockers))
        if m.state == S.AWAITING_APPROVAL:
            m.approval_stage = next_stage(m.approval_stage)

    def _pause_for_budget(
        self, production_id: str, tenant_id: str, state: ProductionState, exc: BudgetExceededError
    ) -> ProductionManifest:
        m = self._load(production_id, tenant_id)
        if m.state != state:
            return m
        payload = {
            "step": state.value,
            "requested": float(exc.requested),
            "available": float(exc.available),
            "scene_id": exc.scene_id,
        }
        self._sync_budget(m)
        self._audit(m, "system", "budget_paused", payload)
        self.rt.productions.save(m)
        moved = self.rt.productions.transition(
            production_id, tenant_id, S.PAUSED_BUDGET, reason=str(exc), payload=payload
        )
        self._event(moved, "budget_paused", str(exc), payload)
        return moved

    def _fail(
        self, production_id: str, tenant_id: str, state: ProductionState, exc: Exception
    ) -> ProductionManifest:
        m = self._load(production_id, tenant_id)
        if m.state != state:
            return m
        payload: dict[str, Any] = {
            "step": state.value,
            "error": f"{type(exc).__name__}: {exc}"[:1000],
        }
        if isinstance(exc, ShotFailedError):
            payload |= {"shot_id": exc.shot_id, "attempts": exc.attempts}
        self._audit(m, "system", "failed", payload)
        self.rt.productions.save(m)
        moved = self.rt.productions.transition(
            production_id, tenant_id, S.FAILED, reason=str(exc)[:500], payload=payload
        )
        self._event(moved, "failed", str(exc)[:500], payload)
        return moved

    # ================================================================== step handlers
    def _research(self, m: ProductionManifest) -> StepOutcome:
        theme, policy = self.theme_for(m), self.policy_for(m)
        brief = m.creative_brief
        self._invoke(
            m,
            theme,
            policy,
            A.MASTER_ORCHESTRATOR,
            PlanningInput(
                production_id=m.production_id,
                brief=brief,
                mode=m.mode,
                budget_limit=m.budget.limit,
                duration_target_sec=m.output.duration_target_sec,
            ),
        )
        treatment = self._invoke(
            m, theme, policy, A.CREATIVE_DIRECTOR, CreativeInput(brief=brief, theme=theme)
        )
        research = self._invoke(
            m,
            theme,
            policy,
            A.RESEARCH,
            ResearchInput(
                brief=brief, theme_id=theme.id, factual_rigor=theme.narrative.factual_rigor
            ),
        )
        intended_use = "commercial"
        media = self._invoke(
            m,
            theme,
            policy,
            A.MEDIA_DISCOVERY,
            MediaDiscoveryInput(
                brief=brief, claims=research.output.claims, intended_use=intended_use
            ),
        )
        gated = self._apply_rights_gate(media.output, intended_use)
        # The gated selection is the artifact downstream agents (and the dashboard) use.
        self.rt.agent_runs.finish(
            media.run.id,
            status=AgentRunStatus.SUCCEEDED,
            output=dump(gated),
            output_model=AssetSelection.__name__,
            actual_cost=media.run.actual_cost,
        )
        m.research_brief_ref = f"agent_run://{research.run.id}"
        m.style_bible_ref = f"agent_run://{treatment.run.id}"
        approved = [c for c in gated.candidates if c.rights_status == RightsStatus.APPROVED]
        m.provenance_refs = sorted({*m.provenance_refs, *(c.source_url for c in approved)})
        self._audit(
            m,
            "system",
            "rights_gate_applied",
            {
                "selected": gated.selected_ids,
                "blocked": gated.blocked,
                "intended_use": intended_use,
            },
        )
        self._sync_budget(m)
        return StepOutcome(
            m,
            S.SCRIPTING,
            "Research, treatment and media discovery complete",
            {
                "claims": len(research.output.claims),
                "approved_assets": len(gated.selected_ids),
                "blocked_assets": len(gated.blocked),
            },
        )

    def _apply_rights_gate(self, selection: AssetSelection, intended_use: str) -> AssetSelection:
        candidates = []
        blocked: dict[str, str] = {}
        for cand in selection.candidates:
            decision = self.rt.rights_gate.evaluate(cand.license, intended_use=intended_use)
            candidates.append(cand.model_copy(update={"rights_status": decision.status}))
            if decision.status != RightsStatus.APPROVED:
                reasons = "; ".join(decision.reasons) or "no reason given"
                blocked[cand.candidate_id] = f"{decision.status.value}: {reasons}"
        approved = {c.candidate_id for c in candidates if c.rights_status == RightsStatus.APPROVED}
        return AssetSelection(
            candidates=candidates,
            selected_ids=[cid for cid in selection.selected_ids if cid in approved],
            blocked=blocked,
        )

    def _script(self, m: ProductionManifest) -> StepOutcome:
        theme, policy = self.theme_for(m), self.policy_for(m)
        script = self._invoke(
            m,
            theme,
            policy,
            A.SCRIPTWRITER,
            ScriptInput(
                brief=m.creative_brief,
                treatment=self._artifact(m, CreativeTreatment),
                research=self._artifact(m, ResearchBrief),
                assets=self._artifact(m, AssetSelection),
                scene_count=target_scene_count(theme, m.output.duration_target_sec),
                duration_target_sec=m.output.duration_target_sec,
                excluded_claim_ids=sorted(rejected_claim_ids(m)),
                persona=self.persona_for(m),
                canon=self.canon_for(m),
            ),
            attempt=script_revision(m),
        ).output
        self._sync_budget(m)
        return StepOutcome(
            m,
            S.STORYBOARDING,
            "Script complete",
            {
                "lines": len(script.lines),
                "word_count": script.word_count,
                "revision": script_revision(m),
            },
        )

    def _storyboard(self, m: ProductionManifest) -> StepOutcome:
        theme, policy = self.theme_for(m), self.policy_for(m)
        script = self._artifact(m, Script)
        graph: SceneGraph = self._invoke(
            m,
            theme,
            policy,
            A.SCENE_DIRECTOR,
            SceneDirectionInput(
                script=script,
                treatment=self._artifact(m, CreativeTreatment),
                assets=self._artifact(m, AssetSelection),
                output=m.output,
                mode_policy=policy,
                max_shots_per_scene=theme.production.max_shots_per_scene,
                persona=self.persona_for(m),
            ),
            attempt=script_revision(m),
        ).output
        m = self._with_scenes(m, graph.scenes)
        m.captions = [self._captions(m)]
        palette = theme.direction.sound_palette
        m.soundtrack = Soundtrack(
            music_cue=palette[1] if len(palette) > 1 else (palette[0] if palette else None),
            ambience=palette[0] if palette else None,
        )

        rules = theme.production.generative
        if rules is not None:
            m.approval_stage = ApprovalStage.SCRIPT
            estimate = estimate_vlog(m, rules, policy, self.rt.price_catalog)
        else:
            estimate = self.rt.cost_estimator.estimate(m, policy)
        cost_plan: CostPlan = self._invoke(
            m,
            theme,
            policy,
            A.COST_OPTIMIZER,
            CostPlanningInput(manifest=m, mode_policy=policy, estimate=estimate),
            attempt=script_revision(m),
        ).output
        self._apply_estimate(m, estimate)
        if rules is None:
            # Vlogs are bounded by the credit cap instead; redos make scene shares moot.
            self._allocate_scene_budgets(m)
        self._sync_budget(m)

        total, limit = estimate.total_estimated, m.budget.limit
        payload = {
            "scenes": len(m.scenes),
            "shots": sum(len(s.shots) for s in m.scenes),
            "estimated": float(total),
            "limit": float(limit),
            "within_budget": cost_plan.within_budget,
        }
        # Deterministic gate: the estimate is compared to the cap by code, not by the agent.
        if total > limit:
            pause = {
                "step": S.STORYBOARDING.value,
                "requested": float(total),
                "available": float(limit),
                "reason": "estimate_exceeds_limit",
            }
            self._audit(m, "system", "budget_paused", pause)
            return StepOutcome(
                m,
                S.PAUSED_BUDGET,
                f"Estimate {total} exceeds budget cap {limit}",
                payload,
                [("budget_paused", f"Estimate {total} exceeds budget cap {limit}", pause)],
            )
        return StepOutcome(m, S.AWAITING_APPROVAL, "Storyboard and cost plan ready", payload)

    def _generate(self, m: ProductionManifest) -> StepOutcome:
        theme, policy = self.theme_for(m), self.policy_for(m)
        if theme.production.fully_generative:
            return self.studio.generate(m, theme, policy)
        try:
            for scene in m.scenes:
                for shot in scene.shots:
                    if shot.status in _DONE:
                        continue
                    self._ensure_still(m, S.GENERATING)
                    self._produce_shot(m, theme, policy, scene, shot)
                    self._sync_costs(m)
                    self.rt.productions.save(m)
                if all(sh.status in _DONE for sh in scene.shots):
                    scene.status = WorkStatus.COMPLETE

            self._ensure_still(m, S.GENERATING)
            audio = self._produce_audio(m, theme, policy)
            self._sync_costs(m, self._apply_audio(m, audio))
        except Exception:
            self._sync_costs(m)
            self.rt.productions.save(m)
            raise
        attempts = sum(len(sh.attempts) for sh in m.iter_shots())
        return StepOutcome(
            m,
            S.ASSEMBLING,
            "All shots and audio generated",
            {"shots": sum(1 for _ in m.iter_shots()), "attempts": attempts},
        )

    def _produce_shot(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
    ) -> None:
        max_attempts = policy.max_attempts_per_shot
        first = len(shot.attempts) + 1
        last_failure = shot.attempts[-1] if shot.attempts else None
        retry_reason = (
            last_failure.error if last_failure and last_failure.status == "failed" else None
        )
        if first > max_attempts:
            shot.status = WorkStatus.FAILED
            scene.status = WorkStatus.FAILED
            raise ShotFailedError(shot.id, len(shot.attempts), retry_reason or "attempts exhausted")
        plan = shot.provider_plan
        for attempt in range(first, max_attempts + 1):
            shot.status = WorkStatus.IN_PROGRESS
            scene.status = WorkStatus.IN_PROGRESS
            try:
                inv = self._invoke(
                    m,
                    theme,
                    policy,
                    A.VISUAL_PRODUCTION,
                    ShotProductionInput(
                        scene_id=scene.id, shot=shot, attempt=attempt, retry_reason=retry_reason
                    ),
                    scope=shot.id,
                    attempt=attempt,
                    estimated_cost=shot.estimated_cost,
                )
            except ProviderError as exc:
                shot.attempts.append(
                    ProviderAttempt(
                        attempt=attempt,
                        provider=plan.provider,
                        model=plan.model,
                        status="failed",
                        error=str(exc)[:500],
                    )
                )
                shot.actual_cost = money(sum((a.cost for a in shot.attempts), Decimal(0)))
                retry_reason = str(exc)[:500]
                if exc.retryable and attempt < max_attempts:
                    log.info("shot %s attempt %s failed (%s); retrying", shot.id, attempt, exc)
                    self.rt.productions.save(m)
                    continue
                shot.status = WorkStatus.FAILED
                scene.status = WorkStatus.FAILED
                raise ShotFailedError(shot.id, attempt, str(exc)) from exc
            ref: RenderedShotRef = inv.output
            request_id = next(
                (
                    e.provider_request_id
                    for e in inv.ledger_events
                    if e.event_id == ref.ledger_event_id
                ),
                None,
            )
            shot.attempts.append(
                ProviderAttempt(
                    attempt=attempt,
                    provider=ref.provider,
                    model=ref.model,
                    status="succeeded",
                    provider_request_id=request_id,
                    ledger_event_id=ref.ledger_event_id,
                    cost=ref.cost,
                    output_asset_id=ref.asset_id,
                )
            )
            shot.actual_cost = money(sum((a.cost for a in shot.attempts), Decimal(0)))
            if ref.asset_id and all(a.asset_id != ref.asset_id for a in shot.assets):
                shot.assets.append(AssetRef(asset_id=ref.asset_id, role=AssetRole.GENERATED))
            shot.artifact_hash = ref.asset_id
            shot.status = WorkStatus.COMPLETE
            return

    def _produce_audio(
        self, m: ProductionManifest, theme: ThemeProfile, policy: ProductionModePolicy
    ) -> AudioPackage:
        """A8 once per scene (narration + lip-sync) and once for the music bed, each with
        the shots' bounded retry policy, so a failed line retries alone. Succeeded runs
        are reused when GENERATING resumes."""
        script = self._artifact(m, Script)
        language = m.creative_brief.language
        tracks, alignments = [], []
        for scene in m.scenes:
            self._ensure_still(m, S.GENERATING)
            payload = AudioInput(
                scenes=[scene], script=script, language=language, include_music=False
            )
            part = self._audio_with_retries(m, theme, policy, payload, scope=scene.id)
            tracks += part.tracks
            alignments += part.alignments
        self._ensure_still(m, S.GENERATING)
        music = AudioInput(
            scenes=m.scenes, script=script, language=language, include_narration=False
        )
        part = self._audio_with_retries(m, theme, policy, music, scope="music")
        return AudioPackage(tracks=[*tracks, *part.tracks], alignments=alignments)

    def _audio_with_retries(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        payload: AudioInput,
        *,
        scope: str,
    ) -> AudioPackage:
        max_attempts = policy.max_attempts_per_shot
        for attempt in range(1, max_attempts + 1):
            try:
                return self._invoke(
                    m, theme, policy, A.AUDIO_PERFORMANCE, payload, scope=scope, attempt=attempt
                ).output
            except ProviderError as exc:
                if not exc.retryable or attempt == max_attempts:
                    raise WorkflowError(
                        f"audio {scope} failed after {attempt} attempt(s): {exc}"
                    ) from exc
                log.info("audio %s attempt %s failed (%s); retrying", scope, attempt, exc)
                self._audit(
                    m,
                    A.AUDIO_PERFORMANCE.value,
                    "audio_retry",
                    {"scope": scope, "attempt": attempt, "error": str(exc)},
                )
                self.rt.productions.save(m)
        raise WorkflowError("audio produced no result")  # pragma: no cover

    @staticmethod
    def _apply_audio(m: ProductionManifest, audio: AudioPackage) -> dict[str, Decimal]:
        """Bind audio assets to the manifest; returns audio cost per scene."""
        for track in audio.tracks:
            if track.kind == "music" and m.soundtrack is not None:
                m.soundtrack.music_asset_id = track.asset_id
            scene = m.find_scene(track.scene_id) if track.scene_id else None
            if scene is None or not track.asset_id:
                continue
            first = scene.shots[0]
            if all(a.asset_id != track.asset_id for a in first.assets):
                first.assets.append(AssetRef(asset_id=track.asset_id, role=AssetRole.AUDIO))
        return {
            sid: money(sum((t.cost for t in audio.tracks if t.scene_id == sid), Decimal(0)))
            for sid in {t.scene_id for t in audio.tracks if t.scene_id}
        }

    def _assemble(self, m: ProductionManifest) -> StepOutcome:
        if m.master_render_asset_id is None:
            job_id = f"{m.production_id}:{S.ASSEMBLING.value}:render"
            self._audit(m, "system", "render_requested", {"job_id": job_id})
            self.rt.productions.save(m)
            self.rt.queue.enqueue(
                QUEUE_MEDIA,
                JOB_RENDER_MASTER,
                {
                    "production_id": m.production_id,
                    "tenant_id": m.tenant_id,
                    "idempotency_key": job_id,
                },
                job_id=job_id,
            )
            self._event(m, "render_requested", "Master render queued", {"job_id": job_id})
            return StepOutcome(m, None, "Waiting for master render")
        return StepOutcome(
            m,
            S.REVIEWING,
            "Master render available",
            {"master_render_asset_id": m.master_render_asset_id},
        )

    def _review(self, m: ProductionManifest) -> StepOutcome:
        theme, policy = self.theme_for(m), self.policy_for(m)
        master = self.master_render(m)
        self._sync_budget(m)
        report = self._invoke(
            m,
            theme,
            policy,
            A.EDITOR_QC,
            ReviewInput(
                manifest=m, research=self._artifact(m, ResearchBrief, required=False), master=master
            ),
        ).output
        m.review_findings = list(report.findings)
        m.review_status = report.status
        self._sync_budget(m)
        critical = [f for f in report.findings if f.blocking]
        payload = {
            "status": report.status.value,
            "findings": len(report.findings),
            "critical": len(critical),
        }
        if critical or report.status != ReviewStatus.PASSED:
            self._audit(m, A.EDITOR_QC.value, "review_failed", payload)
            return StepOutcome(
                m,
                S.NEEDS_REVIEW,
                f"QC found {len(critical)} blocking issue(s)",
                payload,
                [("review_failed", f"QC found {len(critical)} blocking issue(s)", payload)],
            )
        self._audit(m, A.EDITOR_QC.value, "review_passed", payload)
        return StepOutcome(m, S.READY, "QC passed", payload)

    # ================================================================== helpers
    def _lines_citing(self, m: ProductionManifest, claim_ids: set[str]) -> set[int]:
        if not claim_ids:
            return set()
        script = self._artifact(m, Script, required=False)
        if script is None:
            return set()
        return {line.scene_order for line in script.lines if claim_ids & set(line.claim_ids)}

    def _check_claims_for_approval(self, m: ProductionManifest) -> None:
        blocking = self._lines_citing(m, rejected_claim_ids(m))
        if blocking:
            scenes = ", ".join(str(n) for n in sorted(blocking))
            raise ApprovalBlockedError(
                f"script scene(s) {scenes} cite rejected claims; request a script rewrite first"
            )

    def master_render(self, m: ProductionManifest) -> MasterRender | None:
        """MasterRender from the media job's AgentRun (EDITOR_QC / ASSEMBLING), else from
        the AssetRecord referenced by ``master_render_asset_id``."""
        if m.master_render_asset_id is None:
            return None
        runs = [
            r
            for r in self.rt.agent_runs.list_for_production(m.production_id, m.tenant_id)
            if r.status == AgentRunStatus.SUCCEEDED
            and r.output_model == MasterRender.__name__
            and r.output
        ]
        matching = [r for r in runs if r.output.get("asset_id") == m.master_render_asset_id]
        chosen = (matching or runs or [None])[-1]
        if chosen is not None:
            return load(MasterRender, chosen.output)
        record = self.rt.assets.get(m.master_render_asset_id, m.tenant_id)
        if record is None:
            return None
        meta = record.metadata or {}
        return MasterRender(
            asset_id=record.id,
            uri=record.uri,
            duration_sec=record.duration_sec or 0.0,
            width=record.width or 0,
            height=record.height or 0,
            fps=float(meta.get("fps", m.output.fps)),
            codec=str(meta.get("codec") or meta.get("video_codec") or "unknown"),
            audio_codec=meta.get("audio_codec"),
            size_bytes=record.size_bytes,
            sha256=record.sha256,
            probe={"source": "asset_record", **meta},
        )

    def _invoke(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        agent_id: AgentId,
        payload: BaseModel,
        *,
        scope: str = "production",
        attempt: int = 1,
        estimated_cost: Decimal | None = None,
    ) -> Invocation:
        definition = agent_definition(agent_id)
        key = f"{m.production_id}:{m.state.value}:{agent_id.value}:{scope}:{attempt}"
        run = self.rt.agent_runs.start(
            AgentRun(
                id=new_id("run"),
                production_id=m.production_id,
                tenant_id=m.tenant_id,
                agent_id=agent_id,
                step=m.state,
                status=AgentRunStatus.RUNNING,
                attempt=attempt,
                idempotency_key=key,
                prompt_template_id=definition.prompt_template_id,
                prompt_template_version=definition.prompt_template_version,
                input_summary=summarize_payload(payload),
                estimated_cost=money(estimated_cost or 0),
            )
        )
        agent = self.rt.agents.get(agent_id)
        if run.status == AgentRunStatus.SUCCEEDED and run.output is not None:
            log.info("reusing succeeded agent run %s", key)
            return Invocation(load(agent.output_model, run.output), run, reused=True)
        ctx = AgentContext(
            production_id=m.production_id,
            tenant_id=m.tenant_id,
            manifest=m.model_copy(deep=True),
            theme=theme,
            mode_policy=policy,
            providers=self.rt.providers,
            paid_calls=self.rt.paid_calls,
            idempotency_key=key,
            attempt=attempt,
            extras={LEDGER_EVENTS: []},
        )
        try:
            output = self.rt.agents.invoke(agent_id, ctx, payload)
        except Exception as exc:
            self.rt.agent_runs.finish(
                run.id,
                status=AgentRunStatus.FAILED,
                error=f"{type(exc).__name__}: {exc}"[:2000],
                actual_cost=_sum_actual(ctx.extras.get(LEDGER_EVENTS, [])),
            )
            raise
        events: list[LedgerEvent] = list(ctx.extras.get(LEDGER_EVENTS, []))
        finished = self.rt.agent_runs.finish(
            run.id,
            status=AgentRunStatus.SUCCEEDED,
            output=dump(output),
            output_model=type(output).__name__,
            actual_cost=_sum_actual(events),
        )
        return Invocation(output, finished, events)

    def _artifact(self, m: ProductionManifest, model: type[BaseModel], *, required: bool = True):
        runs = self.rt.agent_runs.list_for_production(m.production_id, m.tenant_id)
        for run in reversed(runs):
            if (
                run.status == AgentRunStatus.SUCCEEDED
                and run.output_model == model.__name__
                and run.output is not None
            ):
                return load(model, run.output)
        if required:
            raise WorkflowError(f"{m.production_id}: missing {model.__name__} artifact")
        return None

    def _with_scenes(self, m: ProductionManifest, scenes: list[Scene]) -> ProductionManifest:
        data = m.model_dump(exclude_computed_fields=True)
        data["scenes"] = [s.model_dump(exclude_computed_fields=True) for s in scenes]
        return ProductionManifest.model_validate(data)

    @staticmethod
    def _captions(m: ProductionManifest) -> CaptionTrack:
        cues: list[Caption] = []
        start = 0.0
        if any(sh.audio.dialogue_text for sh in m.iter_shots()):
            for shot in m.iter_shots():
                if shot.audio.dialogue_text:
                    cues += _spoken_cues(shot.audio.dialogue_text, start, shot.duration_sec)
                start = round(start + shot.duration_sec, 2)
            return CaptionTrack(language=m.creative_brief.language, burn_in=True, cues=cues)
        for scene in m.scenes:
            end = round(start + scene.duration_sec, 2)
            if scene.narration:
                cues.append(Caption(start_sec=round(start, 2), end_sec=end, text=scene.narration))
            start = end
        return CaptionTrack(language=m.creative_brief.language, burn_in=True, cues=cues)

    @staticmethod
    def _apply_estimate(m: ProductionManifest, estimate: CostEstimate) -> None:
        for scene in m.scenes:
            for shot in scene.shots:
                shot.estimated_cost = money(
                    sum(
                        (li.estimated_cost for li in estimate.line_items if li.shot_id == shot.id),
                        Decimal(0),
                    )
                )
            scene_lines = sum(
                (li.estimated_cost for li in estimate.line_items if li.scene_id == scene.id),
                Decimal(0),
            )
            scene.estimated_cost = money(estimate.by_scene.get(scene.id, scene_lines))
        m.budget.estimated = money(estimate.total_estimated)

    def _allocate_scene_budgets(self, m: ProductionManifest) -> None:
        """Per-scene runaway caps: the scene's estimate share of the production cap, with
        headroom for costs the estimate cannot attribute. The production cap stays the
        hard ceiling, so scene caps may sum to more than it."""
        if not m.scenes:
            return
        limit = m.budget.limit
        total = sum((s.estimated_cost for s in m.scenes), Decimal(0))
        for scene in m.scenes:
            share = (scene.estimated_cost / total) if total > 0 else Decimal(1) / len(m.scenes)
            scene_limit = min(limit, _floor_money(limit * share * SCENE_BUDGET_HEADROOM))
            self.rt.budget.set_limit(m.production_id, scene_limit, scene_id=scene.id)
            scene.budget_limit = scene_limit

    def _set_production_limit(self, m: ProductionManifest, new_limit: Decimal) -> None:
        old = m.budget.limit
        self.rt.budget.set_limit(m.production_id, new_limit)
        m.budget.limit = new_limit
        if old <= 0:
            return
        factor = new_limit / old
        for scene in m.scenes:
            if scene.budget_limit is None:
                continue
            scaled = min(new_limit, _floor_money(scene.budget_limit * factor))
            budget = self.rt.budget.set_limit(m.production_id, scaled, scene_id=scene.id)
            scene.budget_limit = money(budget.limit_amount)

    def _sync_budget(self, m: ProductionManifest) -> None:
        budget = self.rt.budget.get_budget(m.production_id)
        if budget is None:
            return
        m.budget.limit = money(budget.limit_amount)
        m.budget.reserved = money(budget.reserved_amount)
        m.budget.actual = money(budget.actual_amount)

    def _sync_costs(self, m: ProductionManifest, audio: dict[str, Decimal] | None = None) -> None:
        audio = audio or {}
        for scene in m.scenes:
            shots = sum((sh.actual_cost for sh in scene.shots), Decimal(0))
            scene.actual_cost = money(shots + audio.get(scene.id, Decimal(0)))
        self._sync_budget(m)

    def _ensure_still(self, m: ProductionManifest, state: ProductionState) -> None:
        current = self.rt.productions.get(m.production_id, m.tenant_id)
        if current is None or current.state != state:
            raise _Interrupted()

    def _command_transition(
        self,
        m: ProductionManifest,
        to_state: ProductionState,
        reason: str,
        action: str,
        details: dict[str, Any] | None = None,
        *,
        actor: str = "operator",
    ) -> ProductionManifest:
        assert_transition(m.state, to_state)
        self._audit(m, actor, action, {"from_state": m.state.value, **(details or {})})
        self.rt.productions.save(m)
        return self.rt.productions.transition(
            m.production_id, m.tenant_id, to_state, reason=reason, payload=details or {}
        )

    def _enqueue_advance(self, m: ProductionManifest) -> str:
        n = sum(
            1
            for e in self.rt.productions.events(m.production_id, m.tenant_id)
            if e.event_type == "state_changed" and e.to_state == m.state
        )
        job_id = f"{m.production_id}:{m.state.value}:{max(n, 1)}"
        return self.rt.queue.enqueue(
            QUEUE_AGENTS,
            JOB_ADVANCE_PRODUCTION,
            {"production_id": m.production_id, "tenant_id": m.tenant_id, "idempotency_key": job_id},
            job_id=job_id,
        )

    def _load(self, production_id: str, tenant_id: str) -> ProductionManifest:
        m = self.rt.productions.get(production_id, tenant_id)
        if m is None:
            raise NotFoundError(f"production {production_id} not found")
        return m

    @staticmethod
    def _audit(m: ProductionManifest, actor: str, action: str, details: dict[str, Any]) -> None:
        m.audit.append(AuditEntry(actor=actor, action=action, details=details))

    def _event(
        self, m: ProductionManifest, event_type: str, message: str, payload: dict[str, Any]
    ) -> None:
        self.rt.productions.add_event(
            ProductionEvent(
                production_id=m.production_id,
                tenant_id=m.tenant_id,
                event_type=event_type,
                to_state=m.state,
                message=message,
                payload=payload,
            )
        )
