"""Claim review at the approval gate (ENG-04), script rewrite and theme versions."""

from __future__ import annotations

import pytest
from cineforge.contracts.agents import AgentRunStatus
from cineforge.contracts.api import (
    ApproveProductionRequest,
    ClaimDecision,
    CreateProductionRequest,
    ReviewClaimsRequest,
)
from cineforge.contracts.common import AgentId
from cineforge.contracts.workflow import InvalidStateTransitionError, ProductionState
from cineforge.orchestration.workflow import (
    ApprovalBlockedError,
    InvalidClaimReviewError,
    WorkflowEngine,
    rejected_claim_ids,
    script_revision,
)
from fakes_b import make_runtime

S = ProductionState
TENANT = "tenant_demo"
TOPIC = "The night the Eiffel Tower first lit up for the 1889 World's Fair"


def _at_gate():
    rt, fx = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(CreateProductionRequest(topic=TOPIC), TENANT).production_id
    wf.start(pid, TENANT)
    assert rt.productions.get(pid, TENANT).state == S.AWAITING_APPROVAL
    return rt, fx, wf, pid


def _script_runs(rt, pid):
    return [
        r
        for r in rt.agent_runs.list_for_production(pid, TENANT)
        if r.agent_id == AgentId.SCRIPTWRITER and r.status == AgentRunStatus.SUCCEEDED
    ]


def _cited(run) -> set[str]:
    return {cid for line in run.output["lines"] for cid in line["claim_ids"]}


def _review(*decisions: tuple[str, str]) -> ReviewClaimsRequest:
    return ReviewClaimsRequest(
        reviewed_by="editor",
        decisions=[ClaimDecision(claim_id=c, decision=d) for c, d in decisions],
    )


def test_latest_decision_per_claim_wins() -> None:
    rt, _, wf, pid = _at_gate()
    wf.review_claims(pid, TENANT, _review(("claim_02", "rejected")))
    wf.review_claims(pid, TENANT, _review(("claim_02", "approved"), ("claim_03", "rejected")))
    m = rt.productions.get(pid, TENANT)
    assert len(m.claim_reviews) == 3
    assert rejected_claim_ids(m) == {"claim_03"}
    assert m.state == S.AWAITING_APPROVAL
    assert any(a.action == "claims_reviewed" for a in m.audit)
    assert "claims_reviewed" in [e.event_type for e in rt.productions.events(pid, TENANT)]


def test_unknown_claim_id_is_rejected() -> None:
    _, _, wf, pid = _at_gate()
    with pytest.raises(InvalidClaimReviewError):
        wf.review_claims(pid, TENANT, _review(("claim_99", "rejected")))


def test_claim_review_outside_gate_is_invalid() -> None:
    rt, _ = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(CreateProductionRequest(topic=TOPIC), TENANT).production_id
    with pytest.raises(InvalidStateTransitionError):
        wf.review_claims(pid, TENANT, _review(("claim_01", "rejected")))


def test_rejected_cited_claim_blocks_approval_until_rewrite() -> None:
    rt, _, wf, pid = _at_gate()
    first = _script_runs(rt, pid)[-1]
    cited = sorted(_cited(first))
    assert cited, "mock script cites claims"
    wf.review_claims(pid, TENANT, _review((cited[0], "rejected")))
    with pytest.raises(ApprovalBlockedError):
        wf.approve(pid, TENANT, ApproveProductionRequest())
    assert rt.productions.get(pid, TENANT).state == S.AWAITING_APPROVAL

    result = wf.rewrite_script(pid, TENANT)
    m = rt.productions.get(pid, TENANT)
    assert result.job_id
    assert m.state == S.AWAITING_APPROVAL  # inline queue ran script + storyboard again
    assert script_revision(m) == 2
    states = [
        e.to_state for e in rt.productions.events(pid, TENANT) if e.event_type == "state_changed"
    ]
    assert states[-4:] == [S.NEEDS_REVIEW, S.SCRIPTING, S.STORYBOARDING, S.AWAITING_APPROVAL]
    runs = _script_runs(rt, pid)
    assert len(runs) == 2 and runs[-1].attempt == 2
    assert runs[-1].idempotency_key.endswith(":production:2")
    assert cited[0] not in _cited(runs[-1])
    a6 = [r for r in rt.agent_runs.list_for_production(pid, TENANT)
          if r.agent_id == AgentId.SCENE_DIRECTOR]  # fmt: skip
    assert [r.attempt for r in a6] == [1, 2]
    for scene in m.scenes:
        assert cited[0] not in scene.facts

    approved = wf.approve(pid, TENANT, ApproveProductionRequest())
    assert approved.manifest.state == S.GENERATING
    assert rt.productions.get(pid, TENANT).state == S.READY


def test_rewrite_requires_gate_or_needs_review() -> None:
    rt, _ = make_runtime()
    wf = WorkflowEngine(rt)
    pid = wf.create_production(CreateProductionRequest(topic=TOPIC), TENANT).production_id
    with pytest.raises(InvalidStateTransitionError):
        wf.rewrite_script(pid, TENANT)


def test_re_approving_a_rejected_claim_unblocks_approval() -> None:
    rt, _, wf, pid = _at_gate()
    cited = sorted(_cited(_script_runs(rt, pid)[-1]))
    wf.review_claims(pid, TENANT, _review((cited[0], "rejected")))
    with pytest.raises(ApprovalBlockedError):
        wf.approve(pid, TENANT, ApproveProductionRequest())
    wf.review_claims(pid, TENANT, _review((cited[0], "approved")))
    assert wf.approve(pid, TENANT, ApproveProductionRequest()).manifest.state == S.GENERATING


def test_production_pins_requested_theme_version() -> None:
    rt, _ = make_runtime()
    base = rt.themes.get("time-traveler")
    edited = base.model_copy(update={"tone": "Hushed and reverent"})
    v2 = rt.themes.create_version(edited, base_version=base.version)
    assert v2.version == base.version + 1
    wf = WorkflowEngine(rt)
    latest = wf.create_production(CreateProductionRequest(topic=TOPIC), TENANT)
    pinned = wf.create_production(
        CreateProductionRequest(topic=TOPIC, theme_version=base.version), TENANT
    )
    assert latest.theme_profile.version == v2.version
    assert pinned.theme_profile.version == base.version
    assert wf.theme_for(latest).tone == "Hushed and reverent"
