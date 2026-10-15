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
        if payload.dialogue_shot_id:
            return self._dialogue(ctx, payload, payload.dialogue_shot_id)
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

    def _dialogue(self, ctx: AgentContext, payload: AudioInput, shot_id: str) -> AudioPackage:
        """One host line (A-roll ``dialogue_text``) in the character's fixed voice."""
        scene, shot = next(
            ((sc, sh) for sc in payload.scenes for sh in sc.shots if sh.id == shot_id),
            (None, None),
        )
        if scene is None or shot is None or not shot.audio.dialogue_text:
            raise ValueError(f"shot {shot_id} has no dialogue line")
        voice = payload.voice or {}
        text = shot.audio.dialogue_text
        self.render_prompt(
            ctx,
            voice=voice.get("voice_name") or voice.get("voice_id") or ctx.theme.performance.voice,
            language=payload.language,
            accent=ctx.theme.performance.accent or "neutral",
            sound_palette=", ".join(ctx.theme.direction.sound_palette),
            scene_count=1,
        )
        params = {
            "language": payload.language,
            "characters": len(text),
            "duration_sec": shot.duration_sec,
        }
        if voice.get("voice_id"):
            params |= {
                "voice_type": voice.get("voice_type", "preset"),
                "voice_id": voice["voice_id"],
            }
        response, event = self.call_provider(
            ctx,
            C.VOICE_TTS,
            sub_scope=f"line-{shot.id}",
            provider_name=voice.get("provider"),
            model=voice.get("model"),
            prompt=text,
            scene_id=scene.id,
            shot_id=shot.id,
            parameters=params,
        )
        track = AudioTrack(
            id=f"audio_dialogue_{shot.id}",
            kind="dialogue",
            scene_id=scene.id,
            shot_id=shot.id,
            asset_id=response.output_asset_id,
            duration_sec=shot.duration_sec,
            provider=response.provider,
            model=response.model,
            cost=event.actual_cost,
            ledger_event_id=event.event_id,
            output_url=response.output_data.get("result_url"),
            text=text,
        )
        alignment = AlignmentRef(shot_id=shot.id, audio_track_id=track.id, method="lip_sync")
        return AudioPackage(tracks=[track], alignments=[alignment])
