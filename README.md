# CineForge AI

Theme-driven, multi-agent cinematic video production platform for YouTube Shorts,
TikTok and Instagram Reels.

**Phase 0 - Foundation.** A working vertical slice of the production engine (PRD 3):
10 logical agents, a typed production manifest, a scene-by-scene mock workflow,
budget-enforced cost accounting, rights-gated media metadata, an FFmpeg master
render, and a dashboard - all with **mock providers, no credentials and no paid API calls**.

## Quick start

Prerequisites: Docker Desktop, [Supabase CLI](https://supabase.com/docs/guides/local-development/cli/getting-started),
[uv](https://docs.astral.sh/uv/), Node.js >= 20.9 (Homebrew: `brew install uv supabase/tap/supabase node`).

```bash
make setup     # check tools, uv sync, npm install, create .env from .env.example
make up        # supabase start (Postgres) + docker compose up -d --build
make demo      # create + run a sample "Time Traveler" production
```

| URL | What |
|---|---|
| http://localhost:3000 | Dashboard (productions, workflow, scenes, agents, costs, master render) |
| http://localhost:8000/docs | API documentation (OpenAPI) |
| http://localhost:8000/health | Health of database, Redis and media storage |

In the dashboard: **Productions → New production** (or "Create sample production"),
**Run**, review the storyboard and estimated cost, **Approve**, watch generation,
assembly and QC, play the rendered master, then **Deliver**.

## Commands

| Command | Purpose |
|---|---|
| `make up` / `make down` | Start / stop services (`down` keeps DB, Redis data and media) |
| `make down-all` | Also stop the Supabase stack |
| `make restart`, `make rebuild` | Restart; rebuild images without cache |
| `make logs [s=api]`, `make ps`, `make shell s=worker` | Observe services |
| `make test` | Python unit/integration + dashboard tests |
| `make test-integration` | Postgres-backed tests (needs `make db-start`) |
| `make test-e2e` | End-to-end against the running stack |
| `make test-docker` | Python suite inside the media-worker image (FFmpeg) |
| `make lint`, `make fmt` | Ruff + ESLint + TypeScript checks / auto-format |
| `make contracts`, `make contracts-check` | Regenerate / verify JSON Schema + TS types |
| `make db-reset` | **Destructive**: re-apply migrations + seed |
| `make check-media` | Fail if Git tracks media, large files or secrets |
| `make clean-media CONFIRM=1` | **Destructive**: delete the media volume |

Without Docker: `uv sync && uv run pytest -q` and `npm install && npm test --workspace @cineforge/dashboard`.

## Architecture

```
Dashboard (Next.js) ──/api/v1 proxy──▶ API (FastAPI) ──▶ Postgres (Supabase local)
                                          │ enqueue
                                          ▼
                                    Redis (RQ queues)
                         ┌────────────────┴─────────────────┐
                 agent worker (A1–A10)            media worker (FFmpeg)
                         └──── PaidCallGuard → mock providers ┘
                                          │
                           media volume (cineforge-media, persistent)
```

- **One engine package** (`packages/engine`, import `cineforge`) holds contracts and all
  domain logic; services are thin entrypoints. Logical agents share one worker process.
- **Contracts first:** Pydantic models are the source of truth; JSON Schema and
  TypeScript types are generated into `packages/schemas`.
- **Deterministic guards:** state machine, budget reservations, rights gate and
  render validation are code, not LLM decisions.
- Details: [docs/architecture/overview.md](docs/architecture/overview.md),
  [docs/architecture/contracts.md](docs/architecture/contracts.md),
  [docs/agents/README.md](docs/agents/README.md).

## Repository layout

```
apps/dashboard/            Next.js 16 + TypeScript + Tailwind v4 dashboard
services/api/              FastAPI app (cineforge_api)
services/worker/           RQ agent worker (cineforge_worker)
services/media-worker/     RQ media worker with FFmpeg (cineforge_media_worker)
packages/engine/           Python package `cineforge`
  src/cineforge/contracts/   frozen shared contracts (manifest, agents, cost, media, API)
  src/cineforge/agents/      agent registry + 10 logical agents
  src/cineforge/orchestration/ workflow engine, queues, jobs
  src/cineforge/persistence/ production + agent-run repositories (memory, Postgres)
  src/cineforge/cost/        price catalog, estimator, budget service + ledger
  src/cineforge/providers/   mock providers, registry, PaidCallGuard
  src/cineforge/media/       storage, rights gate, asset repo, FFmpeg render job
packages/schemas/          generated JSON Schema + TS types + sample manifest fixture
packages/prompts/          versioned prompt templates per agent
packages/configurations/   themes, production modes, simulated price catalog
supabase/                  Supabase CLI config, migrations, seed
infrastructure/docker/     Dockerfiles (python app/media targets, dashboard)
docs/                      architecture, agents, development guides
tests/e2e/                 cross-workstream end-to-end tests
.cursor/rules/, AGENTS.md  guidance for parallel coding agents
```

## Media, secrets and cost policy

- Git never contains generated or downloaded media, renders, caches, credentials or
  keys (`.gitignore`, `.dockerignore`, `make check-media`, CI hygiene job).
- Media binaries go to the storage backend: the `cineforge-media` Docker volume
  (`/data/media`, survives restarts) or `var/media` on the host. Postgres stores metadata,
  license snapshots, content hashes, provenance and usage cost.
- Every provider call goes through `PaidCallGuard`: price lookup → atomic budget
  reservation → call → commit. Paid providers are refused unless `ALLOW_PAID_PROVIDERS=true`
  (hard-coded `false` in `compose.yaml`). Phase 0 costs are **simulated**.

## Configuration

All configuration is environment-based (`.env.example`). Moving to Supabase Cloud
later means changing `DATABASE_URL` (and `SUPABASE_URL`/keys for storage) - no code
changes. See [docs/development/supabase.md](docs/development/supabase.md).

## Development

See [AGENTS.md](AGENTS.md) (ownership, rules, worktrees) and
[docs/development/](docs/development/setup.md) (setup, Docker, Supabase, testing, workflow).
