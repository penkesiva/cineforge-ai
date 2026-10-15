"""Host-led vlog planning: deterministic timing, structure, prompts and disclosure."""

from __future__ import annotations

from pathlib import Path

from cineforge.agents.drafts import VlogBeatDraft, VlogScriptDraft
from cineforge.agents.vlog import (
    build_vlog_scenes,
    build_vlog_script,
    max_dialogue_words,
)
from cineforge.config import Settings
from cineforge.configuration import get_character, load_themes
from cineforge.contracts.agents import ClaimStatus, FactClaim
from cineforge.contracts.manifest import ShotKind

CFG = Path(Settings().configurations_dir)


def _theme():
    return load_themes(CFG)[("lena-vlog", 1)]


def _claims() -> list[FactClaim]:
    return [
        FactClaim(
            id="claim_1",
            text="The tower opened in March 1889.",
            status=ClaimStatus.VERIFIED,
            confidence=0.9,
        ),
        FactClaim(
            id="claim_2",
            text="Rumor: it glowed blue.",
            status=ClaimStatus.DRAMATIZED,
            confidence=0.5,
        ),
    ]


def _script(draft=None, scene_count=5):
    return build_vlog_script(
        topic="Paris 1889",
        logline="Lena visits the World's Fair",
        theme=_theme(),
        character=get_character(CFG, "lena-voss"),
        claims=_claims(),
        excluded=set(),
        scene_count=scene_count,
        draft=draft,
    )


def test_fallback_script_alternates_and_signs_off_with_dialogue() -> None:
    script = _script()
    rules = _theme().production.generative
    last_scene = [ln for ln in script.lines if ln.scene_order == 5]
    assert [ln.kind for ln in last_scene] == ["dialogue"]
    assert script.cta and script.cta in last_scene[-1].text
    assert {ln.kind for ln in script.lines} == {"dialogue", "broll"}
    for line in script.lines:
        if line.kind == "dialogue":
            assert len(line.text.split()) <= max_dialogue_words(rules)
    assert script.hook == script.lines[0].text


def test_drafted_lines_are_trimmed_and_only_verified_claims_cited_after_hook() -> None:
    long = " ".join(["word"] * 50)
    draft = VlogScriptDraft(
        hook="Okay, I'm standing in Paris in 1889.",
        beats=[
            VlogBeatDraft(scene_order=1, kind="dialogue", text="Hi!", visual="selfie close-up",
                          claim_ids=["claim_2"]),
            VlogBeatDraft(scene_order=2, kind="dialogue", text=long, visual="crowd",
                          claim_ids=["claim_1", "claim_x"]),
            VlogBeatDraft(scene_order=2, kind="broll", text="Tower", visual="the tower"),
        ],
    )  # fmt: skip
    script = _script(draft, scene_count=3)
    rules = _theme().production.generative
    scene2 = [ln for ln in script.lines if ln.scene_order == 2]
    assert len(scene2[0].text.split()) <= max_dialogue_words(rules)
    assert scene2[0].claim_ids == ["claim_1"]
    assert script.lines[0].claim_ids == ["claim_2"] and script.lines[0].dramatized
    late = VlogBeatDraft(scene_order=2, kind="dialogue", text="Fun fact", visual="the crowd",
                         claim_ids=["claim_2"])  # fmt: skip
    script = _script(VlogScriptDraft(hook="Hello there", beats=[late, late]), scene_count=3)
    assert next(ln for ln in script.lines if ln.scene_order == 2).claim_ids == []


def test_scenes_have_a_and_b_roll_shots_with_element_and_disclosure() -> None:
    theme = _theme()
    character = get_character(CFG, "lena-voss")
    graph = build_vlog_scenes(script=_script(), theme=theme, character=character)
    rules = theme.production.generative
    element = character.element_for("higgsfield")
    for scene in graph.scenes:
        assert abs(sum(s.duration_sec for s in scene.shots) - scene.duration_sec) < 0.05
        for shot in scene.shots:
            assert shot.disclosure.synthetic_media and shot.disclosure.label_text
            assert shot.provider_plan.provider == "higgsfield"
            model = rules.a_roll if shot.kind == ShotKind.A_ROLL else rules.b_roll
            assert shot.provider_plan.model == model.model
            assert model.min_sec <= shot.duration_sec <= model.max_sec
            if shot.kind == ShotKind.A_ROLL:
                assert shot.audio.dialogue_text
                assert f"<<<{element}>>>" in shot.provider_plan.parameters["still_prompt"]
            else:
                assert shot.audio.dialogue_text is None
