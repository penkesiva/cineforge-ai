"""Host-led vlog planning for fully generative themes (A5 script, A6 shots).

The LLM writes what the host says and what the camera sees; code owns timing (words per
second, model duration limits), the A-roll/B-roll structure, claim rules, prompts with
the character's reference element, and disclosure. Every shot is generated: a
storyboard still first, then a clip (A-roll lip-synced to the host's voice line).
"""

from __future__ import annotations

from cineforge.agents.drafts import VlogBeatDraft, VlogScriptDraft
from cineforge.agents.planning import beats_for_scenes
from cineforge.contracts.agents import (
    ClaimStatus,
    FactClaim,
    SceneGraph,
    Script,
    ScriptLine,
    StoryBeat,
)
from cineforge.contracts.character import CharacterProfile
from cineforge.contracts.common import GenerationStrategy
from cineforge.contracts.manifest import (
    AudioSpec,
    Disclosure,
    PerformanceSpec,
    ProviderPlan,
    Scene,
    Shot,
    ShotKind,
    VisualSpec,
)
from cineforge.contracts.providers import ProviderCapability
from cineforge.contracts.theme import GenerativeModel, GenerativeRules, ThemeProfile

LIP_SYNC_PAD_SEC = 0.8
BROLL_SEC = 5.0
AI_LABEL = "AI-generated"
_USABLE = (ClaimStatus.VERIFIED, ClaimStatus.DRAMATIZED)


def _clamp(value: float, model: GenerativeModel) -> float:
    low = model.min_sec or 2.0
    high = model.max_sec or 15.0
    return round(max(low, min(high, value)), 1)


def max_dialogue_words(rules: GenerativeRules) -> int:
    return max(6, int(((rules.a_roll.max_sec or 12.0) - LIP_SYNC_PAD_SEC) * rules.words_per_sec))


def _fit(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).rstrip(",;:") + "."


# --------------------------------------------------------------------------- A5
def vlog_prompt(
    *,
    topic: str,
    character: CharacterProfile,
    theme: ThemeProfile,
    beats: list[str],
    claims: list[FactClaim],
    max_words: int,
    scene_count: int,
    duration_sec: float,
) -> str:
    claim_lines = "\n".join(f"- {c.id}: {c.status.value}: {c.text}" for c in claims) or "none"
    return (
        f"Write a {duration_sec:.0f}-second vertical POV vlog about: {topic}.\n"
        f"Host: {character.name}. Personality: {character.personality}\n"
        f"Style: {theme.narrative.narration_style}. Tone: {theme.tone}.\n"
        f"Hook: {theme.narrative.hook_strategy}.\n"
        f"Scenes ({scene_count}), one story beat each: {', '.join(beats)}.\n"
        "Each scene has 1-2 beats. 'dialogue' = she talks to camera (selfie or walk-and-talk); "
        "'broll' = what she films, nothing spoken. Alternate them; most scenes start with "
        "dialogue. The last scene is dialogue only and signs off with: "
        f"{theme.narrative.cta or 'a friendly goodbye'}.\n"
        f"Dialogue: at most {max_words} words per beat, first person, present tense, "
        "contractions, honest reactions, one fact per beat. Only state facts from the claims "
        "below and cite their ids; never invent quotes by real people.\n"
        "Visual: concrete, period-accurate details of place, people, light and weather. "
        f"Mention {character.name} in a broll visual only when she is in frame.\n"
        f"Claims:\n{claim_lines}"
    )


def build_vlog_script(
    *,
    topic: str,
    logline: str,
    theme: ThemeProfile,
    character: CharacterProfile,
    claims: list[FactClaim],
    excluded: set[str],
    scene_count: int,
    draft: VlogScriptDraft | None,
) -> Script:
    rules = theme.production.generative
    assert rules is not None
    beats = beats_for_scenes(theme.narrative.story_beats, scene_count)
    usable = [c for c in claims if c.status in _USABLE and c.id not in excluded]
    by_id = {c.id: c for c in usable}
    verified = [c for c in usable if c.status == ClaimStatus.VERIFIED]
    max_words = max_dialogue_words(rules)

    drafted: dict[int, list[VlogBeatDraft]] = {}
    for beat in draft.beats if draft else []:
        if 1 <= beat.scene_order <= scene_count:
            drafted.setdefault(beat.scene_order, []).append(beat)

    lines: list[ScriptLine] = []
    hook = _fit(draft.hook, max_words) if draft else f"Okay. I'm standing in {topic}, for real."
    for order in range(1, scene_count + 1):
        scene_beats = drafted.get(order, [])[: theme.production.max_shots_per_scene]
        if not scene_beats:
            scene_beats = _fallback_beats(order, scene_count, topic, beats, verified, hook)
        if order == scene_count:
            scene_beats = [b for b in scene_beats if b.kind == "dialogue"] or scene_beats[:1]
        for beat in scene_beats:
            ids = [
                cid
                for cid in dict.fromkeys(beat.claim_ids)
                if cid in by_id and (order == 1 or by_id[cid].status == ClaimStatus.VERIFIED)
            ]
            text = beat.text.strip()
            if beat.kind == "dialogue":
                text = _fit(text, max_words)
            lines.append(
                ScriptLine(
                    scene_order=order,
                    speaker=character.name if beat.kind == "dialogue" else "camera",
                    text=text,
                    claim_ids=ids,
                    dramatized=any(by_id[c].status == ClaimStatus.DRAMATIZED for c in ids),
                    kind=beat.kind,
                    visual=beat.visual.strip(),
                )
            )
    cta = theme.narrative.cta
    last = next((ln for ln in reversed(lines) if ln.kind == "dialogue"), None)
    if cta and last is not None and cta.lower().rstrip(".") not in last.text.lower():
        last.text = f"{_fit(last.text, max_words - len(cta.split()))} {cta}."
    spoken = [ln for ln in lines if ln.kind == "dialogue"]
    words = sum(len(ln.text.split()) for ln in spoken)
    duration = sum(
        _clamp(len(ln.text.split()) / rules.words_per_sec + LIP_SYNC_PAD_SEC, rules.a_roll)
        if ln.kind == "dialogue"
        else _clamp(BROLL_SEC, rules.b_roll)
        for ln in lines
    )
    return Script(
        hook=spoken[0].text if spoken else hook,
        logline=logline,
        beats=[StoryBeat(order=i, beat=b, purpose=b) for i, b in enumerate(beats, 1)],
        lines=lines,
        cta=cta,
        word_count=words,
        estimated_duration_sec=round(duration, 1),
    )


def _fallback_beats(
    order: int,
    scene_count: int,
    topic: str,
    beats: list[str],
    verified: list[FactClaim],
    hook: str,
) -> list[VlogBeatDraft]:
    beat = beats[order - 1] if order - 1 < len(beats) else "moment"
    claim = verified[(order - 2) % len(verified)] if verified and order > 1 else None
    if order == 1:
        said = hook
    elif claim is not None:
        said = f"Okay, so here's the wild part. {claim.text}"
    else:
        said = f"This is the {beat}, and honestly, it's even better in person."
    out = [
        VlogBeatDraft(
            scene_order=order,
            kind="dialogue",
            text=said,
            visual=f"Selfie close-up of the host at {topic}, {beat}",
            claim_ids=[claim.id] if claim else [],
        )
    ]
    if order < scene_count:
        out.append(
            VlogBeatDraft(
                scene_order=order,
                kind="broll",
                text=beat.capitalize(),
                visual=f"POV view of {topic}: {beat}, people and details around",
            )
        )
    return out


# --------------------------------------------------------------------------- A6
def still_prompt(line: ScriptLine, character: CharacterProfile, element: str | None) -> str:
    who = f"<<<{element}>>> as {character.name}" if element else character.name
    if line.kind == "dialogue":
        return (
            f"{who}: {character.look}. Wardrobe: {character.wardrobe or 'casual'}. "
            f"{line.visual}. Vertical 9:16 smartphone selfie vlog frame, she holds the phone "
            "at arm's length and looks into the lens, mouth relaxed, photoreal, natural light, "
            "period-accurate surroundings, no text, no watermark"
        )
    in_frame = character.name.lower() in (line.visual or "").lower()
    lead = f"{who} in frame. " if in_frame else ""
    return (
        f"{lead}{line.visual}. First-person POV smartphone vlog frame, photoreal, "
        "period-accurate, natural light, shallow depth of field, no text, no watermark"
    )


def clip_prompt(line: ScriptLine, character: CharacterProfile) -> str:
    if line.kind == "dialogue":
        return (
            f"{character.name} talks to the camera in a handheld selfie vlog, natural lip "
            "movement in sync with her voice, small head movements and hand gestures, "
            f"{line.visual}. Ambient sound of the place under her voice. Keep her face and "
            "outfit identical to the start frame."
        )
    return (
        f"{line.visual}. Handheld first-person camera, gentle natural movement, realistic "
        "ambient sound of the place, no dialogue, no music, no text."
    )


def build_vlog_scenes(
    *,
    script: Script,
    theme: ThemeProfile,
    character: CharacterProfile,
) -> SceneGraph:
    rules = theme.production.generative
    assert rules is not None
    element = character.element_for(rules.provider)
    by_scene: dict[int, list[ScriptLine]] = {}
    for line in script.lines:
        by_scene.setdefault(line.scene_order, []).append(line)
    beats = {b.order: b.beat for b in script.beats}
    scenes: list[Scene] = []
    for s_idx, order in enumerate(sorted(by_scene), 1):
        scene_id = f"scene_{s_idx:02d}"
        shots: list[Shot] = []
        for j, line in enumerate(by_scene[order], 1):
            a_roll = line.kind == "dialogue"
            model = rules.a_roll if a_roll else rules.b_roll
            words = len(line.text.split())
            duration = (
                _clamp(words / rules.words_per_sec + LIP_SYNC_PAD_SEC, model)
                if a_roll
                else _clamp(BROLL_SEC, model)
            )
            shots.append(
                Shot(
                    id=f"{scene_id}_shot_{j:02d}",
                    order=j,
                    duration_sec=duration,
                    kind=ShotKind.A_ROLL if a_roll else ShotKind.B_ROLL,
                    description=line.visual or line.text,
                    visual=VisualSpec(
                        shot_type="selfie_close_up" if a_roll else "pov",
                        camera_motion="handheld",
                        lighting=theme.direction.lighting[0] if theme.direction.lighting else None,
                        atmosphere=", ".join(theme.direction.atmosphere[:2]) or None,
                    ),
                    performance=PerformanceSpec(
                        character_ref=character.id if a_roll else None,
                        lip_sync_required=a_roll,
                    ),
                    audio=AudioSpec(
                        dialogue_text=line.text if a_roll else None,
                        ambience=(theme.direction.sound_palette or [None])[0],
                    ),
                    provider_plan=ProviderPlan(
                        strategy=GenerationStrategy.GENERATIVE,
                        capability=ProviderCapability.IMAGE_TO_VIDEO,
                        provider=rules.provider,
                        model=model.model,
                        prompt=clip_prompt(line, character),
                        parameters={
                            "still_prompt": still_prompt(line, character, element),
                            "claim_ids": list(line.claim_ids),
                        },
                    ),
                    disclosure=Disclosure(synthetic_media=True, label_text=AI_LABEL),
                )
            )
        total = round(sum(sh.duration_sec for sh in shots), 2)
        scenes.append(
            Scene(
                id=scene_id,
                order=s_idx,
                title=beats.get(order, f"Beat {order}").title(),
                duration_sec=total,
                story_beat=beats.get(order, ""),
                facts=sorted({c for ln in by_scene[order] for c in ln.claim_ids}),
                shots=shots,
            )
        )
    return SceneGraph(scenes=scenes)
