"""In-process mock workflow tests (memory repos + inline queue + fakes for Workstream D)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from cineforge.contracts.agents import AgentRunStatus
from cineforge.contracts.api import ApproveProductionRequest, CreateProductionRequest
from cineforge.contracts.common import AgentId, ProductionMode, money
from cineforge.contracts.jobs import JOB_ADVANCE_PRODUCTION, JOB_RENDER_MASTER, QUEUE_MEDIA
from cineforge.contracts.manifest import WorkStatus
from cineforge.contracts.media import RightsStatus
from cineforge.contracts.repositories import NotFoundError
from cineforge.contracts.review import ReviewStatus
from cineforge.contracts.workflow import InvalidStateTransitionError, ProductionState
from cineforge.orchestration.jobs import advance_production
from cineforge.orchestration.queue import RecordingTaskQueue
from cineforge.orchestration.workflow import WorkflowEngine, parse_job_state, summarize_payload
from fakes_b import make_render_job, make_runtime

S = ProductionState
TENANT = "tenant_demo"
TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"


def _req(**kw) -> CreateProductionRequest:
    return CreateProductionRequest(**({"topic": TOPIC} | kw))


def _events(rt, pid: str) -> list[str]:
    return [e.event_type for e in rt.productions.events(pid, TENANT)]


def _states(rt, pid: str) -> list[S]:
    return [
        e.to_state for e in rt.productions.events(pid, TENANT) if e.event_type == "state_changed"
    ]


def _runs(rt, pid: str, agent: AgentId | None = None):
    runs = rt.agent_runs.list_for_production(pid, TENANT)
    return [r for r in runs if agent is None or r.agent_id == agent]


# --------------------------------------------------------------------------- happy path
def test_full_mock_workflow_draft_to_delivered() -> None:
    rt, fx = make_runtime()
    wf = WorkflowEngine(rt)
    m = wf.create_production(_req(), TENANT)
    pid = m.production_id
    assert m.state == S.DRAFT
    assert m.budget.limit == money(10)
    assert fx.budget.get_budget(pid).limit_amount == money(10)
    assert _events(rt, pid) == ["created"]

    started = wf.start(pid, TENANT)
    assert started.manifest.state == S.RESEARCHING
    assert started.job_id == f"{pid}:RESEARCHING:1"

    m = rt.productions.get(pid, TENANT)
    assert m.state == S.AWAITING_APPROVAL
    assert _states(rt, pid) == [S.RESEARCHING, S.SCRIPTING, S.STORYBOARDING, S.AWAITING_APPROVAL]
    # Agents run so far, in contract order for RESEARCHING.
    agents = [r.agent_id for r in _runs(rt, pid)]
    assert agents == [
        AgentId.MASTER_ORCHESTRATOR,
        AgentId.CREATIVE_DIRECTOR,
        AgentId.RESEARCH,
        AgentId.MEDIA_DISCOVERY,
        AgentId.SCRIPTWRITER,
        AgentId.SCENE_DIRECTOR,
        AgentId.COST_OPTIMIZER,
    ]
    assert all(r.status == AgentRunStatus.SUCCEEDED for r in _runs(rt, pid))
    assert all(r.prompt_template_id == r.agent_id.value for r in _runs(rt, pid))
    assert _runs(rt, pid, AgentId.MASTER_ORCHESTRATOR)[0].idempotency_key == (
        f"{pid}:RESEARCHING:a1_master_orchestrator:production:1"
    )
    assert _runs(rt, pid, AgentId.RESEARCH)[0].actual_cost > 0

    # Rights gate rewrote the selection: NC and unknown licenses are blocked.
    media = _runs(rt, pid, AgentId.MEDIA_DISCOVERY)[0].output
    statuses = {c["candidate_id"]: c["rights_status"] for c in media["candidates"]}
    blocked = media["blocked"]
    assert len(blocked) == 2
    assert all(statuses[cid] != RightsStatus.APPROVED.value for cid in blocked)
    assert set(media["selected_ids"]).isdisjoint(blocked)
    assert any(a.action == "rights_gate_applied" for a in m.audit)

    # Storyboard + cost plan applied to the manifest.
    assert len(m.scenes) == 5
    assert m.total_duration_sec() == pytest.approx(45)
    assert m.budget.estimated > 0
    assert all(sh.estimated_cost > 0 for sh in m.iter_shots())
    scene_limits = [s.budget_limit for s in m.scenes]
    assert all(lim and lim > 0 for lim in scene_limits)
    assert all(lim <= m.budget.limit for lim in scene_limits)
    assert fx.budget.get_budget(pid, "scene_01").limit_amount == m.scenes[0].budget_limit
    assert m.captions and len(m.captions[0].cues) == 5
    selected = set(media["selected_ids"])
    bound = {a.asset_id for sh in m.iter_shots() for a in sh.assets}
    assert bound and bound <= selected

    approved = wf.approve(pid, TENANT, ApproveProductionRequest(approved_by="qa", note="ok"))
    assert approved.manifest.state == S.GENERATING
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY, _events(rt, pid)
    assert _states(rt, pid)[-4:] == [S.GENERATING, S.ASSEMBLING, S.REVIEWING, S.READY]
    assert m.approval.approved_by == "qa" and m.approval.approved_at is not None
    for shot in m.iter_shots():
        assert shot.status == WorkStatus.COMPLETE
        assert [a.status for a in shot.attempts] == ["succeeded"]
        assert shot.attempts[0].ledger_event_id and shot.attempts[0].output_asset_id
        assert shot.attempts[0].provider_request_id
        assert shot.actual_cost == shot.attempts[0].cost > 0
    assert all(s.status == WorkStatus.COMPLETE for s in m.scenes)
    assert all(s.actual_cost > 0 for s in m.scenes)
    assert m.soundtrack and m.soundtrack.music_asset_id
    assert m.master_render_asset_id
    assert m.review_status == ReviewStatus.PASSED
    assert m.review_findings and not any(f.blocking for f in m.review_findings)
    assert Decimal(0) < m.budget.actual <= m.budget.limit
    assert m.budget.actual == fx.budget.get_budget(pid).actual_amount
    assert "render_requested" in _events(rt, pid)
    assert "approved" in _events(rt, pid)
    a7 = _runs(rt, pid, AgentId.VISUAL_PRODUCTION)
    assert len(a7) == 10
    assert a7[0].idempotency_key == f"{pid}:GENERATING:a7_visual_production:scene_01_shot_01:1"
    audio = _runs(rt, pid, AgentId.AUDIO_PERFORMANCE)
    audio_scopes = [r.idempotency_key.split(":")[3] for r in audio]
    assert audio_scopes == [s.id for s in m.scenes] + ["music"]
    qc = _runs(rt, pid, AgentId.EDITOR_QC)
    assert {r.output_model for r in qc} == {"MasterRender", "ReviewReport"}
    # Every provider call went through the guard and is in the ledger.
    assert len(fx.guard.calls) == len(fx.budget.ledger(pid))
    assert fx.queue.failures == []
    executed = [j.job_id for j in fx.queue.executed]
    assert f"{pid}:ASSEMBLING:render" in executed
    assert f"{pid}:ASSEMBLING:rendered" in executed

    delivered = wf.deliver(pid, TENANT)
    assert delivered.manifest.state == S.DELIVERED
    assert rt.productions.get(pid, TENANT).state == S.DELIVERED


def test_auto_approve_runs_to_ready_without_operator() -> None:
    rt, fx = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY
    assert m.approval.approved_by == "auto"
    assert S.AWAITING_APPROVAL in _states(rt, pid)
    approved = [e for e in rt.productions.events(pid, TENANT) if e.event_type == "approved"]
    assert approved and approved[0].payload["auto"] is True
    assert fx.queue.failures == []


@pytest.mark.parametrize("mode", list(ProductionMode))
def test_every_mode_reaches_ready(mode: ProductionMode) -> None:
    rt, _ = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(mode=mode, auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY, _events(rt, pid)
    assert m.budget.actual <= m.budget.limit


# --------------------------------------------------------------------------- budget
def test_budget_exceeded_during_generation_pauses_then_resumes_with_raised_cap() -> None:
    rt, fx = make_runtime(estimator_scale=0.1)  # under-estimate so approval passes
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(budget_limit_usd=money(2)), TENANT).production_id
    wf.start(pid, TENANT)
    assert rt.productions.get(pid, TENANT).state == S.AWAITING_APPROVAL
    wf.approve(pid, TENANT, ApproveProductionRequest())
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.PAUSED_BUDGET
    paused = [e for e in rt.productions.events(pid, TENANT) if e.event_type == "budget_paused"]
    assert len(paused) == 1
    assert paused[0].payload["requested"] > paused[0].payload["available"] >= 0
    assert paused[0].payload["step"] == "GENERATING"
    assert m.budget.actual <= money(2)
    done_before = [sh.id for sh in m.iter_shots() if sh.status == WorkStatus.COMPLETE]
    failed_runs = [r for r in _runs(rt, pid) if r.status == AgentRunStatus.FAILED]
    assert failed_runs and "BudgetExceededError" in failed_runs[-1].error

    wf.approve(
        pid, TENANT, ApproveProductionRequest(approved_by="cfo", raise_budget_to_usd=money(50))
    )
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY, _events(rt, pid)
    assert m.budget.limit == money(50)
    assert fx.budget.get_budget(pid).limit_amount == money(50)
    # Shots completed before the pause were not regenerated.
    for shot_id in done_before:
        assert len(m.find_shot(shot_id).attempts) == 1
    assert all(s.budget_limit <= money(50) for s in m.scenes)
    assert fx.queue.failures == []


def test_estimate_over_cap_pauses_at_storyboard_then_approval_resumes() -> None:
    rt, _ = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(budget_limit_usd=money("0.5")), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.PAUSED_BUDGET
    paused = [e for e in rt.productions.events(pid, TENANT) if e.event_type == "budget_paused"]
    assert paused[0].payload["reason"] == "estimate_exceeds_limit"
    assert m.scenes and m.budget.estimated > m.budget.limit
    cost_plan = _runs(rt, pid, AgentId.COST_OPTIMIZER)[0].output
    assert cost_plan["within_budget"] is False

    wf.approve(pid, TENANT, ApproveProductionRequest(raise_budget_to_usd=money(30)))
    assert rt.productions.get(pid, TENANT).state == S.READY


# --------------------------------------------------------------------------- retries
def test_retryable_failure_then_success_records_two_attempts() -> None:
    rt, fx = make_runtime()
    fx.provider("mock-video").fail_times["scene_02_shot_01"] = 1
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY
    shot = m.find_shot("scene_02_shot_01")
    assert [(a.attempt, a.status) for a in shot.attempts] == [(1, "failed"), (2, "succeeded")]
    assert "simulated failure" in shot.attempts[0].error
    runs = [
        r
        for r in _runs(rt, pid, AgentId.VISUAL_PRODUCTION)
        if "scene_02_shot_01" in r.idempotency_key
    ]
    assert [(r.attempt, r.status) for r in runs] == [
        (1, AgentRunStatus.FAILED),
        (2, AgentRunStatus.SUCCEEDED),
    ]
    retry_calls = [c for c in fx.guard.calls if c[1].shot_id == "scene_02_shot_01"]
    assert [c[3] for c in retry_calls] == [1, 2]
    assert retry_calls[1][1].parameters["retry_reason"].startswith("mock-video")
    ledger = [e for e in fx.budget.ledger(pid) if e.shot_id == "scene_02_shot_01"]
    assert sorted(e.status.value for e in ledger) == ["committed", "failed"]


def test_transient_audio_failure_is_retried() -> None:
    rt, fx = make_runtime()
    fx.provider("mock-lipsync").fail_times["*"] = 1
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.READY
    runs = _runs(rt, pid, AgentId.AUDIO_PERFORMANCE)
    # Only the scene with the lip-synced hook shot retries; other lines run once.
    by_scope: dict[str, list] = {}
    for r in runs:
        by_scope.setdefault(r.idempotency_key.split(":")[3], []).append((r.attempt, r.status))
    assert by_scope.pop("scene_01") == [(1, AgentRunStatus.FAILED), (2, AgentRunStatus.SUCCEEDED)]
    assert all(v == [(1, AgentRunStatus.SUCCEEDED)] for v in by_scope.values())
    assert set(by_scope) == {s.id for s in m.scenes[1:]} | {"music"}
    retries = [a for a in m.audit if a.action == "audio_retry"]
    assert [a.details["scope"] for a in retries] == ["scene_01"]


def test_audio_exhausting_attempts_fails_production() -> None:
    rt, fx = make_runtime()
    fx.provider("mock-lipsync").fail_times["*"] = 99
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    assert rt.productions.get(pid, TENANT).state == S.FAILED
    assert len(_runs(rt, pid, AgentId.AUDIO_PERFORMANCE)) == 3


def test_shot_exhausting_attempts_fails_production() -> None:
    rt, fx = make_runtime()
    fx.provider("mock-video").fail_times["scene_02_shot_01"] = 99
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.FAILED
    shot = m.find_shot("scene_02_shot_01")
    assert len(shot.attempts) == 3  # balanced max_attempts_per_shot
    assert shot.status == WorkStatus.FAILED
    assert m.find_scene("scene_02").status == WorkStatus.FAILED
    failed = [e for e in rt.productions.events(pid, TENANT) if e.event_type == "failed"]
    assert failed[0].payload["shot_id"] == "scene_02_shot_01"
    assert failed[0].payload["attempts"] == 3
    assert m.find_shot("scene_01_shot_01").status == WorkStatus.COMPLETE  # progress kept


def test_non_retryable_failure_fails_immediately() -> None:
    rt, fx = make_runtime()
    video = fx.provider("mock-video")
    video.fail_times["scene_01_shot_01"] = 1
    video.retryable = False
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.FAILED
    assert len(m.find_shot("scene_01_shot_01").attempts) == 1


# --------------------------------------------------------------------------- idempotency
def test_re_advance_is_idempotent_and_reuses_agent_runs() -> None:
    queue = RecordingTaskQueue()
    rt, fx = make_runtime(queue=queue)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(), TENANT).production_id
    wf.start(pid, TENANT)
    assert [j.job_id for j in queue.jobs] == [f"{pid}:RESEARCHING:1"]
    job = queue.jobs[0]
    assert job.job_path == JOB_ADVANCE_PRODUCTION

    advance_production(**job.kwargs)
    assert rt.productions.get(pid, TENANT).state == S.SCRIPTING
    runs_after_first = len(_runs(rt, pid))
    calls_after_first = len(fx.guard.calls)
    assert queue.jobs[-1].job_id == f"{pid}:SCRIPTING:1"

    # Same job delivered twice: stale, no work.
    advance_production(**job.kwargs)
    assert len(_runs(rt, pid)) == runs_after_first
    assert rt.productions.get(pid, TENANT).state == S.SCRIPTING

    # Crash simulation: the step's work committed but the transition was lost.
    stored = rt.productions._items[pid]
    rt.productions._items[pid] = stored.model_copy(update={"state": S.RESEARCHING})
    advance_production(**job.kwargs)
    assert rt.productions.get(pid, TENANT).state == S.SCRIPTING
    assert len(_runs(rt, pid)) == runs_after_first  # succeeded runs reused
    assert len(fx.guard.calls) == calls_after_first  # no new provider spend


def test_advance_with_foreign_key_runs_current_state_and_unknown_production_is_noop() -> None:
    queue = RecordingTaskQueue()
    rt, _ = make_runtime(queue=queue)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(), TENANT).production_id
    wf.start(pid, TENANT)
    assert wf.advance(pid, TENANT, "media-job-without-state") is not None
    assert rt.productions.get(pid, TENANT).state == S.SCRIPTING
    assert wf.advance("prod_missing", TENANT, "x") is None
    assert parse_job_state(pid, f"{pid}:GENERATING:2") == S.GENERATING
    assert parse_job_state(pid, f"{pid}:NOPE:2") is None
    assert parse_job_state(pid, "other:GENERATING:2") is None


def test_assembling_enqueues_render_job_once_and_waits() -> None:
    queue = RecordingTaskQueue()
    rt, _ = make_runtime(queue=queue)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    while queue.jobs and queue.jobs[-1].job_path == JOB_ADVANCE_PRODUCTION:
        job = queue.jobs[-1]
        advance_production(**job.kwargs)
        if rt.productions.get(pid, TENANT).state == S.ASSEMBLING and queue.jobs[-1] is job:
            break
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.ASSEMBLING
    render = queue.jobs[-1]
    assert (render.queue, render.job_path, render.job_id) == (
        QUEUE_MEDIA,
        JOB_RENDER_MASTER,
        f"{pid}:ASSEMBLING:render",
    )
    assert render.kwargs == {
        "production_id": pid,
        "tenant_id": TENANT,
        "idempotency_key": f"{pid}:ASSEMBLING:render",
    }


# --------------------------------------------------------------------------- commands
def test_invalid_commands_raise() -> None:
    queue = RecordingTaskQueue()
    rt, _ = make_runtime(queue=queue)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(), TENANT).production_id
    with pytest.raises(InvalidStateTransitionError):
        wf.approve(pid, TENANT, ApproveProductionRequest())
    with pytest.raises(InvalidStateTransitionError):
        wf.deliver(pid, TENANT)
    wf.start(pid, TENANT)
    with pytest.raises(InvalidStateTransitionError):
        wf.start(pid, TENANT)
    with pytest.raises(NotFoundError):
        wf.start(pid, "tenant_other")
    # Rejected commands leave no audit trail behind.
    assert [a.action for a in rt.productions.get(pid, TENANT).audit] == ["created", "run_requested"]


def test_cancel_stops_pending_work() -> None:
    queue = RecordingTaskQueue()
    rt, _ = make_runtime(queue=queue)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(), TENANT).production_id
    wf.start(pid, TENANT)
    result = wf.cancel(pid, TENANT)
    assert result.manifest.state == S.CANCELLED
    advance_production(**queue.jobs[0].kwargs)
    assert rt.productions.get(pid, TENANT).state == S.CANCELLED
    assert _runs(rt, pid) == []
    with pytest.raises(InvalidStateTransitionError):
        wf.cancel(pid, TENANT)


def test_qc_failure_goes_to_needs_review() -> None:
    rt, _ = make_runtime(render_job=make_render_job(width=720, height=1280))
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(auto_approve=True), TENANT).production_id
    wf.start(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert m.state == S.NEEDS_REVIEW
    assert m.review_status == ReviewStatus.FAILED
    assert any(f.blocking and f.gate.value == "master" for f in m.review_findings)
    assert "review_failed" in _events(rt, pid)


def test_create_is_idempotent_per_tenant() -> None:
    rt, fx = make_runtime()
    wf = WorkflowEngine(rt)
    a = wf.create_production(_req(idempotency_key="k1"), TENANT)
    b = wf.create_production(_req(idempotency_key="k1"), TENANT)
    c = wf.create_production(_req(idempotency_key="k1"), "tenant_other")
    assert a.production_id == b.production_id != c.production_id
    assert fx.budget.create_calls == 2
    assert _events(rt, a.production_id) == ["created"]


def test_create_uses_mode_default_budget_and_theme_output() -> None:
    rt, _ = make_runtime()
    wf = WorkflowEngine(rt)
    m = wf.create_production(
        _req(theme_id="mystery-explorer", mode=ProductionMode.PREMIUM, duration_target_sec=50),
        TENANT,
    )
    assert m.budget.limit == money(40)
    assert m.output.duration_target_sec == 50
    assert (m.output.width, m.output.height, m.output.aspect_ratio) == (1080, 1920, "9:16")
    assert m.theme_profile.id == "mystery-explorer"
    assert m.character_bible_ref is None


def test_step_delay_sleeps_between_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    import cineforge.orchestration.workflow as workflow

    sleeps: list[float] = []
    monkeypatch.setattr(workflow.time, "sleep", sleeps.append)
    rt, _ = make_runtime(mock_step_delay_sec=0.25)
    wf = WorkflowEngine(rt)
    pid = wf.create_production(_req(), TENANT).production_id
    wf.start(pid, TENANT)
    assert sleeps == [0.25, 0.25]  # after RESEARCHING and SCRIPTING; gate stops


def test_summarize_payload_is_json_safe() -> None:
    import json

    from cineforge.contracts.agents import PlanningInput
    from cineforge.contracts.manifest import CreativeBrief

    summary = summarize_payload(
        PlanningInput(
            production_id="p",
            brief=CreativeBrief(topic=TOPIC),
            mode=ProductionMode.BALANCED,
            budget_limit=money(3),
            duration_target_sec=45,
        )
    )
    assert summary["topic"] == TOPIC and summary["budget_limit"] == 3.0
    json.dumps(summary)
