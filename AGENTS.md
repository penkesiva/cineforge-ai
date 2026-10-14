# AGENTS.md - CineForge AI

Guidance for human and AI coding agents working in this repository.

## Product in one paragraph

CineForge AI is a theme-driven, multi-agent cinematic short-video engine (PRD 3)
consumed later by an automated content channel (PRD 1) and a promotional video
studio (PRD 2). Agents make creative/planning decisions through typed artifacts;
deterministic code handles budgets, rights, state, timing, encoding and job execution.

## Architecture

```
apps/dashboard            Next.js + TS + Tailwind dashboard (port 3000)
services/api              FastAPI (port 8000): thin routes over the engine
services/worker           RQ worker for queue cineforge-agents (all 10 logical agents)
services/media-worker     RQ worker for queue cineforge-media (FFmpeg)
packages/engine           Python package `cineforge` - contracts + all domain logic
packages/schemas          GENERATED JSON Schema + TS types (+ sample fixture)
packages/prompts          Versioned prompt templates per agent
packages/configurations   Themes, production modes, price catalogs (YAML)
supabase/                 Supabase CLI config, migrations, seed
infrastructure/docker     Dockerfiles
```

Read `docs/architecture/contracts.md` before writing code.

## Golden rules

1. **Contracts are frozen.** `packages/engine/src/cineforge/contracts/`, `supabase/migrations/`,
   `packages/configurations/`, `cineforge/config.py`, `cineforge/runtime.py`,
   `cineforge/db.py`, `cineforge/configuration.py`, `cineforge/testing.py`, and
   `packages/schemas/` change only through the integrator. Need a change? Stop and report it.
2. **No binary media in Git.** No images, video, audio, renders, caches or generated
   output. Runtime media goes to the storage backend (`var/media` or the
   `cineforge-media` Docker volume). Only tiny approved fixtures under `tests/fixtures/approved/`.
3. **No secrets in Git.** Use `.env` (ignored). `.env.example` holds placeholders only.
4. **No paid API calls** without explicit human approval. Only mock providers exist in
   Phase 0. Every provider call goes through `PaidCallGuard` (budget reservation first).
5. **No new dependencies** without a stated reason. Python deps are declared and
   locked by the integrator; the dashboard owner may add JS deps under `apps/dashboard`.
6. **Stay in your lane.** Only edit files your workstream owns (table below).
7. **Tests are mandatory.** Every change ships with tests; your workstream's test command must pass.

## Workstream ownership (Phase 0 and Phase 1)

| Workstream | Branch | Owns (exclusive write access) |
|---|---|---|
| Integrator | `phase0/foundation` | contracts (rule 1), `AGENTS.md`, `README.md`, `docs/architecture/`, `tests/` (e2e), root `pyproject.toml`, `uv.lock`, root `package.json` |
| A - Platform | `phase0/a-platform` | `infrastructure/`, `compose.yaml`, `Makefile`, `.github/`, `.dockerignore`, `.cursor/rules/`, `scripts/` (except `export_contracts.py`, `generate_seed.py`), `docs/development/` |
| B - Engine core | `phase0/b-engine` | `services/api/`, `services/worker/`, `cineforge/agents/`, `cineforge/orchestration/`, `cineforge/persistence/`, `packages/prompts/`, `docs/agents/` |
| C - Dashboard | `phase0/c-dashboard` | `apps/dashboard/`, `package-lock.json` |
| D - Cost & media | `phase0/d-cost-media` | `cineforge/cost/`, `cineforge/media/`, `cineforge/providers/`, `services/media-worker/`, `supabase/seed.sql`, `scripts/generate_seed.py` |

Engine tests live next to the code they test: `packages/engine/tests/<area>/`
(`agents`, `orchestration`, `persistence` for B; `cost`, `media`, `providers` for D).

## Git and worktrees

- Integration branch: `phase1/foundation` (Phase 1; `phase0/foundation` for Phase 0), branches
 `phase1/<x>`. `main` only receives reviewed PRs after all
  acceptance criteria pass.
- One worktree per workstream: `git worktree add ../cineforge-ai-wt/<x> -b phase1/<x> phase1/foundation`.
- Small, focused commits: `<area>: <imperative summary>` (e.g. `cost: add postgres budget reservations`).
- Never rewrite shared history, never force-push shared branches, never commit to `main` directly.

## Commands

```bash
uv sync                                  # Python deps (workspace)
uv run pytest -q                         # all Python tests (integration tests skip without DB)
uv run pytest -m integration             # needs `supabase start` (+ redis for queue tests)
uv run ruff check . && uv run ruff format --check .
npm install && npm run contracts:types   # TS contract types
uv run python scripts/export_contracts.py --check
make help                                # Docker/dev shortcuts (after Workstream A)
```

## Coding conventions

- Python 3.12, Pydantic v2, type hints everywhere, `ruff` clean, sync code (FastAPI
  sync endpoints are fine). No global mutable state outside `cineforge.runtime`.
- Money is `Decimal` (`cineforge.contracts.common.money`); never float math for budgets.
- Inter-agent hand-offs are contract models, never free-form prose.
- TypeScript strict mode; import contract types from `@cineforge/schemas`, never hand-copy them.
- UI: never `window.alert`/`window.confirm`; use `AppNoticeDialog` / `AppConfirmDialog`.
