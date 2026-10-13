"""Tests for the frozen shared contracts (ENG-02, ENG-03, state machine)."""

from __future__ import annotations

import itertools
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from cineforge.config import Settings
from cineforge.configuration import get_theme, load_mode_policies, theme_summaries
from cineforge.contracts.agents import AGENT_DEFINITIONS
from cineforge.contracts.common import AgentId, ProductionMode, money
from cineforge.contracts.manifest import ProductionManifest
from cineforge.contracts.workflow import (
    HAPPY_PATH,
    InvalidStateTransitionError,
    ProductionState,
    assert_transition,
    can_transition,
    progress_pct,
)
from cineforge.testing import sample_manifest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
S = ProductionState


def test_manifest_json_round_trip() -> None:
    manifest = sample_manifest()
    payload = manifest.model_dump_json()
    restored = ProductionManifest.model_validate_json(payload)
    assert restored == manifest
    assert len(restored.scenes) == 5
    assert restored.total_duration_sec() == pytest.approx(45)
    assert json.loads(payload)["budget"]["limit"] == 10.0  # Money serializes as a JSON number


def test_manifest_rejects_unknown_fields() -> None:
    data = sample_manifest().model_dump(mode="json")
    data["surprise"] = True
    with pytest.raises(ValidationError):
        ProductionManifest.model_validate(data)


def test_manifest_rejects_duplicate_shot_ids() -> None:
    data = sample_manifest().model_dump(mode="json")
    data["scenes"][1]["shots"][0]["id"] = data["scenes"][0]["shots"][0]["id"]
    with pytest.raises(ValidationError, match="duplicate shot ids"):
        ProductionManifest.model_validate(data)


def test_scene_shot_durations_must_sum() -> None:
    data = sample_manifest().model_dump(mode="json")
    data["scenes"][0]["shots"][0]["duration_sec"] = 1
    with pytest.raises(ValidationError, match="shot durations"):
        ProductionManifest.model_validate(data)


def test_unknown_dependency_rejected() -> None:
    data = sample_manifest().model_dump(mode="json")
    data["scenes"][0]["shots"][1]["depends_on"] = ["scene_99_shot_01"]
    with pytest.raises(ValidationError, match="unknown ids"):
        ProductionManifest.model_validate(data)


def test_dependency_tracking_is_scoped() -> None:
    manifest = sample_manifest()
    affected = manifest.dependents_of("scene_02_shot_01")
    assert affected == {"scene_02_shot_02"}
    assert manifest.dependents_of("scene_03") == {"scene_03_shot_01", "scene_03_shot_02"}


def test_happy_path_transitions() -> None:
    for current, nxt in itertools.pairwise(HAPPY_PATH):
        assert can_transition(current, nxt)
    assert progress_pct(S.DRAFT) == 0
    assert progress_pct(S.DELIVERED) == 100


@pytest.mark.parametrize(
    ("src", "dst"),
    [(S.DRAFT, S.GENERATING), (S.DELIVERED, S.DRAFT), (S.CANCELLED, S.RESEARCHING)],
)
def test_invalid_transitions(src: ProductionState, dst: ProductionState) -> None:
    with pytest.raises(InvalidStateTransitionError):
        assert_transition(src, dst)


def test_exception_and_resume_transitions() -> None:
    assert can_transition(S.GENERATING, S.PAUSED_BUDGET)
    assert can_transition(S.PAUSED_BUDGET, S.GENERATING)
    assert can_transition(S.REVIEWING, S.GENERATING)  # targeted repair
    assert can_transition(S.NEEDS_REVIEW, S.REVIEWING)
    assert not can_transition(S.FAILED, S.GENERATING)


def test_ten_agents_registered_in_contract() -> None:
    assert len(AGENT_DEFINITIONS) == 10
    assert {d.id for d in AGENT_DEFINITIONS} == set(AgentId)
    assert [d.code for d in AGENT_DEFINITIONS] == [f"A{i}" for i in range(1, 11)]


def test_configurations_load() -> None:
    cfg = Settings().configurations_dir
    assert {t.id for t in theme_summaries(cfg)} == {
        "time-traveler",
        "mystery-explorer",
        "fascinating-places",
    }
    assert get_theme(cfg, "time-traveler").version == 1
    modes = load_mode_policies(cfg)
    assert set(modes) == set(ProductionMode)
    assert modes[ProductionMode.BALANCED].default_budget_usd == Decimal("10")


def test_money_quantizes() -> None:
    assert money(0.1) + money(0.2) == Decimal("0.300000")


def test_exported_contract_schema_is_current() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_contracts.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
