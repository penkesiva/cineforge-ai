"""Host-led vlog planning: deterministic timing, structure, prompts and disclosure."""

from __future__ import annotations

from pathlib import Path

import pytest
from cineforge.agents.drafts import VlogBeatDraft, VlogScriptDraft
from cineforge.agents.vlog import (
    AuthoredScriptError,
    build_vlog_scenes,
    build_vlog_script,
    line_duration,
    max_dialogue_words,
    script_from_authored,
    still_prompt,
    vlog_prompt,
)
from cineforge.config import Settings
from cineforge.configuration import get_persona, load_themes
from cineforge.contracts.agents import ClaimStatus, FactClaim
from cineforge.contracts.manifest import AuthoredScript, ProductionLook, ScriptLine, ShotKind
from cineforge.contracts.persona import Episode, PersonaCanon
from cineforge.cost.vlog import credits_for

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
        persona=get_persona(CFG, "lena-voss"),
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
    persona = get_persona(CFG, "lena-voss")
    graph = build_vlog_scenes(script=_script(), theme=theme, persona=persona)
    rules = theme.production.generative
    element = persona.element_for("higgsfield")
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


def test_script_prompt_carries_persona_voice_and_canon() -> None:
    canon = PersonaCanon(
        persona_id="lena-voss",
        facts=["She lives in Los Angeles."],
        running_jokes=["She always gets lost."],
        episodes=[Episode(title="Pompeii, the day before")],
    )
    prompt = vlog_prompt(
        topic="Paris 1889",
        persona=get_persona(CFG, "lena-voss"),
        theme=_theme(),
        beats=["arrive", "explore"],
        claims=_claims(),
        max_words=30,
        scene_count=2,
        duration_sec=75,
        canon=canon,
    )
    assert "Host: Lena Voss, 23" in prompt
    assert "Okay, you guys." in prompt and "See you in the next one." in prompt
    assert "Never cover: graphic violence" in prompt
    assert "She lives in Los Angeles." in prompt and "She always gets lost." in prompt
    assert "Earlier trips (may reference, never repeat): Pompeii, the day before" in prompt
    assert "hearing each fact for the first time" in prompt
    assert "Do not joke about meals" in prompt


def test_still_prompt_locks_look_and_lists_avoid() -> None:
    script = _script()
    line = next(ln for ln in script.lines if ln.kind == "dialogue")
    lena = get_persona(CFG, "lena-voss")
    prompt = still_prompt(line, lena, lena.element_for("higgsfield"))
    assert prompt.startswith("<<<01288044-0746-4b24-8fa8-bea17c4a9233>>> as Lena Voss, 23")
    assert "Keep: same face and age in every shot" in prompt
    assert "Avoid: text, watermark, heavy makeup" in prompt
    assert "Outfit: fitted black ribbed tank top" in prompt


def test_authored_lines_time_voice_overs_and_reject_long_lines() -> None:
    theme, rules = _theme(), _theme().production.generative
    persona = get_persona(CFG, "lena-voss")
    over = ScriptLine(scene_order=1, kind="broll", voiceover=True, text="No strings. No tricks.")
    silent = ScriptLine(scene_order=1, kind="broll", text="-")
    assert line_duration(over, rules) == rules.b_roll.min_sec
    assert line_duration(over.model_copy(update={"duration_sec": 6}), rules) == 6
    assert line_duration(silent, rules) == 5
    assert line_duration(silent.model_copy(update={"duration_sec": 20}), rules) == 8
    too_long = ScriptLine(scene_order=1, kind="broll", voiceover=True, text="word " * 30)
    authored = AuthoredScript(lines=[over, too_long])
    with pytest.raises(AuthoredScriptError, match="line 2: 30 words; at most 18"):
        script_from_authored(authored, logline="x", theme=theme, persona=persona)


def test_look_overrides_wardrobe_and_adds_the_setting() -> None:
    persona = get_persona(CFG, "lena-voss")
    look = ProductionLook(wardrobe="an ivory kurta over jeans", location="a granite temple")
    line = ScriptLine(scene_order=1, kind="dialogue", text="Hi", visual="she waves")
    prompt = still_prompt(line, persona, None, look)
    assert "Outfit: an ivory kurta over jeans. Setting: a granite temple." in prompt
    assert "black ribbed tank top" not in prompt
    shots = [
        ScriptLine(scene_order=1, kind="dialogue", text="Hi there, welcome."),
        ScriptLine(scene_order=1, kind="broll", voiceover=True, text="Look up."),
        ScriptLine(scene_order=2, kind="broll", text="-"),
    ]
    script = script_from_authored(
        AuthoredScript(lines=shots), logline="x", theme=_theme(), persona=persona
    )
    graph = build_vlog_scenes(script=script, theme=_theme(), persona=persona, look=look)
    rules = _theme().production.generative
    voice = [credits_for(rules, s, "voice") for s in graph.scenes[0].shots + graph.scenes[1].shots]
    assert voice[1] == voice[0] > 0 and graph.scenes[0].shots[1].audio.voiceover
