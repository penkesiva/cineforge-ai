# CineForge agents (A1-A10)

CineForge runs **10 logical agents**. They are plain Python classes in
`packages/engine/src/cineforge/agents/`, registered in a `DefaultAgentRegistry`
and called only by the workflow engine (`cineforge.orchestration.workflow`).
The agent worker (`services/worker`, RQ queue `cineforge-agents`) executes the
`advance_production` job, which runs one workflow step at a time.

Agents never touch the database, queue or storage. Everything they may use is in
`AgentContext` (manifest, theme, mode policy, providers, `paid_calls`, price
catalog, idempotency key, attempt). Every provider call goes through
`ctx.paid_calls` (`PaidCallGuard`: price lookup, budget reservation, invoke,
commit or release).

## Catalog

| Code | Id | Module | Step | Input -> Output | Provider capabilities |
|------|----|--------|------|-----------------|-----------------------|
| A1 | `a1_master_orchestrator` | `master_orchestrator.py` | RESEARCHING | `PlanningInput` -> `ProductionPlan` | LLM |
| A2 | `a2_research` | `research.py` | RESEARCHING | `ResearchInput` -> `ResearchBrief` | LLM, web research |
| A3 | `a3_media_discovery` | `media_discovery.py` | RESEARCHING | `MediaDiscoveryInput` -> `AssetSelection` | media search |
| A4 | `a4_creative_director` | `creative_director.py` | RESEARCHING | `CreativeInput` -> `CreativeTreatment` | LLM |
| A5 | `a5_scriptwriter` | `scriptwriter.py` | SCRIPTING | `ScriptInput` -> `Script` | LLM |
| A6 | `a6_scene_director` | `scene_director.py` | STORYBOARDING | `SceneDirectionInput` -> `SceneGraph` | LLM |
| A7 | `a7_visual_production` | `visual_production.py` | GENERATING (per shot) | `ShotProductionInput` -> `RenderedShotRef` | image, image-to-video, video |
| A8 | `a8_audio_performance` | `audio_performance.py` | GENERATING | `AudioInput` -> `AudioPackage` | TTS, lip-sync, music |
| A9 | `a9_editor_qc` | `editor_qc.py` | REVIEWING | `ReviewInput` -> `ReviewReport` | LLM |
| A10 | `a10_cost_optimizer` | `cost_optimizer.py` | STORYBOARDING | `CostPlanningInput` -> `CostPlan` | none (pure planning) |

What each agent does in Phase 0:

- **A1 Master Orchestrator**: emits the `ProductionPlan` (ordered steps, owners,
  approval gate, retry and budget policy from the mode).
- **A2 Research**: 5 claims with citations. Most are `verified`; one is marked
  `dramatized` so A9 can check the disclosure path. Nothing is ever invented as fact.
- **A3 Media Discovery**: 8 licensed-media candidates from mock sources with a mix
  of licenses. The orchestrator runs every candidate through the `RightsGate`;
  unknown, NC or unlicensed assets are `blocked` and never used.
- **A4 Creative Director**: logline, narrative style, visual language and a style
  bible built from the theme profile.
- **A5 Scriptwriter**: hook, theme story beats, one narration line per beat, fitted
  to a word budget of about 2.5 words per second, call-to-action at the end.
- **A6 Scene Director**: scenes and shots whose durations sum exactly to the target.
  Shot strategy follows the mode policy (`max_generative_ratio`,
  `max_shots_per_scene`); licensed stills with motion are the default, generative
  shots get a compiled prompt (`shot_prompt` template) and an AI disclosure label.
- **A7 Visual Production**: one guarded provider call per shot attempt. The
  orchestrator owns retries (`max_attempts_per_shot` from the mode) and records each
  `ProviderAttempt` on the shot.
- **A8 Audio & Performance**: narration TTS per scene, lip-sync for performance
  shots, one music bed, timing alignments.
- **A9 Editor & QC**: checks the master render (resolution, codec, duration),
  shot completeness, disclosure labels, claim status and budget. Critical findings
  send the production to `NEEDS_REVIEW`. (Rendering itself is the media worker job
  `render_master`, owned by Workstream D.)
- **A10 Cost & Optimization**: turns the `CostEstimate` into a `CostPlan`
  (within budget or not, recommendations). The orchestrator pauses in
  `PAUSED_BUDGET` before generation if the estimate exceeds the limit.

## Prompts

Prompt templates live in `packages/prompts/<template_id>/v<N>.md` and are loaded by
`PromptLibrary` (`settings.prompts_dir`). The first line is an HTML comment header
(`id | version | inputs | output`) and is stripped. Placeholders use `$name`
(`string.Template`, safe substitution). Each `AgentRun` stores
`prompt_template_id` and `prompt_template_version`, so every output is traceable to
the exact prompt version.

To change a prompt, add `v2.md` next to `v1.md` and bump
`prompt_template_version` in the agent definition (a contract change). Never edit
a released version in place: runs must stay reproducible.

## Adding or changing an agent

1. The agent set (`AgentId`, `AGENT_DEFINITIONS`) and its input/output models are
   **contracts** (`cineforge/contracts/agents.py`). Agree changes there first and
   regenerate the exported schemas (`scripts/export_contracts.py`).
2. Create a module in `cineforge/agents/` with a `BaseAgent` subclass:

   ```python
   class MyAgent(BaseAgent):
       agent_id = AgentId.MY_AGENT
       input_model = MyInput
       output_model = MyOutput

       def execute(self, ctx: AgentContext, payload: MyInput) -> MyOutput:
           prompt = self.render_prompt(ctx, topic=ctx.manifest.brief.topic)
           self._llm(ctx, prompt, "main")  # optional, guarded and budgeted
           return MyOutput(...)  # build the typed artifact deterministically
   ```

   Use `self.call_provider(ctx, capability, sub_scope=...)` for every provider
   call. Give each call in one run a distinct `sub_scope` so its idempotency key
   (`{run_key}/{sub_scope}`) is unique.
3. Add `packages/prompts/<agent_id>/v1.md`.
4. Register the class in `cineforge/agents/factory.py` (`AGENT_CLASSES`).
5. Call it from the right step handler in `cineforge/orchestration/workflow.py`
   through `WorkflowEngine._invoke`, which records the `AgentRun` (idempotency key
   `{production}:{state}:{agent}:{scope}:{attempt}`), validates input and output
   through the registry (`AgentSchemaError` on mismatch) and persists the output.
6. Add tests in `packages/engine/tests/agents/` (schema-valid output, deterministic
   behaviour, policy rules).

## Mock vs real providers

Phase 0 runs only **mock providers** (`mock-llm`, `mock-research`,
`mock-media-search`, `mock-image`, `mock-video`, `mock-voice`, `mock-lipsync`,
`mock-music`, `mock-sfx`). They are free,
deterministic and priced from the mock price catalog (`packages/configurations/pricing`)
so budgets, reservations and the ledger behave like production.

Agents do **not parse provider text** in Phase 0. Artifacts are built
deterministically from the brief, theme and mode; LLM responses are only attached
as notes. This keeps tests stable and makes real providers a drop-in change later.

Real providers are a Workstream D concern:

- Register them in the provider registry with real model names and catalog prices.
- They are blocked unless `ALLOW_PAID_PROVIDERS=true`; the `PaidCallGuard` raises
  `PaidProviderNotAllowedError` otherwise.
- Agents route by capability (`ctx.providers.for_capability(...)`) or by the
  provider named in the shot's `ProviderPlan`, so no agent code changes are needed.
- When agents start using real LLM output, parse it into the same contract models
  and keep the deterministic path as a fallback.

## Running locally

```bash
uv run uvicorn cineforge_api.main:app --reload --port 8000    # API
uv run python -m cineforge_worker                             # agent worker (Redis)
uv run python -m cineforge_worker --simple --burst            # drain once, no fork
```

For a fully in-process demo without Redis, set `QUEUE_BACKEND=inline`; each API
call then runs the workflow synchronously until the next gate.
