"""Staged generation for fully generative (vlog) productions.

Gates, cheapest first; each one is a human approval and its quote is shown up front:

- ``script``: script + shot list + credit estimate (LLM only).
- ``preview``: one storyboard still per shot and one voice line per A-roll shot.
- ``pilot``: the first A-roll and B-roll clips, to judge motion, lip-sync and sound.
- ``final``: every remaining clip, then assembly.

Clips animate their approved still (``start_image``); A-roll clips lip-sync to the
approved voice line (``audio_references``). A redo touches one shot and one stage, and
invalidates only what was built on it. Approved public images are passed to the image
model as context references only; they never appear on screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from cineforge.agents.vlog import LIP_SYNC_PAD_SEC, max_dialogue_words
from cineforge.contracts.agents import AudioInput, RenderedShotRef, Script, ShotProductionInput
from cineforge.contracts.api import RegenerateShotRequest, StageQuote
from cineforge.contracts.common import AgentId, GenerationStrategy, money
from cineforge.contracts.cost import BudgetExceededError, LedgerEvent
from cineforge.contracts.manifest import (
    ApprovalStage,
    AssetRef,
    AssetRole,
    ProductionManifest,
    ProviderAttempt,
    ProviderPlan,
    Scene,
    Shot,
    ShotKind,
    WorkStatus,
)
from cineforge.contracts.media import AssetKind, AssetRecord, RightsStatus
from cineforge.contracts.persona import PersonaProfile
from cineforge.contracts.providers import (
    PriceUnit,
    ProviderCapability,
    ProviderError,
    ProviderStatus,
)
from cineforge.contracts.theme import GenerativeRules, ProductionModePolicy, ThemeProfile
from cineforge.contracts.workflow import ProductionState
from cineforge.cost.vlog import credits_for
from cineforge.media.ingest import latest_selection, resolve_image_url
from cineforge.orchestration import external
from cineforge.providers.http import build_http_client

if TYPE_CHECKING:
    from cineforge.orchestration.workflow import StepOutcome, WorkflowEngine

log = logging.getLogger(__name__)

S = ProductionState
G = ApprovalStage
C = ProviderCapability
STAGE_ORDER = (G.SCRIPT, G.PREVIEW, G.PILOT, G.FINAL)
VIA = "engine"
AI_LABEL = "AI-generated"
MAX_NOTE_CHARS = 400


class StudioError(RuntimeError):
    """A stage cannot run (missing still, voice or sign-in)."""


class CreditCapReachedError(BudgetExceededError):
    def __init__(self, production_id: str, used: Decimal, needed: Decimal, cap: Decimal) -> None:
        super().__init__(
            production_id=production_id, scene_id=None, requested=needed, available=cap - used
        )
        self.args = (f"credit cap reached: {used} used + {needed} needed > cap {cap} credits",)


def next_stage(stage: ApprovalStage | None) -> ApprovalStage:
    if stage is None:
        return G.PREVIEW
    index = STAGE_ORDER.index(stage)
    return STAGE_ORDER[min(index + 1, len(STAGE_ORDER) - 1)]


def stage_state(shot: Shot, stage: str) -> dict[str, Any]:
    """Per-shot progress of one stage, kept in the shot's provider plan."""
    stages = shot.provider_plan.parameters.setdefault("stages", {})
    return stages.setdefault(stage, {})


def is_done(shot: Shot, stage: str) -> bool:
    if stage == "voice" and shot.kind != ShotKind.A_ROLL:
        return True
    state = stage_state(shot, stage)
    return bool(state.get("done")) and not state.get("stale")


def pilot_shots(m: ProductionManifest, rules: GenerativeRules) -> list[Shot]:
    shots = list(m.iter_shots())
    picked: list[Shot] = []
    for kind in (ShotKind.A_ROLL, ShotKind.B_ROLL):
        first = next((s for s in shots if s.kind == kind), None)
        if first is not None and len(picked) < rules.pilot_shots:
            picked.append(first)
    for shot in shots:
        if len(picked) >= rules.pilot_shots:
            break
        if shot not in picked:
            picked.append(shot)
    return picked


def stage_work(
    m: ProductionManifest, rules: GenerativeRules, stage: ApprovalStage
) -> list[tuple[Shot, str]]:
    """(shot, call) pairs a stage still has to run."""
    if stage == G.PREVIEW:
        return [
            (shot, call)
            for shot in m.iter_shots()
            for call in ("still", "voice")
            if not is_done(shot, call)
        ]
    if stage == G.PILOT:
        return [(s, "clip") for s in pilot_shots(m, rules) if not is_done(s, "clip")]
    if stage == G.FINAL:
        return [(s, "clip") for s in m.iter_shots() if not is_done(s, "clip")]
    return []


@dataclass
class _Result:
    attempt: int
    ref_url: str | None
    asset_id: str | None
    job_id: str | None
    event: LedgerEvent | None


class VlogStudio:
    def __init__(self, engine: WorkflowEngine) -> None:
        self.e = engine
        self.rt = engine.rt
        self._refs: dict[str, list[dict[str, Any]]] = {}

    # ------------------------------------------------------------------ setup
    def rules(self, theme: ThemeProfile) -> GenerativeRules:
        rules = theme.production.generative
        if rules is None:
            raise StudioError(f"theme {theme.id} is not fully generative")
        return rules

    def persona(self, m: ProductionManifest) -> PersonaProfile | None:
        return self.e.persona_for(m)

    def live(self, m: ProductionManifest, rules: GenerativeRules) -> bool:
        """True when the theme's provider is signed in and paid calls are allowed."""
        try:
            status, _ = self.rt.providers.status(rules.provider, m.tenant_id)
        except LookupError:
            return False
        return status == ProviderStatus.READY

    def voice(self, m: ProductionManifest, live: bool) -> dict[str, Any]:
        persona = self.persona(m)
        if not live or persona is None or not persona.voice.voice_id:
            return {}
        v = persona.voice
        return {
            "provider": v.provider,
            "model": v.model,
            "variant": v.variant,
            "voice_type": v.voice_type,
            "voice_id": v.voice_id,
            "voice_name": v.voice_name,
        }

    def blockers(self, m: ProductionManifest, theme: ThemeProfile) -> list[str]:
        """Reasons the next gate cannot be approved (live runs need sign-in and a voice)."""
        rules = self.rules(theme)
        out: list[str] = []
        if any(s.status == WorkStatus.IN_PROGRESS for s in m.iter_shots()):
            out.append("a shot is still regenerating")
        if self.rt.settings.provider_mode != "live":
            return out
        if not self.live(m, rules):
            out.append(f"sign in to {rules.provider} on the Sources page")
        persona = self.persona(m)
        if persona is not None and not persona.voice.voice_id:
            out.append(f"choose a voice for {persona.name}")
        return out

    # ------------------------------------------------------------------ quotes
    def credits_used(self, m: ProductionManifest, rules: GenerativeRules) -> Decimal:
        return external.credits_in_use(self.rt, m.production_id, rules.provider)

    def quote(self, m: ProductionManifest, theme: ThemeProfile) -> StageQuote:
        rules = self.rules(theme)
        stage = (
            next_stage(m.approval_stage)
            if m.state == S.AWAITING_APPROVAL
            else (m.approval_stage or G.PREVIEW)
        )
        work = stage_work(m, rules, stage)
        credits = sum((credits_for(rules, shot, call) for shot, call in work), Decimal(0))
        return self._quote(m, rules, stage.value, len(work), credits)

    def regenerate_quote(
        self, m: ProductionManifest, theme: ThemeProfile, shot: Shot, target: str
    ) -> StageQuote:
        rules = self.rules(theme)
        return self._quote(m, rules, f"redo:{target}", 1, credits_for(rules, shot, target))

    def _quote(
        self,
        m: ProductionManifest,
        rules: GenerativeRules,
        stage: str,
        items: int,
        credits: Decimal,
    ) -> StageQuote:
        price = self._credit_price(rules)
        return StageQuote(
            stage=stage,
            items=items,
            credits=credits,
            usd=money(credits * price),
            credits_used=self.credits_used(m, rules),
            credit_cap=Decimal(rules.credit_cap),
        )

    def _credit_price(self, rules: GenerativeRules) -> Decimal:
        entry = self.rt.price_catalog.get(rules.provider, rules.a_roll.model, PriceUnit.CREDIT)
        return entry.unit_price

    def _check_cap(
        self, m: ProductionManifest, rules: GenerativeRules, live: bool, needed: Decimal
    ) -> None:
        if not live:
            return
        used = self.credits_used(m, rules)
        cap = Decimal(rules.credit_cap)
        if used + needed > cap:
            raise CreditCapReachedError(m.production_id, used, needed, cap)

    # ------------------------------------------------------------------ stages
    def generate(
        self, m: ProductionManifest, theme: ThemeProfile, policy: ProductionModePolicy
    ) -> StepOutcome:
        from cineforge.orchestration.workflow import StepOutcome

        rules = self.rules(theme)
        stage = m.approval_stage if m.approval_stage in (G.PREVIEW, G.PILOT, G.FINAL) else G.PREVIEW
        m.approval_stage = stage
        try:
            for shot, call in stage_work(m, rules, stage):
                self.e._ensure_still(m, S.GENERATING)
                scene = self._scene_of(m, shot)
                self.run(m, theme, policy, scene, shot, call)
                self.e._sync_costs(m)
                self.rt.productions.save(m)
        except Exception:
            self.e._sync_costs(m)
            self.rt.productions.save(m)
            raise
        for scene in m.scenes:
            if all(is_done(s, "clip") for s in scene.shots):
                scene.status = WorkStatus.COMPLETE
        payload = {"stage": stage.value, "credits_used": float(self.credits_used(m, rules))}
        if stage == G.FINAL:
            return StepOutcome(m, S.ASSEMBLING, "All clips generated", payload)
        label = "Storyboard frames and voice lines" if stage == G.PREVIEW else "Pilot clips"
        message = f"{label} ready for review"
        return StepOutcome(
            m, S.AWAITING_APPROVAL, message, payload, [("stage_ready", message, payload)]
        )

    def run(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
        call: str,
        *,
        note: str | None = None,
    ) -> None:
        if call == "still":
            self._still(m, theme, policy, scene, shot, note)
        elif call == "voice":
            self._voice(m, theme, policy, scene, shot)
        else:
            self._clip(m, theme, policy, scene, shot, note)

    def regenerate(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        shot_id: str,
        req: RegenerateShotRequest,
    ) -> None:
        rules = self.rules(theme)
        shot = m.find_shot(shot_id)
        if shot is None:
            raise StudioError(f"shot {shot_id} not found")
        scene = self._scene_of(m, shot)
        if req.target == "voice":
            if shot.kind != ShotKind.A_ROLL:
                raise StudioError(f"shot {shot_id} has no voice line")
            if req.dialogue_text:
                self._set_line(shot, rules, req.dialogue_text)
                scene.duration_sec = round(sum(s.duration_sec for s in scene.shots), 2)
        self.run(m, theme, policy, scene, shot, req.target, note=req.note)
        if req.target in ("still", "voice"):
            clip = stage_state(shot, "clip")
            if clip.get("attempt"):
                clip["stale"] = True
                shot.status = WorkStatus.PLANNED
                scene.status = WorkStatus.IN_PROGRESS

    # ------------------------------------------------------------------ calls
    def _still(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
        note: str | None,
    ) -> None:
        rules = self.rules(theme)
        live = self.live(m, rules)
        params: dict[str, Any] = dict(rules.still.parameters)
        refs = self._context_refs(m, rules) if live else []
        if refs:
            params["import_urls"] = [{"url": r["url"], "role": "image_references"} for r in refs]
        plan = self._plan(
            C.IMAGE_GENERATION,
            rules,
            rules.still.model,
            live,
            shot.provider_plan.parameters.get("still_prompt") or shot.description,
            params,
        )
        result = self._visual(m, theme, policy, scene, shot, plan, "still", note)
        if result.asset_id:
            shot.assets.append(AssetRef(asset_id=result.asset_id, role=AssetRole.KEYFRAME))
        self._mark(shot, "still", result, context=[r["candidate_id"] for r in refs])

    def _clip(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
        note: str | None,
    ) -> None:
        rules = self.rules(theme)
        live = self.live(m, rules)
        a_roll = shot.kind == ShotKind.A_ROLL
        model = rules.a_roll if a_roll else rules.b_roll
        params: dict[str, Any] = dict(model.parameters)
        if live:
            still = self._job(shot, "still", rules)
            if not still:
                raise StudioError(f"shot {shot.id} has no {rules.provider} storyboard still yet")
            medias = [{"value": still, "role": "start_image"}]
            if a_roll:
                voice = self._job(shot, "voice", rules)
                if not voice:
                    raise StudioError(f"shot {shot.id} has no {rules.provider} voice line yet")
                medias.append({"value": voice, "role": "audio_references"})
            params["medias"] = medias
        plan = self._plan(
            C.IMAGE_TO_VIDEO, rules, model.model, live, shot.provider_plan.prompt, params
        )
        result = self._visual(m, theme, policy, scene, shot, plan, "clip", note)
        if result.asset_id:
            shot.assets.append(AssetRef(asset_id=result.asset_id, role=AssetRole.GENERATED))
            shot.artifact_hash = result.asset_id
        shot.disclosure.synthetic_media = True
        shot.disclosure.label_text = shot.disclosure.label_text or AI_LABEL
        shot.status = WorkStatus.COMPLETE
        self._mark(shot, "clip", result)

    def _voice(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
    ) -> None:
        rules = self.rules(theme)
        live = self.live(m, rules)
        attempt = int(stage_state(shot, "voice").get("attempt", 0)) + 1
        credits = credits_for(rules, shot, "voice")
        self._check_cap(m, rules, live, credits)
        payload = AudioInput(
            scenes=[scene],
            script=self.e._artifact(m, Script),
            language=m.creative_brief.language,
            include_narration=False,
            include_music=False,
            dialogue_shot_id=shot.id,
            voice=self.voice(m, live),
        )
        try:
            inv = self.e._invoke(
                m, theme, policy, AgentId.AUDIO_PERFORMANCE, payload,
                scope=f"{shot.id}:voice", attempt=attempt,
                estimated_cost=money(credits * self._credit_price(rules)),
            )  # fmt: skip
        except ProviderError as exc:
            self._failed(shot, attempt, "voice", rules.voice_model, exc)
            raise
        track = inv.output.tracks[0]
        event = self._event(m, track.ledger_event_id)
        asset_id = track.asset_id
        if track.output_url and event is not None:
            record = self._store(m, event, track.output_url, AssetKind.AUDIO, track.text, {})
            asset_id = record.id
        if asset_id:
            shot.assets.append(AssetRef(asset_id=asset_id, role=AssetRole.AUDIO))
            shot.audio.dialogue_ref = asset_id
        result = _Result(
            attempt, track.output_url, asset_id, event.provider_request_id if event else None, event
        )
        self._attempt(shot, attempt, track.provider, track.model, track.cost, result)
        self._mark(shot, "voice", result)

    # ------------------------------------------------------------------ helpers
    def _plan(
        self,
        capability: ProviderCapability,
        rules: GenerativeRules,
        model: str,
        live: bool,
        prompt: str | None,
        params: dict[str, Any],
    ) -> ProviderPlan:
        return ProviderPlan(
            strategy=GenerationStrategy.GENERATIVE,
            capability=capability,
            provider=rules.provider if live else "unassigned",
            model=model if live else "unassigned",
            prompt=prompt,
            parameters=params,
        )

    def _visual(
        self,
        m: ProductionManifest,
        theme: ThemeProfile,
        policy: ProductionModePolicy,
        scene: Scene,
        shot: Shot,
        plan: ProviderPlan,
        stage: str,
        note: str | None,
    ) -> _Result:
        rules = self.rules(theme)
        live = plan.provider != "unassigned"
        credits = credits_for(rules, shot, stage)
        self._check_cap(m, rules, live, credits)
        attempt = int(stage_state(shot, stage).get("attempt", 0)) + 1
        staged = shot.model_copy(update={"provider_plan": plan})
        note = note.strip()[:MAX_NOTE_CHARS] if note else None
        try:
            inv = self.e._invoke(
                m,
                theme,
                policy,
                AgentId.VISUAL_PRODUCTION,
                ShotProductionInput(
                    scene_id=scene.id, shot=staged, attempt=attempt, stage=stage, note=note
                ),
                scope=f"{shot.id}:{stage}",
                attempt=attempt,
                estimated_cost=money(credits * self._credit_price(rules)),
            )
        except ProviderError as exc:
            self._failed(shot, attempt, stage, plan.model, exc)
            raise
        ref: RenderedShotRef = inv.output
        event = self._event(m, ref.ledger_event_id)
        asset_id = ref.asset_id
        if ref.output_url and event is not None:
            kind = AssetKind.IMAGE if stage == "still" else AssetKind.VIDEO
            context = self._refs.get(m.production_id) if stage == "still" else None
            record = self._store(
                m, event, ref.output_url, kind, ref.prompt, ref.parameters, context=context
            )
            asset_id = record.id
        job = event.provider_request_id if event else None
        result = _Result(attempt, ref.output_url, asset_id, job, event)
        self._attempt(shot, attempt, ref.provider, ref.model, ref.cost, result)
        return result

    def _store(
        self,
        m: ProductionManifest,
        event: LedgerEvent,
        url: str,
        kind: AssetKind,
        prompt: str | None,
        parameters: dict[str, Any],
        *,
        context: list[dict[str, Any]] | None = None,
    ) -> AssetRecord:
        done = external.find_completed_asset(self.rt, m, event.event_id)
        if done is not None:
            return done
        attribution = "; ".join(r["attribution"] for r in context or [] if r.get("attribution"))
        return external.store_result(
            self.rt,
            m,
            url=url,
            kind=kind,
            event=event,
            job_id=event.provider_request_id or event.event_id,
            prompt=prompt,
            parameters={k: v for k, v in parameters.items() if k not in ("stages", "medias")},
            credits_used=event.credits_used,
            cost=event.actual_cost,
            metadata={"context_refs": context or []},
            attribution=attribution or None,
            via=VIA,
        )

    def _event(self, m: ProductionManifest, event_id: str | None) -> LedgerEvent | None:
        if not event_id:
            return None
        return next(
            (e for e in self.rt.budget.ledger(m.production_id) if e.event_id == event_id), None
        )

    @staticmethod
    def _attempt(
        shot: Shot, attempt: int, provider: str, model: str, cost: Decimal, result: _Result
    ) -> None:
        shot.attempts.append(
            ProviderAttempt(
                attempt=attempt,
                provider=provider,
                model=model,
                status="succeeded",
                provider_request_id=result.job_id,
                ledger_event_id=result.event.event_id if result.event else None,
                cost=cost,
                output_asset_id=result.asset_id,
            )
        )
        shot.actual_cost = money(sum((a.cost for a in shot.attempts), Decimal(0)))

    @staticmethod
    def _failed(shot: Shot, attempt: int, stage: str, model: str, exc: ProviderError) -> None:
        shot.attempts.append(
            ProviderAttempt(
                attempt=attempt,
                provider=getattr(exc, "provider", None) or "unknown",
                model=model,
                status="failed",
                error=f"{stage}: {exc}"[:500],
            )
        )
        stage_state(shot, stage)["attempt"] = attempt

    @staticmethod
    def _mark(shot: Shot, stage: str, result: _Result, **extra: Any) -> None:
        state = stage_state(shot, stage)
        state.update(
            attempt=result.attempt,
            done=True,
            job=result.job_id,
            provider=result.event.provider if result.event else None,
            asset=result.asset_id,
            url=result.ref_url,
            stale=False,
            **extra,
        )

    @staticmethod
    def _job(shot: Shot, stage: str, rules: GenerativeRules) -> str | None:
        state = stage_state(shot, stage)
        if state.get("stale") or state.get("provider") != rules.provider:
            return None
        return state.get("job")

    @staticmethod
    def _set_line(shot: Shot, rules: GenerativeRules, text: str) -> None:
        line = " ".join(text.split()[: max_dialogue_words(rules)])
        shot.audio.dialogue_text = line
        words = len(line.split())
        low, high = rules.a_roll.min_sec or 2.0, rules.a_roll.max_sec or 15.0
        shot.duration_sec = round(
            max(low, min(high, words / rules.words_per_sec + LIP_SYNC_PAD_SEC)), 1
        )

    def _context_refs(self, m: ProductionManifest, rules: GenerativeRules) -> list[dict[str, Any]]:
        """Top approved public images as generator context (never shown on screen)."""
        if m.production_id in self._refs:
            return self._refs[m.production_id]
        refs: list[dict[str, Any]] = []
        self._refs[m.production_id] = refs
        if rules.max_context_refs <= 0:
            return refs
        selection = latest_selection(self.rt, m)
        approved = sorted(
            (
                c
                for c in (selection.candidates if selection else [])
                if c.rights_status == RightsStatus.APPROVED
            ),
            key=lambda c: c.score,
            reverse=True,
        )
        if not approved:
            return refs
        with build_http_client(self.rt.settings) as http:
            for cand in approved:
                if len(refs) >= rules.max_context_refs:
                    break
                url = resolve_image_url(http, cand)
                if not url:
                    continue
                lic = cand.license
                refs.append(
                    {
                        "candidate_id": cand.candidate_id,
                        "url": url,
                        "source_url": cand.source_url,
                        "license_type": lic.license_type if lic else None,
                        "attribution": lic.attribution_text if lic else None,
                    }
                )
        return refs

    @staticmethod
    def _scene_of(m: ProductionManifest, shot: Shot) -> Scene:
        for scene in m.scenes:
            if any(s.id == shot.id for s in scene.shots):
                return scene
        raise StudioError(f"shot {shot.id} has no scene")
