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
