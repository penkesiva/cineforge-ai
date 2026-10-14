"""A6 Scene Director: scene graph, shot specs, routing plan and prompt compilation.

Deterministic guarantees (validated by the manifest contract and tests):
- scene count within the theme's min/max; shots per scene <= ``max_shots_per_scene``;
- shot durations sum exactly to their scene, scenes sum to ``duration_target_sec``;
- strategies only from ``mode_policy.allowed_strategies``; generative share ~=
  ``generative_shot_ratio``; generative shots carry disclosure labels.

A real LLM (``StoryboardDraft``) only contributes scene titles and per-shot
description, shot type, camera motion, lighting and atmosphere. Timing, strategies,
asset binding, provider routing and disclosure stay deterministic.
"""

from __future__ import annotations

import re

from cineforge.agents.base import BaseAgent
from cineforge.agents.drafts import SceneDraft, ShotDraft, StoryboardDraft
from cineforge.agents.planning import split_centis, stable_int
from cineforge.agents.prompts import PromptTemplate
from cineforge.contracts.agents import AgentContext, SceneDirectionInput, SceneGraph
from cineforge.contracts.common import AgentId, GenerationStrategy
from cineforge.contracts.manifest import (
    AssetRef,
    AssetRole,
    AudioSpec,
    Disclosure,
    OutputProfile,
    PerformanceSpec,
    ProviderPlan,
    Scene,
    Shot,
    VisualSpec,
)
from cineforge.contracts.providers import ProviderCapability, UnsupportedCapabilityError
from cineforge.contracts.theme import ProductionModePolicy

G = GenerationStrategy
SHOT_PROMPT_TEMPLATE_ID = "shot_prompt"
SHOT_PROMPT_TEMPLATE_VERSION = 1
DRAFT_VIDEO_MODEL = "mock-video-draft"
CINEMATIC_VIDEO_MODEL = "mock-video-cinematic"
MAX_PROMPT_CHARS = 480


def disclosure_label(rules: list[str]) -> str:
    """Use the on-screen label a theme prescribes (e.g. "Reconstruction"), else a default."""
    for rule in rules:
        match = re.search(r"\"([^\"]+)\"", rule)
        if match:
            return match.group(1)
    return "AI-generated"


def _cycle(items: list[str], idx: int, default: str | None) -> str | None:
    return items[idx % len(items)] if items else default


def _motion(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:40] or "static"


class SceneDirectorAgent(BaseAgent):
    agent_id = AgentId.SCENE_DIRECTOR
    input_model = SceneDirectionInput
    output_model = SceneGraph

    def execute(self, ctx: AgentContext, payload: SceneDirectionInput) -> SceneGraph:
        theme = ctx.theme
        policy = payload.mode_policy
        output = payload.output
        lines = sorted(payload.script.lines, key=lambda line: line.scene_order)
        lines = lines[: theme.production.max_scenes]
        prompt = self.render_prompt(
            ctx,
            logline=payload.script.logline,
            scene_count=len(lines),
            duration_sec=output.duration_target_sec,
            max_shots=payload.max_shots_per_scene,
            camera_grammar=", ".join(theme.direction.camera_grammar),
            lighting=", ".join(theme.direction.lighting) or "natural",
            atmosphere=", ".join(theme.direction.atmosphere) or "neutral",
            mode=policy.mode.value,
            generative_ratio=policy.generative_shot_ratio,
            allowed_strategies=", ".join(s.value for s in policy.allowed_strategies),
            lines="\n".join(f"{i}: {line.text}" for i, line in enumerate(lines, 1)),
        )
        draft = self.structured(ctx, StoryboardDraft, prompt, scope="storyboard", max_tokens=2500)
        if draft is None:
            self._llm(ctx, prompt, "storyboard", max_tokens=1000)
        drafted: dict[int, SceneDraft] = {s.order: s for s in draft.scenes} if draft else {}

        weights = [0.8 if i == 0 else 1.0 for i in range(len(lines))]
        scene_durations = split_centis(output.duration_target_sec, weights)
        shot_counts = [
            max(1, min(payload.max_shots_per_scene, int(d // 3))) for d in scene_durations
        ]
        generative_ids = self._pick_generative(shot_counts, policy)
        fallback = self._fallback_strategy(policy.allowed_strategies)
        selected = list(payload.assets.selected_ids)
        shot_template = self.prompts.get_or_fallback(
            SHOT_PROMPT_TEMPLATE_ID, SHOT_PROMPT_TEMPLATE_VERSION
        )
        label = disclosure_label(theme.constraints.disclosure_rules)
        reconstruction = any(
            "reconstruction" in r.lower() for r in theme.constraints.disclosure_rules
        )
        providers: dict[ProviderCapability, tuple[str, list[str]]] = {}

        scenes: list[Scene] = []
        asset_cursor = 0
        global_idx = 0
        for s_idx, (line, scene_dur, n_shots) in enumerate(
            zip(lines, scene_durations, shot_counts, strict=True)
        ):
            scene_id = f"scene_{s_idx + 1:02d}"
            beat = payload.script.beats[s_idx].beat if s_idx < len(payload.script.beats) else ""
            scene_draft = drafted.get(s_idx + 1)
            shot_durations = split_centis(scene_dur, [1.0] * n_shots)
            shots: list[Shot] = []
            for j, shot_dur in enumerate(shot_durations):
                shot_draft: ShotDraft | None = (
                    scene_draft.shots[j] if scene_draft and j < len(scene_draft.shots) else None
                )
                shot_id = f"{scene_id}_shot_{j + 1:02d}"
                is_last = j == n_shots - 1
                generative = shot_id in generative_ids
                strategy = G.GENERATIVE if generative else fallback
                capability = (
                    ProviderCapability.VIDEO_GENERATION
                    if generative
                    else ProviderCapability.IMAGE_TO_VIDEO
                )
                provider_name, models = providers.setdefault(
                    capability, self._provider_for(ctx, capability)
                )
                wanted = CINEMATIC_VIDEO_MODEL if generative else DRAFT_VIDEO_MODEL
                model = wanted if (not models or wanted in models) else models[0]

                hook_close_up = s_idx == 0 and is_last
                character = theme.performance.recurring_character if hook_close_up else None
                if hook_close_up:
                    shot_type = "close_up"
                elif shot_draft is not None:
                    shot_type = shot_draft.shot_type
                elif j == 0:
                    shot_type = "wide"
                else:
                    shot_type = ("medium", "close_up", "detail")[s_idx % 3]
                if hook_close_up:
                    motion = "slow_push"
                elif generative:
                    motion = (
                        _motion(shot_draft.camera_motion)
                        if shot_draft is not None
                        else _cycle(theme.direction.camera_grammar, global_idx, "slow_push")
                    )
                else:
                    motion = "ken_burns" if j == 0 else "slow_push"
                visual = VisualSpec(
                    shot_type=shot_type,
                    camera_motion=motion or "static",
                    lighting=(shot_draft.lighting if shot_draft else None)
                    or _cycle(theme.direction.lighting, s_idx, None),
                    atmosphere=(shot_draft.atmosphere if shot_draft else None)
                    or _cycle(theme.direction.atmosphere, global_idx, None),
                    color_grade=theme.visual_style.split(",")[0][:60],
                    vfx=["period_cleanup"] if generative and reconstruction else [],
                )
                description = (
                    shot_draft.description
                    if shot_draft is not None
                    else f"{beat or 'Scene'}: {line.text}"
                )[:200]

                assets: list[AssetRef] = []
                refs: list[str] = []
                if selected:
                    asset_id = selected[asset_cursor % len(selected)]
                    asset_cursor += 1
                    role = AssetRole.REFERENCE if generative else AssetRole.SOURCE
                    transform = (
                        {}
                        if generative
                        else {"ken_burns": {"zoom": 1.08, "pan": "left" if j % 2 else "right"}}
                    )
                    assets.append(AssetRef(asset_id=asset_id, role=role, transform=transform))
                    refs.append(asset_id)

                shots.append(
                    Shot(
                        id=shot_id,
                        order=j + 1,
                        duration_sec=shot_dur,
                        description=description,
                        visual=visual,
                        performance=PerformanceSpec(
                            character_ref=character,
                            emotion="curious" if character else None,
                            gesture="addresses camera" if character else None,
                            lip_sync_required=character is not None,
                        ),
                        audio=AudioSpec(
                            narration_text=line.text if j == 0 else None,
                            ambience=_cycle(theme.direction.sound_palette, 0, None),
                            music_cue=(
                                _cycle(theme.direction.sound_palette, 1, None)
                                if s_idx == 0 and j == 0
                                else None
                            ),
                        ),
                        assets=assets,
                        provider_plan=ProviderPlan(
                            strategy=strategy,
                            capability=capability,
                            provider=provider_name,
                            model=model,
                            prompt_template_id=shot_template.template_id,
                            prompt_template_version=shot_template.version,
                            prompt=self._compile_prompt(
                                shot_template, visual, description, theme.visual_style, output
                            ),
                            negative_prompt=", ".join(
                                [*theme.constraints.avoid, "watermark", "garbled text"]
                            ),
                            seed=stable_int(ctx.production_id, shot_id),
                            reference_asset_ids=refs,
                            parameters={
                                "duration_sec": shot_dur,
                                "width": output.width,
                                "height": output.height,
                                "fps": output.fps,
                                "aspect_ratio": output.aspect_ratio,
                                "quality_tier": policy.quality_tier,
                            },
                            draft_first=policy.draft_first and generative,
                        ),
                        disclosure=Disclosure(
                            synthetic_media=generative,
                            reconstruction=generative and reconstruction,
                            label_text=label if generative else None,
                        ),
                        depends_on=[shots[-1].id] if shots else [],
                    )
                )
                global_idx += 1
            scenes.append(
                Scene(
                    id=scene_id,
                    order=s_idx + 1,
                    title=(
                        scene_draft.title
                        if scene_draft is not None
                        else (beat or f"Scene {s_idx + 1}").replace("-", " ").title()
                    )[:80],
                    duration_sec=scene_dur,
                    story_beat=beat,
                    narration=line.text,
                    facts=list(line.claim_ids),
                    shots=shots,
                )
            )
        return SceneGraph(scenes=scenes)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _fallback_strategy(allowed: list[GenerationStrategy]) -> GenerationStrategy:
        for candidate in (G.LICENSED_STILL_MOTION, G.HYBRID, G.REUSE):
            if candidate in allowed:
                return candidate
        return allowed[0]

    @staticmethod
    def _pick_generative(shot_counts: list[int], policy: ProductionModePolicy) -> set[str]:
        if G.GENERATIVE not in policy.allowed_strategies:
            return set()
        total = sum(shot_counts)
        wanted = round(total * policy.generative_shot_ratio)
        last_shots = [f"scene_{i + 1:02d}_shot_{n:02d}" for i, n in enumerate(shot_counts)]
        others = [
            f"scene_{i + 1:02d}_shot_{j:02d}"
            for i, n in enumerate(shot_counts)
            for j in range(1, n)
        ]
        return set((last_shots + others)[:wanted])

    @staticmethod
    def _provider_for(ctx: AgentContext, capability: ProviderCapability) -> tuple[str, list[str]]:
        try:
            provider = ctx.providers.route(capability, tenant_id=ctx.tenant_id)
        except UnsupportedCapabilityError:
            return "unassigned", []
        return provider.info.name, list(provider.info.models)

    @staticmethod
    def _compile_prompt(
        template: PromptTemplate,
        visual: VisualSpec,
        description: str,
        style: str,
        output: OutputProfile,
    ) -> str:
        text = template.render(
            shot_type=visual.shot_type.replace("_", " "),
            camera_motion=visual.camera_motion.replace("_", " "),
            lighting=(visual.lighting or "natural light").replace("_", " "),
            atmosphere=(visual.atmosphere or "clear air").replace("_", " "),
            description=description,
            visual_style=style,
            aspect_ratio=output.aspect_ratio,
            task=description,
            context=style,
        )
        flat = " ".join(text.split())
        return flat[:MAX_PROMPT_CHARS]
