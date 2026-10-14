"""A8 Audio & Performance Agent: narration per scene, one music bed, lip-sync where needed.

``include_narration`` / ``include_music`` let the orchestrator run narration per scene
and the music bed as separate, individually retried steps.
"""

from __future__ import annotations

from cineforge.agents.base import BaseAgent
from cineforge.contracts.agents import (
    AgentContext,
    AlignmentRef,
    AudioInput,
    AudioPackage,
    AudioTrack,
)
from cineforge.contracts.common import AgentId
from cineforge.contracts.providers import ProviderCapability

C = ProviderCapability


class AudioPerformanceAgent(BaseAgent):
    agent_id = AgentId.AUDIO_PERFORMANCE
    input_model = AudioInput
    output_model = AudioPackage

    def execute(self, ctx: AgentContext, payload: AudioInput) -> AudioPackage:
        theme = ctx.theme
        self.render_prompt(
            ctx,
            voice=theme.performance.voice,
            language=payload.language,
            accent=theme.performance.accent or "neutral",
            sound_palette=", ".join(theme.direction.sound_palette),
            scene_count=len(payload.scenes),
        )
        lines = {line.scene_order: line for line in payload.script.lines}
        tracks: list[AudioTrack] = []
        alignments: list[AlignmentRef] = []

        for scene in payload.scenes if payload.include_narration else []:
            text = scene.narration or (lines[scene.order].text if scene.order in lines else "")
            if not text:
                continue
            response, event = self.call_provider(
                ctx,
                C.VOICE_TTS,
                sub_scope=f"tts-{scene.id}",
                prompt=text,
                scene_id=scene.id,
                parameters={
                    "voice": theme.performance.voice,
                    "language": payload.language,
                    "characters": len(text),
                    "duration_sec": scene.duration_sec,
                },
            )
            track = AudioTrack(
                id=f"audio_narration_{scene.id}",
                kind="narration",
                scene_id=scene.id,
                asset_id=response.output_asset_id,
                duration_sec=scene.duration_sec,
                provider=response.provider,
                model=response.model,
                cost=event.actual_cost,
            )
            tracks.append(track)
            alignments.append(
                AlignmentRef(
                    shot_id=scene.shots[0].id, audio_track_id=track.id, method="forced_alignment"
                )
            )
            for shot in scene.shots:
                if not shot.performance.lip_sync_required:
                    continue
                self.call_provider(
                    ctx,
                    C.LIP_SYNC,
                    sub_scope=f"lipsync-{shot.id}",
                    scene_id=scene.id,
                    shot_id=shot.id,
                    reference_asset_ids=[a.asset_id for a in shot.assets],
                    parameters={
                        "duration_sec": shot.duration_sec,
                        "character_ref": shot.performance.character_ref,
                        "audio_track_id": track.id,
                    },
                )
                alignments.append(
                    AlignmentRef(shot_id=shot.id, audio_track_id=track.id, method="lip_sync")
                )

        if not payload.include_music:
            return AudioPackage(tracks=tracks, alignments=alignments)
        total = sum(s.duration_sec for s in payload.scenes)
        cue = next(
            (sh.audio.music_cue for s in payload.scenes for sh in s.shots if sh.audio.music_cue),
            None,
        )
        response, event = self.call_provider(
            ctx,
            C.MUSIC_GENERATION,
            sub_scope="music",
            prompt=cue or ", ".join(theme.direction.sound_palette) or theme.tone,
            parameters={"duration_sec": total, "mood": theme.tone},
        )
        tracks.append(
            AudioTrack(
                id="audio_music_main",
                kind="music",
                asset_id=response.output_asset_id,
                duration_sec=total,
                provider=response.provider,
                model=response.model,
                cost=event.actual_cost,
            )
        )
        return AudioPackage(tracks=tracks, alignments=alignments)
