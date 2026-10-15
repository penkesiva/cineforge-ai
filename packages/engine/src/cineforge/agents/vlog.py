"""Host-led vlog planning for fully generative themes (A5 script, A6 shots).

The LLM writes what the host says and what the camera sees; code owns timing (words per
second, model duration limits), the A-roll/B-roll structure, claim rules, prompts with
the persona's reference element, and disclosure. Every shot is generated: a
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
from cineforge.contracts.common import GenerationStrategy
from cineforge.contracts.manifest import (
    AudioSpec,
    AuthoredScript,
    Disclosure,
    PerformanceSpec,
    ProductionLook,
    ProviderPlan,
    Scene,
    Shot,
    ShotKind,
    VisualSpec,
)
from cineforge.contracts.persona import PersonaCanon, PersonaProfile
from cineforge.contracts.providers import ProviderCapability
from cineforge.contracts.theme import GenerativeModel, GenerativeRules, ThemeProfile

LIP_SYNC_PAD_SEC = 0.8
VOICEOVER_PAD_SEC = 0.4
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


def speech_sec(text: str, rules: GenerativeRules) -> float:
    return len(text.split()) / rules.words_per_sec


def line_duration(line: ScriptLine, rules: GenerativeRules) -> float:
    """Shot length: speech time (plus pad) or the authored length, within model limits."""
    if line.kind == "dialogue":
        spoken = speech_sec(line.text, rules) + LIP_SYNC_PAD_SEC
        return _clamp(max(spoken, line.duration_sec or 0), rules.a_roll)
    if line.voiceover:
        spoken = speech_sec(line.text, rules) + VOICEOVER_PAD_SEC
        return _clamp(max(spoken, line.duration_sec or 0), rules.b_roll)
    return _clamp(line.duration_sec or BROLL_SEC, rules.b_roll)


class AuthoredScriptError(ValueError):
    """An approved script line cannot fit its shot (too many words for the model limit)."""


def script_from_authored(
    authored: AuthoredScript,
    *,
    logline: str,
    theme: ThemeProfile,
    persona: PersonaProfile,
) -> Script:
    """Use a human-approved script as-is; code only checks fit and adds the CTA."""
    rules = theme.production.generative
    assert rules is not None
    lines = [ln.model_copy(deep=True) for ln in authored.lines]
    for i, ln in enumerate(lines, 1):
        spoken = ln.kind == "dialogue" or ln.voiceover
        ln.speaker = persona.name if spoken else "camera"
        model = rules.a_roll if ln.kind == "dialogue" else rules.b_roll
        pad = LIP_SYNC_PAD_SEC if ln.kind == "dialogue" else VOICEOVER_PAD_SEC
        if spoken and speech_sec(ln.text, rules) + pad > (model.max_sec or 15.0):
            limit = int(((model.max_sec or 15.0) - pad) * rules.words_per_sec)
            raise AuthoredScriptError(
                f"line {i}: {len(ln.text.split())} words; at most {limit} fit one shot"
            )
    cta = theme.narrative.cta
    last = next((ln for ln in reversed(lines) if ln.kind == "dialogue" or ln.voiceover), None)
    if cta and last is not None and cta.lower().rstrip(".") not in last.text.lower():
        last.text = f"{last.text.rstrip()} {cta}."
    orders = sorted({ln.scene_order for ln in lines})
    names = beats_for_scenes(theme.narrative.story_beats, len(orders))
    spoken_lines = [ln for ln in lines if ln.kind == "dialogue" or ln.voiceover]
    return Script(
        hook=spoken_lines[0].text if spoken_lines else lines[0].text,
        logline=logline,
        beats=[StoryBeat(order=o, beat=n, purpose=n) for o, n in zip(orders, names, strict=True)],
        lines=lines,
        cta=cta,
        word_count=sum(len(ln.text.split()) for ln in spoken_lines),
        estimated_duration_sec=round(sum(line_duration(ln, rules) for ln in lines), 1),
    )


# --------------------------------------------------------------------------- A5
def persona_brief(persona: PersonaProfile) -> str:
    """Who is speaking and how (identity, personality, delivery, content limits)."""
    who, d = persona.identity, persona.delivery
    parts = [
        f"Host: {persona.name}, {who.age}"
        + (f", from {who.origin}" if who.origin else "")
        + (f", {who.occupation}" if who.occupation else "")
        + ".",
        f"Personality: {persona.personality.summary}",
        f"Delivery: {d.pace} pace, {d.energy} energy.",
    ]
    if persona.personality.humor:
        parts.append(f"Humor: {persona.personality.humor}.")
    if d.catchphrases:
        parts.append(f"Catchphrases (use at most one): {'; '.join(d.catchphrases)}.")
    if d.greeting:
        parts.append(f"Usual opener: {d.greeting}")
    if d.sign_off:
        parts.append(f"Usual sign-off: {d.sign_off}")
    if d.avoid_words:
        parts.append(f"Never say: {', '.join(d.avoid_words)}.")
    if persona.content.topics_avoid:
        parts.append(f"Never cover: {', '.join(persona.content.topics_avoid)}.")
    return "\n".join(parts)


def canon_brief(canon: PersonaCanon | None, limit: int = 8) -> str:
    """Continuity the script must not contradict (facts, jokes, recent trips)."""
    if canon is None:
        return ""
    lines = []
    if canon.facts:
        lines.append(f"Established facts: {'; '.join(canon.facts)}.")
    if canon.running_jokes:
        lines.append(f"Running jokes (optional callback): {'; '.join(canon.running_jokes)}.")
    trips = [e.title for e in canon.episodes[-limit:]]
    if trips:
        lines.append(f"Earlier trips (may reference, never repeat): {'; '.join(trips)}.")
    return "".join(f"{ln}\n" for ln in lines)


def vlog_prompt(
    *,
    topic: str,
    persona: PersonaProfile,
    theme: ThemeProfile,
    beats: list[str],
    claims: list[FactClaim],
    max_words: int,
    scene_count: int,
    duration_sec: float,
    canon: PersonaCanon | None = None,
) -> str:
    claim_lines = "\n".join(f"- {c.id}: {c.status.value}: {c.text}" for c in claims) or "none"
    return (
        f"Write a {duration_sec:.0f}-second vertical POV vlog about: {topic}.\n"
        f"{persona_brief(persona)}\n"
        f"{canon_brief(canon)}"
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
        f"Mention {persona.name} in a broll visual only when she is in frame.\n"
        f"Claims:\n{claim_lines}"
    )


def build_vlog_script(
    *,
    topic: str,
    logline: str,
    theme: ThemeProfile,
    persona: PersonaProfile,
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
                    speaker=persona.name if beat.kind == "dialogue" else "camera",
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
    duration = sum(line_duration(ln, rules) for ln in lines)
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
def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _wardrobe(persona: PersonaProfile, look: ProductionLook | None) -> str:
    if look is not None and look.wardrobe:
        return _sentence(look.wardrobe)
    rules = f" {' '.join(persona.wardrobe.rules)}" if persona.wardrobe.rules else ""
    return f"{persona.wardrobe.default}.{rules}"


def _setting(look: ProductionLook | None) -> str:
    if look is None or not look.location:
        return "Period-accurate surroundings."
    return " ".join(_sentence(t) for t in [f"Setting: {look.location}", *look.notes])


def in_frame(line: ScriptLine, persona: PersonaProfile) -> bool:
    return (
        line.kind == "dialogue"
        or line.in_frame
        or (persona.name.lower() in (line.visual or "").lower())
    )


def still_prompt(
    line: ScriptLine,
    persona: PersonaProfile,
    element: str | None,
    look: ProductionLook | None = None,
) -> str:
    """First frame of the shot: who (locked look, trip outfit), where, what, how shot."""
    who = f"<<<{element}>>> as {persona.name}" if element else persona.name
    plook, cam = persona.look, persona.camera
    color = f", {cam.color}" if cam.color else ""
    if in_frame(line, persona):
        keep = f" Keep: {', '.join(plook.locks)}." if plook.locks else ""
        avoid = ", ".join(["text", "watermark", *plook.avoid])
        framing = (
            f"{cam.framing}, she looks into the lens"
            if line.kind == "dialogue"
            else "handheld smartphone shot, she is in frame"
        )
        return (
            f"{who}, {persona.identity.age} years old: {plook.description}.{keep} "
            f"Outfit: {_wardrobe(persona, look)} {_setting(look)} "
            f"Moment: {line.visual}. "
            f"Camera: vertical 9:16 smartphone vlog frame, {framing}, photoreal, "
            f"{cam.lighting}{color}, natural skin texture, correct hands. Avoid: {avoid}."
        )
    return (
        f"{_setting(look)} Moment: {line.visual}. "
        f"Camera: vertical 9:16 first-person smartphone vlog frame, photoreal, "
        f"{cam.lighting}{color}, shallow depth of field. Avoid: text, watermark, logos."
    )


def clip_prompt(line: ScriptLine, persona: PersonaProfile) -> str:
    """Motion for the video model; the still already fixes look, place and framing."""
    sound = line.sound or "ambient sound of the place"
    if line.kind == "dialogue":
        action = line.motion or (f"{line.visual}. Small natural head movements and hand gestures")
        return (
            f"{persona.name} talks to the camera in a handheld selfie vlog. {action}. "
            f"Natural lip movement in sync with her voice. Sound: {sound} under her voice. "
            "Keep her face, outfit and props identical to the start frame."
        )
    action = line.motion or f"{line.visual}. Gentle natural movement"
    keep = " Keep her face and outfit identical to the start frame." if line.in_frame else ""
    return (
        f"{action}. Handheld smartphone camera, light natural shake. Sound: {sound}. "
        f"No speech, no music, no text.{keep}"
    )


def build_vlog_scenes(
    *,
    script: Script,
    theme: ThemeProfile,
    persona: PersonaProfile,
    look: ProductionLook | None = None,
) -> SceneGraph:
    rules = theme.production.generative
    assert rules is not None
    element = persona.element_for(rules.provider)
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
            spoken = a_roll or line.voiceover
            duration = line_duration(line, rules)
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
                        character_ref=persona.id if in_frame(line, persona) else None,
                        lip_sync_required=a_roll,
                    ),
                    audio=AudioSpec(
                        dialogue_text=line.text if spoken else None,
                        voiceover=spoken and not a_roll,
                        ambience=line.sound or (theme.direction.sound_palette or [None])[0],
                    ),
                    on_screen_text=line.on_screen_text,
                    provider_plan=ProviderPlan(
                        strategy=GenerationStrategy.GENERATIVE,
                        capability=ProviderCapability.IMAGE_TO_VIDEO,
                        provider=rules.provider,
                        model=model.model,
                        prompt=clip_prompt(line, persona),
                        parameters={
                            "still_prompt": still_prompt(line, persona, element, look),
                            "claim_ids": list(line.claim_ids),
                            "refs": list(line.refs),
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
