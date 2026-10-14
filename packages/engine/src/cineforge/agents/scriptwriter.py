"""A5 Scriptwriter & Reasoner: hook, story beats and one narration line per scene.

Deterministic guarantees hold whether or not a real LLM wrote the lines: exactly one
line per scene, only usable claims that a reviewer did not reject (verified, or
dramatized for the hook only), per-line word budget, and the theme's call to action.
"""

from __future__ import annotations

from cineforge.agents.base import BaseAgent
from cineforge.agents.drafts import ScriptDraft
from cineforge.agents.planning import beats_for_scenes, word_budget
from cineforge.contracts.agents import (
    AgentContext,
    ClaimStatus,
    FactClaim,
    Script,
    ScriptInput,
    ScriptLine,
    StoryBeat,
)
from cineforge.contracts.common import AgentId

_PURPOSES = {
    "hook": "grab attention in under two seconds",
    "arrival": "place the viewer in the moment",
    "context": "explain why it matters",
    "reveal": "deliver the surprising fact",
    "legacy": "connect the past to today",
    "call-to-action": "invite the viewer to follow",
    "setup": "frame the mystery",
    "clue": "present the strongest evidence",
    "counter-evidence": "show what does not fit",
    "open-question": "leave the viewer wondering",
    "where-it-is": "locate the place",
    "how-it-formed": "explain its origin",
    "human-story": "show the people behind it",
    "why-visit": "make the viewer want to go",
}
_USABLE = (ClaimStatus.VERIFIED, ClaimStatus.DRAMATIZED)
_SHORT_SUBJECT = {
    "time-traveler": "this moment",
    "mystery-explorer": "this mystery",
    "fascinating-places": "this place",
}


def _purpose(beat: str) -> str:
    parts = [p.strip() for p in beat.replace("(continued)", "").split(" and ")]
    return "; ".join(_PURPOSES.get(p, "advance the story") for p in parts)


def _fit(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]).rstrip(",;") + "."


class ScriptwriterAgent(BaseAgent):
    agent_id = AgentId.SCRIPTWRITER
    input_model = ScriptInput
    output_model = Script

    def execute(self, ctx: AgentContext, payload: ScriptInput) -> Script:
        topic = payload.brief.topic
        theme = ctx.theme
        beats = beats_for_scenes(theme.narrative.story_beats, payload.scene_count)
        excluded = set(payload.excluded_claim_ids)
        usable: list[FactClaim] = [
            c for c in payload.research.claims if c.status in _USABLE and c.id not in excluded
        ]
        by_id = {c.id: c for c in usable}
        budget = word_budget(payload.duration_target_sec)
        per_line = max(8, budget // payload.scene_count)
        prompt = self.render_prompt(
            ctx,
            topic=topic,
            logline=payload.treatment.logline,
            narrative_style=payload.treatment.narrative_style,
            hook_strategy=theme.narrative.hook_strategy,
            beats=", ".join(beats),
            scene_count=payload.scene_count,
            duration_sec=payload.duration_target_sec,
            word_budget=budget,
            words_per_line=per_line,
            claims="\n".join(f"- {c.id}: {c.status.value}: {c.text}" for c in usable) or "none",
            cta=theme.narrative.cta or "none",
        )
        draft = self.structured(ctx, ScriptDraft, prompt, scope="script", max_tokens=1500)
        if draft is None:
            self._llm(ctx, prompt, "script", max_tokens=1200)

        verified = [c for c in usable if c.status == ClaimStatus.VERIFIED]
        dramatized = [c for c in usable if c.status == ClaimStatus.DRAMATIZED]
        in_sentence = topic[0].lower() + topic[1:] if topic.startswith("The ") else topic
        hook = f"Picture this: you are standing at {in_sentence}. What happens next?"
        if draft is not None:
            hook = _fit(draft.hook, 15)
        drafted = {line.scene_order: line for line in draft.lines} if draft else {}
        # After the hook, refer to a long topic by a short subject to respect the word budget.
        subject = topic if len(topic.split()) <= 5 else _SHORT_SUBJECT.get(theme.id, "this story")

        lines: list[ScriptLine] = []
        for order, beat in enumerate(beats, 1):
            claims: list[FactClaim]
            drafted_line = drafted.get(order)
            if drafted_line is not None:
                claims = [
                    by_id[cid]
                    for cid in dict.fromkeys(drafted_line.claim_ids)
                    if cid in by_id and (order == 1 or by_id[cid].status == ClaimStatus.VERIFIED)
                ]
                text = drafted_line.text.strip()
            elif order == 1:
                first = dramatized[0] if dramatized else (verified[0] if verified else None)
                claims = [first] if first else []
                text = hook
            else:
                claim = verified[(order - 2) % len(verified)] if verified else None
                claims = [claim] if claim else []
                text = claim.text.replace(topic, subject) if claim else f"The {beat} of {subject}."
                text = text[0].upper() + text[1:]
            text = _fit(text, per_line)
            if order == len(beats) and theme.narrative.cta:
                text = f"{text} {theme.narrative.cta}."
            lines.append(
                ScriptLine(
                    scene_order=order,
                    text=text,
                    claim_ids=[c.id for c in claims],
                    dramatized=any(c.status == ClaimStatus.DRAMATIZED for c in claims),
                )
            )
        word_count = sum(len(line.text.split()) for line in lines)
        return Script(
            hook=hook,
            logline=payload.treatment.logline,
            beats=[StoryBeat(order=i, beat=b, purpose=_purpose(b)) for i, b in enumerate(beats, 1)],
            lines=lines,
            cta=theme.narrative.cta,
            word_count=word_count,
            estimated_duration_sec=payload.duration_target_sec,
        )
