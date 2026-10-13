"""Structured QC findings (PRD 3 section 11)."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field, computed_field

from cineforge.contracts.common import ContractModel, new_id, utcnow


class Severity(StrEnum):
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"


class ReviewGate(StrEnum):
    RESEARCH = "research"
    MEDIA = "media"
    SCRIPT = "script"
    SCENE = "scene"
    AUDIO = "audio"
    MASTER = "master"
    BUDGET = "budget"


class RetryScope(StrEnum):
    NONE = "none"
    SHOT = "shot"
    SCENE = "scene"
    AUDIO = "audio"
    PRODUCTION = "production"


class ReviewStatus(StrEnum):
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    NEEDS_HUMAN = "needs_human"


class ReviewScore(ContractModel):
    dimension: str = Field(description="e.g. narrative, continuity, av_sync, technical")
    score: float = Field(ge=0, le=1)
    notes: str = ""


class ReviewFinding(ContractModel):
    id: str = Field(default_factory=lambda: new_id("finding"))
    gate: ReviewGate
    severity: Severity
    message: str
    evidence: list[str] = Field(default_factory=list)
    affected_artifact_ids: list[str] = Field(default_factory=list)
    recommended_fix: str | None = None
    retry_scope: RetryScope = RetryScope.NONE
    created_at: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def blocking(self) -> bool:
        return self.severity == Severity.CRITICAL


class ReviewReport(ContractModel):
    production_id: str
    status: ReviewStatus
    findings: list[ReviewFinding] = Field(default_factory=list)
    scores: list[ReviewScore] = Field(default_factory=list)
    reviewed_at: datetime = Field(default_factory=utcnow)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def passed(self) -> bool:
        return self.status == ReviewStatus.PASSED and not any(f.blocking for f in self.findings)
