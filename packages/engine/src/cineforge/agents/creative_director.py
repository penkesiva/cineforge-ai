"""A4 Creative Director: creative treatment and style bible from the ThemeProfile."""

from __future__ import annotations

from cineforge.agents.base import BaseAgent, note
from cineforge.contracts.agents import AgentContext, CreativeInput, CreativeTreatment
from cineforge.contracts.common import AgentId


class CreativeDirectorAgent(BaseAgent):
    agent_id = AgentId.CREATIVE_DIRECTOR
    input_model = CreativeInput
    output_model = CreativeTreatment

    def execute(self, ctx: AgentContext, payload: CreativeInput) -> CreativeTreatment:
        theme = payload.theme
        brief = payload.brief
        genre = brief.genre or theme.genres[0]
        prompt = self.render_prompt(
            ctx,
            topic=brief.topic,
            theme_name=theme.name,
            genre=genre,
            tone=theme.tone,
            visual_style=theme.visual_style,
            pacing=theme.pacing,
            audience=brief.audience or theme.audience,
        )
        response = self._llm(ctx, prompt, "treatment")
        visual_language = [
            *theme.direction.camera_grammar,
            *(f"light:{x}" for x in theme.direction.lighting),
            *(f"atmosphere:{x}" for x in theme.direction.atmosphere),
        ]
        style_bible = {
            "visual_style": theme.visual_style,
            "pacing": theme.pacing,
            "lighting": theme.direction.lighting,
            "atmosphere": theme.direction.atmosphere,
            "vfx_intensity": theme.direction.vfx_intensity,
            "crowd_rules": theme.direction.crowd_rules,
            "sound_palette": theme.direction.sound_palette,
            "aspect_ratio": theme.production.aspect_ratio,
            "character": {
                "ref": theme.performance.recurring_character,
                "voice": theme.performance.voice,
                "camera_relationship": theme.performance.camera_relationship,
            },
            "avoid": theme.constraints.avoid,
            "disclosure_rules": theme.constraints.disclosure_rules,
        }
        llm_note = note(response.output_text if response else None)
        if llm_note:
            style_bible["director_notes"] = llm_note
        return CreativeTreatment(
            theme_id=theme.id,
            theme_version=theme.version,
            logline=f"{theme.name}: {brief.topic}, told with a {theme.tone.lower()} voice.",
            genre=genre,
            tone=theme.tone,
            narrative_style=theme.narrative.narration_style,
            visual_language=visual_language,
            style_bible=style_bible,
        )
