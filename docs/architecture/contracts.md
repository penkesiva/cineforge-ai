# Phase 0 Shared Contracts (FROZEN)

Status: **frozen** at the start of parallel work. Changing anything here or in
`packages/engine/src/cineforge/contracts/`, `supabase/migrations/`, or
`packages/configurations/` is a **contract change**: stop, report it to the
integrator, and do not edit it inside a workstream branch.

Source of truth: Pydantic models in `cineforge.contracts.*`. JSON Schema and
TypeScript types are generated (`make contracts`) into `packages/schemas/`.

Change log:
- `phase0-contracts-frozen` - initial freeze (A10 input carries the deterministic `CostEstimate`).
- Integration - `ReviewFinding.blocking` / `ReviewReport.passed` (computed) are ignored on
  input so dumps round-trip. RQ-safe job IDs are derived from the logical IDs below.
- `phase1-contracts-frozen` - research and preproduction (section 9 below): live provider
  mode, provider catalog/settings/secrets, input/output token pricing, theme registry,
  claim review, prompt v2 for A2/A4/A5/A6, per-scene audio, ledger `status_reason`.

## 1. Modules

| Module | Contents |
|---|---|
| `common` | `Money` (Decimal, JSON number), `money()`, `new_id()`, `ProductionMode`, `AgentId`, `GenerationStrategy`, `DEMO_TENANT_ID` |
| `workflow` | `ProductionState`, `HAPPY_PATH`, `ALLOWED_TRANSITIONS`, `assert_transition`, `progress_pct`, `ProductionEvent` |
| `manifest` | `ProductionManifest` → `Scene` → `Shot` (+ visual/performance/audio specs, `ProviderPlan`, `ProviderAttempt`, `AssetRef`, `Disclosure`, captions, soundtrack, audit), `dependents_of()` |
| `agents` | `AGENT_DEFINITIONS` (10), typed inputs/outputs per agent, `AgentRun`, `AgentContext`, `Agent`, `AgentRegistry` |
| `cost` | `PriceCatalogEntry`, `CostEstimate`, `Budget`, `ReservationRequest`, `LedgerEvent`, `CostSummary`, `CostOverview`, `CreditBalance`, `BudgetService`, `PriceCatalog`, `CostEstimator`, errors |
| `providers` | `ProviderCapability`, `PriceUnit`, `ProviderRequest/Response/Usage/Info`, `Provider`, `ProviderRegistry`, `PaidCallGuard`, errors |
| `media` | `AssetRecord`, `LicenseInfo`, `RightsDecision`, `StorageBackend`, `RightsGate`, `AssetRepository`, `storage_key()` |
| `review` | `ReviewFinding`, `ReviewReport`, `Severity`, `ReviewGate`, `RetryScope` |
| `theme` | `ThemeProfile`, `ThemeSummary`, `ProductionModePolicy` |
| `jobs` | queue names, job dotted paths, `TaskQueue` |
| `repositories` | `ProductionRepository`, `AgentRunRepository`, errors |
| `api` | REST DTOs (below) |

Shared helpers (integrator-owned): `cineforge.config.Settings`, `cineforge.db`,
`cineforge.configuration` (themes/modes loader), `cineforge.runtime`
(composition root), `cineforge.testing.sample_manifest()`.

## 2. Factory functions (composition root)

`cineforge.runtime.Runtime` lazily calls these. Names and signatures are fixed.

| Factory | Returns | Owner |
|---|---|---|
| `cineforge.persistence.factory.build_repositories(settings)` | `Repositories(productions, agent_runs)` | B |
| `cineforge.orchestration.factory.build_task_queue(settings)` | `TaskQueue` (`redis` = RQ, `inline` = synchronous) | B |
| `cineforge.agents.factory.build_agent_registry(settings)` | `AgentRegistry` with all 10 agents | B |
| `cineforge.cost.factory.load_price_catalog(settings)` | `PriceCatalog` from `packages/configurations/pricing/<version>.yaml` | D |
| `cineforge.cost.factory.build_budget_service(settings)` | `BudgetService` (memory or Postgres per `PERSISTENCE_BACKEND`) | D |
| `cineforge.cost.factory.build_cost_estimator(settings, catalog)` | `CostEstimator` | D |
| `cineforge.media.factory.build_storage(settings)` | `StorageBackend` (`local`; `supabase` stub) | D |
| `cineforge.media.factory.build_asset_repository(settings)` | `AssetRepository` (memory or Postgres) | D |
| `cineforge.media.factory.build_rights_gate(settings)` | `RightsGate` (fail closed) | D |
| `cineforge.providers.factory.build_provider_registry(settings)` | `ProviderRegistry` with mock providers | D |
| `cineforge.providers.factory.build_paid_call_guard(settings, budget, catalog)` | `PaidCallGuard` | D |

Memory backends are per-process and exist for unit tests (`PERSISTENCE_BACKEND=memory`,
`QUEUE_BACKEND=inline`). Docker uses Postgres + Redis.

## 3. Jobs and queues

| Constant | Value |
|---|---|
| `QUEUE_AGENTS` | `cineforge-agents` (agent worker) |
| `QUEUE_MEDIA` | `cineforge-media` (media worker, has FFmpeg) |
| `JOB_ADVANCE_PRODUCTION` | `cineforge.orchestration.jobs.advance_production(production_id, tenant_id, idempotency_key)` (B) |
| `JOB_RENDER_MASTER` | `cineforge.media.jobs.render_master(production_id, tenant_id, idempotency_key)` (D) |

Job functions use `cineforge.runtime.get_runtime()` for dependencies, are idempotent,
and take keyword arguments only.

## 4. Mock workflow semantics (ENG-02)

One `advance_production` call executes the **current** state's work, transitions,
and enqueues the next call (sleep `MOCK_STEP_DELAY_SEC` between steps for demo
visibility). Agents are invoked only through `AgentRegistry.invoke` (schema
validated) and providers only through `PaidCallGuard.call` (budget reserved first).

| From state | Work | Next |
|---|---|---|
| `DRAFT` (via `POST /run`) | transition only | `RESEARCHING` |
| `RESEARCHING` | A1 plan, A4 treatment, A2 research, A3 media discovery; then the orchestrator (not the agent) applies `RightsGate` to every candidate license and rewrites `AssetSelection.selected_ids/blocked` (unknown rights are blocked) | `SCRIPTING` |
| `SCRIPTING` | A5 script | `STORYBOARDING` |
| `STORYBOARDING` | A6 scene graph → `manifest.scenes`; orchestrator runs `CostEstimator.estimate` → A10 (`CostPlanningInput.estimate`) → `CostPlan`; per-shot/scene `estimated_cost` and `manifest.budget.estimated` updated; scene budgets via `set_limit` | `AWAITING_APPROVAL`, or `PAUSED_BUDGET` if estimate > limit |
| `AWAITING_APPROVAL` | gate; if `manifest.approval.auto_approve` continue immediately | `GENERATING` (after `POST /approve`) |
| `GENERATING` | per shot A7 (bounded attempts = mode `max_attempts_per_shot`, attempts recorded on `Shot.attempts`), A8 audio (narration per scene, music, lip-sync where `lip_sync_required`) | `ASSEMBLING`; `PAUSED_BUDGET` on `BudgetExceededError`; `FAILED` if a shot exhausts attempts |
| `ASSEMBLING` | if no `master_render_asset_id`: enqueue `JOB_RENDER_MASTER` on `QUEUE_MEDIA` and stop; media job renders, then enqueues advance | `REVIEWING` once master exists |
| `REVIEWING` | A9 review (`ReviewInput` incl. `MasterRender`) → findings into manifest | `READY`, or `NEEDS_REVIEW` if any blocking finding |
| `READY` | stop; `POST /deliver` | `DELIVERED` |

Idempotency keys: agent runs `"{production_id}:{state}:{agent_id}:{scope}:{attempt}"`;
ledger reservations `"{agent_run_key}:{provider}:{model}"`; jobs `job_id="{production_id}:{state}:{n}"`.

Phase 0 agents MUST NOT parse provider output text. They build typed artifacts
deterministically from the brief/theme (mock reasoning) and use provider calls for
cost accounting and attached notes.

## 5. REST API (`/api/v1`, OpenAPI at `/docs`, `/openapi.json`)

Tenant: optional header `X-Tenant-Id` (default `DEFAULT_TENANT_ID`). Errors use
`ErrorResponse`: 404 not found, 409 invalid state transition, 422 validation.

| Method & path | Body | Response |
|---|---|---|
| `GET /health/live` | | `{"status": "ok"}` (no dependency checks) |
| `GET /health` | | `HealthResponse` (database, redis, storage checks) |
| `GET /api/v1/agents` | | `AgentDefinition[]` |
| `GET /api/v1/themes` | | `ThemeSummary[]` |
| `GET /api/v1/themes/{theme_id}` | | `ThemeProfile` |
| `GET /api/v1/modes` | | `ProductionModePolicy[]` |
| `GET /api/v1/pricing` | | `PriceCatalogEntry[]` |
| `GET /api/v1/costs/overview` | | `CostOverview` |
| `GET /api/v1/productions` | | `ProductionSummary[]` (newest first) |
| `POST /api/v1/productions` | `CreateProductionRequest` | 201 `ProductionDetail` (state `DRAFT`, budget created) |
| `GET /api/v1/productions/{id}` | | `ProductionDetail` |
| `POST /api/v1/productions/{id}/run` | | 202 `ActionResponse` (DRAFT → RESEARCHING, job enqueued) |
| `POST /api/v1/productions/{id}/approve` | `ApproveProductionRequest` | 202 `ActionResponse` (AWAITING_APPROVAL or PAUSED_BUDGET → GENERATING) |
| `POST /api/v1/productions/{id}/cancel` | | `ActionResponse` |
| `POST /api/v1/productions/{id}/deliver` | | `ActionResponse` (READY → DELIVERED) |
| `GET /api/v1/productions/{id}/costs` | | `CostSummary` |
| `GET /api/v1/productions/{id}/ledger` | | `LedgerEvent[]` |
| `GET /api/v1/assets/{asset_id}/content` | | binary stream (tenant-scoped; 404 for other tenants) |

`ProductionDetail.artifacts` is assembled from the latest succeeded `AgentRun.output`
per `output_model` (`ProductionPlan`, `CreativeTreatment`, `ResearchBrief`,
`AssetSelection`, `Script`, `CostPlan`, `ReviewReport`, `MasterRender`).

The dashboard calls the API same-origin: Next.js rewrites `/api/v1/*` and `/health`
to `API_INTERNAL_URL` (default `http://api:8000` in Docker, `http://localhost:8000` locally).

## 6. Database (Supabase Postgres)

Schema: `supabase/migrations/20261013000000_phase0_schema.sql`. Tables: `tenants`,
`theme_profiles`, `price_catalog`, `productions` (manifest JSONB + denormalized
columns), `production_events`, `agent_runs`, `review_findings`, `budgets`
(`scope_key` = `production` | `scene:<id>`, CHECK reserved+actual <= limit),
`cost_ledger`, `credit_balances`, `assets`, `asset_licenses`, `asset_usages`.
`Money` columns are `numeric(18,6)`.

Local: `postgresql://postgres:postgres@127.0.0.1:54322/postgres` (host) /
`host.docker.internal:54322` (containers). Cloud later: change `DATABASE_URL` only.

## 7. Storage

`StorageBackend` keys come from `storage_key(tenant_id, production_id, kind, filename)`:
`tenants/<tenant>/productions/<id>/<kind>/<file>`. Local backend root
`STORAGE_LOCAL_ROOT` = `/data/media` in Docker on the named volume `cineforge-media`
(persists across restarts; never in Git). Asset URIs: `local://<key>` or
`supabase://<bucket>/<key>`.

## 8. Mock providers and prices

Provider names/models/units are those in `packages/configurations/pricing/mock-2026-10.yaml`.
All mock providers have `is_mock=True, is_paid=False`; their costs are **simulated**
but still go through reservation → commit so accounting is exercised end to end.
`PaidCallGuard` raises `PaidProviderNotAllowedError` for any `is_paid=True` provider
unless `ALLOW_PAID_PROVIDERS=true`. `MOCK_FAILURE_RATE` makes mock media providers
fail deterministically (seeded by idempotency key) to exercise bounded retries.

## 9. Phase 1 additions (research and preproduction)

### Settings

| Setting | Default | Meaning |
|---|---|---|
| `PROVIDER_MODE` | `mock` | `mock`: only mock providers route. `live`: enabled + ready real providers win by priority |
| `ALLOW_PAID_PROVIDERS` | `false` | Hard switch for any `is_paid` provider (guard + router) |
| `PRICE_CATALOG_VERSION` | `mock-2026-10,open-sources-2026-10,anthropic-2026-10` | Comma list, merged; entries keep their own version |
| `SECRETS_BACKEND` | `vault` | `vault` = Supabase Vault (encrypted, shared by api + workers); `memory` = tests |
| `ANTHROPIC_API_KEY` | empty | Env key wins over a stored key |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Must exist in the price catalog (unknown price fails closed) |

### Providers and routing (ENG-12)

- `ProviderRegistry.route(capability, tenant_id=...)` returns the READY provider with the
  lowest priority; `route_all` returns all READY ones (federated media search). Agents use
  these, not `for_capability`. Readiness rules: `cineforge/providers/registry.py` docstring.
- `ProviderStatus`: `ready | missing_key | disabled | blocked_paid_off | blocked_mock_mode | planned`.
- Defaults: mock and free providers enabled, paid disabled; real priority 10, mock 100.
- `ProviderSetting` rows (`provider_settings` table) override defaults per tenant.
- `SecretStore` is write-only from the API: keys are stored under the provider name and
  never returned; the catalog shows `key_source` and a `key_hint` (`...a1b2`).
- Payloads: LLM structured output via `parameters["response_schema"]` ->
  `output_data["structured"]`; research -> `output_data["sources"]` (`ResearchSource[]`);
  media search -> `output_data["items"]` (`MediaSearchItem[]`).
- `ProviderUsage.breakdown` (e.g. `1k_input_tokens` + `1k_output_tokens`) is priced line by
  line by the guard; the ledger row records the aggregate `1k_tokens`.

| Factory | Returns | Owner |
|---|---|---|
| `cineforge.persistence.factory.build_theme_repository(settings)` | `ThemeRepository` (memory / Postgres `theme_profiles`) | B |
| `cineforge.providers.factory.build_secret_store(settings)` | `SecretStore` (`vault` / `memory`) | D |
| `cineforge.providers.factory.build_provider_settings_repository(settings)` | `ProviderSettingsRepository` (memory / Postgres) | D |
| `cineforge.providers.factory.build_provider_registry(settings, *, secrets, provider_settings)` | `ProviderRegistry` (mock + real + planned) | D |

### Workflow changes

- A2 cites only fetched sources; a claim whose URL was not fetched or whose excerpt is not in
  the source text is downgraded to `unverified` (ENG-04). A5 never cites unverified,
  disputed or rejected claims (`ScriptInput.excluded_claim_ids`).
- At `AWAITING_APPROVAL` reviewers record `ClaimReview`s (`manifest.claim_reviews`).
  Approval is refused (409) while a script line cites a rejected claim; the operator can
  send the production back to scripting (`AWAITING_APPROVAL -> NEEDS_REVIEW -> SCRIPTING`).
- A8 runs once per scene (`include_music=false`, scope `scene_id`) and once for music
  (`include_narration=false`, scope `music`), each with bounded retries.
- Ledger rows carry `status_reason` (release/failure reason, or `overspend: ...` when the
  committed actual exceeds the reservation).

### REST additions (`/api/v1`)

| Method & path | Body | Response |
|---|---|---|
| `GET /providers` | | `ProvidersOverview` (groups per capability) |
| `PATCH /providers/{name}` | `UpdateProviderRequest` | `ProviderCatalogEntry` |
| `PUT /providers/{name}/key` | `SetProviderKeyRequest` | `ProviderCatalogEntry` (key never echoed) |
| `DELETE /providers/{name}/key` | | `ProviderCatalogEntry` |
| `POST /providers/{name}/test` | | `ProviderTestResult` (free check where possible) |
| `GET /themes/{id}?version=N` | | `ThemeProfile` |
| `GET /themes/{id}/versions` | | `ThemeProfile[]` (oldest first) |
| `POST /themes/{id}/versions` | `CreateThemeVersionRequest` | 201 `ThemeProfile` (409 if `base_version` is stale) |
| `POST /productions/{id}/claims` | `ReviewClaimsRequest` | `ProductionDetail` (AWAITING_APPROVAL / PAUSED_BUDGET only) |
| `POST /productions/{id}/rewrite-script` | | 202 `ActionResponse` (back to SCRIPTING, rejected claims excluded) |

Database: `supabase/migrations/20261014000000_phase1_providers.sql` adds
`provider_settings`, `cost_ledger.status_reason` and enables `supabase_vault`.

## 10. Phase 2 additions (first real video)

### Media

- `cineforge.media.ingest.ingest_still` downloads a rights-APPROVED A3 candidate (Commons
  1920 px rendition / Openverse original) into storage as an `AssetRecord` (kind `image`,
  `metadata.candidate_id`), once per candidate. Downloads are https-only, size-capped and
  refuse private addresses.
- `cineforge.media.edit` replaces the slate renderer (`RENDERER = "ffmpeg-edit-v1"`). Per
  shot it uses the latest real generated clip, else an ingested still (Ken Burns), else a
  slate. Narration audio is placed per scene; captions are burned in; synthetic shots
  carry their `disclosure.label_text`; a 3 s attribution card closes the master and is
  part of the expected duration.
- `render_master(..., force=True)` re-renders a READY production as `master_v{n+1}`
  without a state change (audit `master_rerendered`).

### External generations

Media generated outside the engine (Phase 2 step one: Higgsfield through MCP, driven by
an operator) still follows reserve, then generate, then commit:

1. `POST /productions/{id}/external-generations` reserves `quoted_credits` x catalog
   price through `BudgetService.reserve`. It fails closed: 403 `paid_providers_disabled`
   unless `ALLOW_PAID_PROVIDERS=true`, 422 `unknown_price` without a catalog entry
   (unit `credit`), 409 `budget_exceeded` over the production budget or `credit_cap`.
2. The operator runs the generation with the provider.
3. `POST .../external-generations/{event_id}/complete` downloads `result_url` (provider
   host allowlist only), registers a `GENERATED` asset (`license_type="generated"`,
   `metadata.derived_from` = source still license/attribution), binds it to the shot
   (`AssetRole.GENERATED`, `disclosure.synthetic_media`) or scene (`AssetRole.AUDIO`),
   appends a `ProviderAttempt` and commits the ledger row with `credits_used`.
4. `POST .../external-generations/{event_id}/release` frees a reservation on failure.

Allowed states: `AWAITING_APPROVAL`, `PAUSED_BUDGET`, `NEEDS_REVIEW`, `READY` (else 409
`invalid_state`). A source still that is not rights-approved at completion gives 409
`rights_blocked` and the row is marked failed with the credits spent. A refused download
(host, type, size) gives 422 and leaves the reservation open for a retry or release.

| Method & path | Body | Response |
|---|---|---|
| `GET /productions/{id}/generation-pack` | | `GenerationPack` |
| `POST /productions/{id}/external-generations` | `ExternalGenerationRequest` | 201 `ExternalGenerationResponse` |
| `POST /productions/{id}/external-generations/{event_id}/complete` | `ExternalGenerationComplete` | `ExternalGenerationResponse` |
| `POST /productions/{id}/external-generations/{event_id}/release` | `ExternalGenerationRelease` | `ExternalGenerationResponse` |
| `POST /productions/{id}/render` | `RenderRequest` | 202 `ActionResponse` (READY only) |

Prices: `packages/configurations/pricing/higgsfield-2026-10.yaml` (USD per plan credit).

## 11. Phase 3 additions (fully generative host vlogs)

### Personas and themes

A persona is a recurring AI host (`cineforge.contracts.persona`). One folder per persona:

```
packages/configurations/personas/
  _template/            copy this to start a new persona (ignored by the loader)
  <id>/persona.v<N>.yaml  PersonaProfile, immutable once used; add a new version
  <id>/canon.yaml         PersonaCanon: facts, running jokes, curated past trips
```

- `PersonaProfile`: `identity` (age 18+, origin, backstory), `look` (description, `locks`
  that never change, `avoid`), `wardrobe`, `personality`, `voice` (provider voice id plus
  sampled `candidates`), `delivery` (pace, catchphrases, greeting, sign-off, words to
  avoid), `content` (niches, topics to avoid), `camera`, `provider_refs` (e.g. the
  Higgsfield element id), `references`, `ownership`, `disclosure`.
- Reference images are owned media, never footage and never in Git. They live in storage at
  `persona_storage_key(tenant, id, file)` = `tenants/<t>/personas/<id>/references/<file>`;
  the profile pins each by `sha256` and `angle`. Ingest with
  `uv run python scripts/ingest_persona_refs.py <id> <folder>` (prints the
  `references:` block).
- Loaded with `cineforge.configuration.get_persona` / `load_canon`. The theme names the
  host in `performance.persona_id`; `create_production` copies it to
  `ProductionManifest.persona_id` and pins `persona_version`.
- Episode memory: `WorkflowEngine.persona_canon` merges `canon.yaml` with the tenant's
  READY / DELIVERED productions of that persona. A5 gets it as `ScriptInput.canon`.
- Stored rows written before the rename (`character_id`) still load.

| Method & path | Response |
|---|---|
| `GET /personas` | `PersonaSummary[]` (latest version each) |
| `GET /personas/{id}?version=` | `PersonaDetail` (profile, canon, reference status, versions) |
| `GET /personas/{id}/references/{ref_id}` | image bytes (404 until ingested for the tenant) |

- `ProductionRules.generative` (`GenerativeRules`) makes a theme fully generative: models
  for the storyboard `still`, the talking `a_roll` and the POV `b_roll` (each with
  duration limits and `credits` / `credits_per_sec` estimates), `voice_model` /
  `voice_credits`, `pilot_shots`, `credit_cap` and `max_context_refs`. Public images are
  context references for the image model only; they never appear on screen.

### Planning

- A5 writes `ScriptLine.kind` `dialogue` (host to camera) or `broll`, with a `visual`. Code
  trims lines to the A-roll limit (`words_per_sec`), keeps the last scene dialogue only and
  appends the CTA (`cineforge.agents.vlog.build_vlog_script`).
- A6 makes one shot per line: `Shot.kind` `a_roll` (with `audio.dialogue_text`,
  lip-sync) or `b_roll`, `provider_plan.parameters.still_prompt` (A-roll includes the
  persona element `<<<id>>>` and look locks), the clip prompt, and `Disclosure(synthetic_media=True)`.
- The estimate is credit based (`cineforge.cost.vlog.estimate_vlog`); scene caps are not
  allocated (the credit cap bounds spend). Default budget: `credit_cap` x credit price + $1.

### Authored briefs (look + script)

`CreateProductionRequest` takes two optional fields for generative themes; both are copied
to the manifest (`ProductionManifest.look`, `.authored_script`):

- `look` (`ProductionLook`): trip `wardrobe` (overrides the persona default), `location`
  bible and `notes` (added to every still prompt), and `references`
  (`ProductionReference`: `ref_<name>` id -> an APPROVED library asset, `reference_only`).
- `script` (`AuthoredScript`, 2-24 `ScriptLine`s): A5 uses it as written, no LLM call
  (`cineforge.agents.vlog.script_from_authored`). Per line: `motion`, `sound`,
  `on_screen_text` (-> `Shot.on_screen_text`), `refs`, `duration_sec`. A `broll` line with
  `voiceover: true` is spoken over the cutaway (`AudioSpec.voiceover`, a voice line but no
  lip-sync); `in_frame: true` puts the host in a cutaway.
- `create_production` fails with 422 `invalid_production_input` if the theme is not
  generative, a reference asset is missing or not APPROVED, a line names an unknown ref, or a
  spoken line has more words than its shot can hold (no silent trimming).
- Shot references are uploaded to the provider once (`HiggsfieldProvider.upload_media`,
  free) and cached in `ProductionReference.provider_media`; a shot with refs uses them as
  `image_references` instead of the public context images.
- Review before spending: `uv run python scripts/shot_sheet.py <brief.yaml>` prints every
  shot's exact still, motion and voice prompts with credits; `--json` prints the API body.

| Method & path | Body | Response |
|---|---|---|
| `POST /assets/references?name=&author=&commercial_use=&license_type=&generator=` | raw png / jpeg / webp (max 25 MB) | 201 `AssetRecord` (`kind=reference`, rights evaluated) |

### Gates (`ProductionManifest.approval_stage`)

`script` -> `preview` -> `pilot` -> `final`. Each approval moves to the next stage and
runs only its work (`cineforge.orchestration.studio.VlogStudio`):

| Stage | Work | Then |
|---|---|---|
| `preview` | one still per shot (A7 `stage="still"`), one voice line per spoken shot: A-roll or voice-over (A8 `dialogue_shot_id`) | `AWAITING_APPROVAL` |
| `pilot` | the first A-roll and B-roll clips | `AWAITING_APPROVAL` |
| `final` | every remaining clip | `ASSEMBLING` |

Clips animate their still (`medias` role `start_image` = the still's provider job id); A-roll
clips lip-sync to the voice line (`audio_references`). Results are downloaded from the
provider CDN allowlist and registered with provenance (`external.store_result`): stills
`KEYFRAME`, voice `AUDIO` (`audio.dialogue_ref`), clips `GENERATED`. Per-shot progress is
kept in `provider_plan.parameters.stages`.

When the provider is not signed in, calls route to the mock providers. In
`PROVIDER_MODE=live`, approval is refused (409 `approval_blocked`) until the provider is
signed in, the persona has a voice and the next stage fits the credit cap. A call that
would pass `credit_cap` pauses the production (`PAUSED_BUDGET`).
A provider error during a stage keeps the finished work and returns the production to the
previous gate (`AWAITING_APPROVAL`, event `stage_failed`); approving again retries only the
missing calls.

### Redo

`POST /productions/{id}/shots/{shot_id}/regenerate` (`RegenerateShotRequest`: `target`
`still` | `voice` | `clip`, optional `note`, `dialogue_text` for voice) queues
`JOB_REGENERATE_SHOT` on the agents queue. Allowed at the preview, pilot and final gates for
a stage the shot already has (else 409 `regenerate_blocked`). The production stays at the
gate; a new still or voice line marks the shot's clip stale so the next stage redoes it.

| Method & path | Body | Response |
|---|---|---|
| `GET /productions/{id}/stage-quote` | | `StageQuote` (404 for classic themes) |
| `POST /productions/{id}/shots/{shot_id}/regenerate` | `RegenerateShotRequest` | 202 `ActionResponse` |
| `POST /providers/{name}/oauth/start` | | `OAuthStartResponse` |
| `GET /providers/{name}/oauth/callback` | | 303 to the dashboard Sources page |
| `GET /providers/{name}/connection` | | `ConnectorStatus` |
| `DELETE /providers/{name}/oauth` | | `ConnectorStatus` |

Prices: `packages/configurations/pricing/higgsfield-2026-10b.yaml`.
