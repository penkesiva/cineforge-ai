# Architecture Overview (Phase 0)

CineForge implements PRD 3 (Cinematic Production Engine). PRD 1 (automated channel)
and PRD 2 (promotional studio) will consume it through the same API; Phase 0 only
prepares for them (tenant IDs everywhere, versioned themes, export profiles).

## Principles

1. **Agents decide, code enforces.** Agents emit typed artifacts. Budget caps,
   rights, state transitions, idempotency and render validation are deterministic.
2. **Contracts first.** `cineforge.contracts` (Pydantic) is the single source of truth,
   exported to JSON Schema and TypeScript. See [contracts.md](contracts.md).
3. **Logical agents, shared workers.** 10 agents run in one worker process; one media
   worker owns FFmpeg. No container per agent.
4. **Cost before spend.** Every provider call: price lookup, atomic reservation,
   invoke, reconcile. Hard caps cannot be bypassed by prompts.
5. **Fail closed on rights.** Unknown or uncertain licenses are never auto-approved.
6. **References, not blobs.** Postgres holds metadata/provenance; binaries live in
   object storage; Git holds neither.

## Runtime topology

| Service | Process | Responsibilities |
|---|---|---|
| `dashboard` | Next.js 16 | UI; proxies `/api/v1/*` and `/health` to the API at request time |
| `api` | FastAPI + uvicorn | REST + OpenAPI, validation, enqueueing, detail assembly, asset streaming (HTTP Range) |
| `worker` | RQ, queue `cineforge-agents` | `advance_production`: one workflow state per job, agents A1–A10 |
| `media-worker` | RQ, queue `cineforge-media`, FFmpeg | `render_master`: slate render, ffprobe QC, asset registration |
| `redis` | Redis 7 | Durable job queues |
| Supabase (CLI) | Postgres 17 | Productions, events, agent runs, budgets, cost ledger, assets, licenses |

`cineforge.runtime.Runtime` is the composition root: it builds repositories, queue,
agent registry, price catalog, budget service, estimator, storage, rights gate,
provider registry and paid-call guard from environment settings. Memory backends +
an inline queue run the whole pipeline in one process for tests.

## Workflow

`DRAFT → RESEARCHING → SCRIPTING → STORYBOARDING → AWAITING_APPROVAL → GENERATING →
ASSEMBLING → REVIEWING → READY → DELIVERED`, with `PAUSED_BUDGET`, `NEEDS_REVIEW`,
`FAILED`, `CANCELLED`. Each step is an idempotent job; agent runs, ledger
reservations and jobs carry idempotency keys. Shots and audio retry up to the mode's
`max_attempts_per_shot`, then escalate to `FAILED`. Budget overruns pause at
`PAUSED_BUDGET` and resume after approval (optionally with a raised cap).
Step-by-step semantics: [contracts.md section 4](contracts.md#4-mock-workflow-semantics-eng-02).

## Data

- `productions.manifest` (JSONB) is the versioned Video Production Manifest with
  denormalized columns for listing; `production_events` is the audit trail.
- `budgets` (production and scene scopes, `CHECK reserved + actual <= limit`) and
  `cost_ledger` (one row per provider call: estimated, reserved, actual, retries,
  cache hits, credits) back the cost monitor. `price_catalog` is versioned and
  seeded from `packages/configurations/pricing/`.
- `assets`, `asset_licenses` (immutable snapshots) and `asset_usages` hold media
  metadata: source URL, license, content hash, production references, usage cost.

## Deployment path

Docker Compose on the MacBook Pro today; the same arm64 images run on the Mac mini M4.
GPU-heavy generation stays with approved cloud APIs (Phase 2+). Supabase Cloud and
Supabase Storage replace the local stack via environment configuration only.

## Phase 0 integration notes

- RQ job IDs may not contain `:`; the queue maps logical IDs
  (`{production_id}:{state}:{n}`) to RQ-safe IDs and keeps the original in job metadata.
- Computed review fields (`ReviewFinding.blocking`, `ReviewReport.passed`) are emitted
  on dump and ignored on load so persisted manifests round-trip.
- Mock media providers fail transiently at `MOCK_FAILURE_RATE` (Docker default 0.05)
  to exercise retries; tests pin it explicitly.
