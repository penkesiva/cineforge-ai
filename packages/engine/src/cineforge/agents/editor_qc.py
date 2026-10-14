"""A9 Editor & QC Agent: deterministic technical / compliance review of the master.

Critical findings block delivery (production -> NEEDS_REVIEW).
"""

from __future__ import annotations

from cineforge.agents.base import BaseAgent
from cineforge.contracts.agents import AgentContext, ClaimStatus, ReviewInput
from cineforge.contracts.common import AgentId, GenerationStrategy
from cineforge.contracts.manifest import WorkStatus
from cineforge.contracts.review import (
    RetryScope,
    ReviewFinding,
    ReviewGate,
    ReviewReport,
    ReviewScore,
    ReviewStatus,
    Severity,
)

DURATION_TOLERANCE_SEC = 0.5
_CODEC_ALIASES = {"h264": {"h264", "avc", "avc1", "libx264"}, "h265": {"h265", "hevc", "libx265"}}


def _codec_matches(expected: str, actual: str) -> bool:
    expected, actual = expected.lower(), actual.lower()
    return actual == expected or actual in _CODEC_ALIASES.get(expected, set())


class EditorQCAgent(BaseAgent):
    agent_id = AgentId.EDITOR_QC
    input_model = ReviewInput
    output_model = ReviewReport

    def execute(self, ctx: AgentContext, payload: ReviewInput) -> ReviewReport:
        m = payload.manifest
        prompt = self.render_prompt(
            ctx,
            production_id=m.production_id,
            scene_count=len(m.scenes),
            duration_sec=m.output.duration_target_sec,
            resolution=f"{m.output.width}x{m.output.height}",
            codec=m.output.codec,
            qc_thresholds=ctx.theme.production.qc_thresholds,
        )
        self._llm(ctx, prompt, "review", max_tokens=600)

        findings: list[ReviewFinding] = []
        findings += self._check_master(payload)
        findings += self._check_shots(payload)
        findings += self._check_disclosure(payload)
        findings += self._check_claims(payload)
        findings += self._check_budget(payload)

        def score(gates: set[ReviewGate]) -> float:
            relevant = [f for f in findings if f.gate in gates]
            if any(f.severity == Severity.CRITICAL for f in relevant):
                return 0.0
            return max(0.0, 1.0 - 0.15 * sum(f.severity == Severity.MAJOR for f in relevant))

        scores = [
            ReviewScore(dimension="technical", score=score({ReviewGate.MASTER})),
            ReviewScore(dimension="continuity", score=score({ReviewGate.SCENE})),
            ReviewScore(
                dimension="compliance",
                score=score({ReviewGate.RESEARCH, ReviewGate.MEDIA}),
            ),
            ReviewScore(dimension="budget", score=score({ReviewGate.BUDGET})),
            ReviewScore(
                dimension="narrative",
                score=0.8 if m.scenes else 0.0,
                notes="Deterministic Phase 0 heuristic (no model judgement).",
            ),
        ]
        blocking = any(f.severity == Severity.CRITICAL for f in findings)
        if not findings:
            findings.append(
                ReviewFinding(
                    gate=ReviewGate.MASTER,
                    severity=Severity.INFO,
                    message="All automated QC checks passed.",
                )
            )
        return ReviewReport(
            production_id=m.production_id,
            status=ReviewStatus.FAILED if blocking else ReviewStatus.PASSED,
            findings=findings,
            scores=scores,
        )

    # ------------------------------------------------------------------ checks
    @staticmethod
    def _check_master(payload: ReviewInput) -> list[ReviewFinding]:
        m, master = payload.manifest, payload.master
        if master is None:
            return [
                ReviewFinding(
                    gate=ReviewGate.MASTER,
                    severity=Severity.CRITICAL,
                    message="Master render is missing.",
                    recommended_fix="Re-run the media render job.",
                    retry_scope=RetryScope.PRODUCTION,
                )
            ]
        problems: list[str] = []
        if (master.width, master.height) != (m.output.width, m.output.height):
            problems.append(
                f"resolution {master.width}x{master.height} != {m.output.width}x{m.output.height}"
            )
        if not _codec_matches(m.output.codec, master.codec):
            problems.append(f"codec {master.codec} != {m.output.codec}")
        target = m.output.duration_target_sec
        if abs(master.duration_sec - target) > DURATION_TOLERANCE_SEC:
            problems.append(
                f"duration {master.duration_sec:.2f}s != {target:.2f}s "
                f"(tolerance {DURATION_TOLERANCE_SEC}s)"
            )
        if not problems:
            return []
        return [
            ReviewFinding(
                gate=ReviewGate.MASTER,
                severity=Severity.CRITICAL,
                message="Master render does not match the output profile.",
                evidence=problems,
                affected_artifact_ids=[master.asset_id],
                recommended_fix="Re-render the master with the manifest output profile.",
                retry_scope=RetryScope.PRODUCTION,
            )
        ]

    @staticmethod
    def _check_shots(payload: ReviewInput) -> list[ReviewFinding]:
        incomplete = [
            sh.id
            for sh in payload.manifest.iter_shots()
            if sh.status not in (WorkStatus.COMPLETE, WorkStatus.APPROVED)
        ]
        if not incomplete:
            return []
        return [
            ReviewFinding(
                gate=ReviewGate.SCENE,
                severity=Severity.CRITICAL,
                message=f"{len(incomplete)} shot(s) are not complete.",
                affected_artifact_ids=incomplete,
                recommended_fix="Regenerate the affected shots.",
                retry_scope=RetryScope.SHOT,
            )
        ]

    @staticmethod
    def _check_disclosure(payload: ReviewInput) -> list[ReviewFinding]:
        missing = []
        for sh in payload.manifest.iter_shots():
            synthetic = (
                sh.disclosure.synthetic_media
                or sh.provider_plan.strategy == GenerationStrategy.GENERATIVE
            )
            if synthetic and not (sh.disclosure.synthetic_media and sh.disclosure.label_text):
                missing.append(sh.id)
        if not missing:
            return []
        return [
            ReviewFinding(
                gate=ReviewGate.MEDIA,
                severity=Severity.CRITICAL,
                message="Synthetic shots are missing an on-screen disclosure label.",
                affected_artifact_ids=missing,
                recommended_fix="Add disclosure labels before delivery.",
                retry_scope=RetryScope.SHOT,
            )
        ]

    @staticmethod
    def _check_claims(payload: ReviewInput) -> list[ReviewFinding]:
        used = {(c, s.id) for s in payload.manifest.scenes for c in s.facts}
        if not used:
            return []
        if payload.research is None:
            return [
                ReviewFinding(
                    gate=ReviewGate.RESEARCH,
                    severity=Severity.MAJOR,
                    message="Scenes cite claims but no research brief was provided for review.",
                )
            ]
        claims = {c.id: c for c in payload.research.claims}
        findings: list[ReviewFinding] = []
        bad = sorted(
            {
                (cid, sid)
                for cid, sid in used
                if cid in claims
                and claims[cid].status not in (ClaimStatus.VERIFIED, ClaimStatus.DRAMATIZED)
            }
        )
        if bad:
            findings.append(
                ReviewFinding(
                    gate=ReviewGate.RESEARCH,
                    severity=Severity.CRITICAL,
                    message="Scenes use claims that are neither verified nor flagged dramatized.",
                    evidence=[f"{cid}: {claims[cid].status.value}" for cid, _ in bad],
                    affected_artifact_ids=sorted({sid for _, sid in bad}),
                    recommended_fix="Replace or verify the claims, or flag them as dramatized.",
                    retry_scope=RetryScope.SCENE,
                )
            )
        unknown = sorted({(cid, sid) for cid, sid in used if cid not in claims})
        if unknown:
            findings.append(
                ReviewFinding(
                    gate=ReviewGate.RESEARCH,
                    severity=Severity.MAJOR,
                    message="Scenes reference claims missing from the research brief.",
                    evidence=[cid for cid, _ in unknown],
                    affected_artifact_ids=sorted({sid for _, sid in unknown}),
                    retry_scope=RetryScope.SCENE,
                )
            )
        return findings

    @staticmethod
    def _check_budget(payload: ReviewInput) -> list[ReviewFinding]:
        budget = payload.manifest.budget
        if budget.actual <= budget.limit:
            return []
        return [
            ReviewFinding(
                gate=ReviewGate.BUDGET,
                severity=Severity.CRITICAL,
                message=f"Actual spend {budget.actual} exceeds the hard cap {budget.limit}.",
                evidence=[f"actual={budget.actual}", f"limit={budget.limit}"],
            )
        ]
