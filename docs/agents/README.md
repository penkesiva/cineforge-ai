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

What each agent does with mock providers (Phase 0 behaviour; see "Mock vs real
providers" for the Phase 1 live paths):

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

## Mock vs real providers (Phase 1)

Agents route per tenant with `ctx.providers.route(capability, tenant_id=...)`
(readiness rules and priorities: Sources page, `cineforge/providers/registry.py`).
With `PROVIDER_MODE=mock` (the default) only the free, deterministic mock providers
run, so behaviour is identical to Phase 0.

When a real LLM is ready, agents use **structured output**:

1. `BaseAgent.structured(ctx, DraftModel, prompt, scope=...)` sends the draft's JSON
   Schema (`response_schema`, `$ref`s inlined) through the `PaidCallGuard`.
2. The reply (`output_data["structured"]`) is validated with Pydantic. On failure it
   retries once with the validation errors (`llm-<scope>-fix`), then returns `None`.
3. `None` (mock LLM, no ready LLM, provider error, still invalid) means the agent
   uses its deterministic path. Budget errors always propagate (production pauses).
4. Drafts live in `cineforge/agents/drafts.py` and are agent-internal. Deterministic
   code turns them into contract artifacts and enforces the rules:
   - **A2**: claims must cite a numbered source with a verbatim excerpt; a failed
     citation check downgrades the claim to `unverified`. Without an LLM, claims are
     verbatim source sentences. No sources means no claims (never invented).
   - **A3**: real media providers are searched one by one (one failing source never
     fails the search), deduplicated and ranked by code; the mock catalog is used
     only when no real media provider is ready. Rights stay `unknown` for `RightsGate`.
   - **A4**: the style bible always comes from the theme; the LLM adds logline,
     narrative style, visual language and notes.
   - **A5**: exactly one line per scene, only verified claims (dramatized only in the
     hook) that a reviewer did not reject, per-line word budget, theme CTA.
   - **A6**: the LLM only supplies titles and shot descriptions, types, motion,
     lighting and atmosphere; timing, strategies, assets, routing and disclosure stay
     deterministic.

Real LLMs are never called just for notes (`_llm` only runs on mock LLMs). The
agent's `extras["reasoning"]` records `structured:<provider>/<model>` or
`deterministic`.

## Claim review and script rewrite (ENG-04)

At `AWAITING_APPROVAL` (or `PAUSED_BUDGET`) an editor can approve or reject claims
(`POST /productions/{id}/claims`; latest decision per claim wins). Approval is
refused (409 `approval_blocked`) while a script line cites a rejected claim.
`POST /productions/{id}/rewrite-script` goes back to `SCRIPTING` via `NEEDS_REVIEW`;
A5/A6/A10 then run with `attempt = script revision` so new runs are recorded and
rejected claims are passed as `excluded_claim_ids`.

## Audio

The orchestrator calls A8 once per scene (`include_music=False`, scope = scene id)
and once for the music bed (`include_narration=False`, scope `music`), each with the
mode's bounded retries. A failed line retries alone; succeeded runs are reused.

## Running locally

```bash
uv run uvicorn cineforge_api.main:app --reload --port 8000    # API
uv run python -m cineforge_worker                             # agent worker (Redis)
uv run python -m cineforge_worker --simple --burst            # drain once, no fork
```

For a fully in-process demo without Redis, set `QUEUE_BACKEND=inline`; each API
call then runs the workflow synchronously until the next gate.
