# Development workflow

## Branches

- `main`: only reviewed PRs after all acceptance criteria pass. Never commit directly.
- `phase0/foundation`: integration branch (integrator-owned). Workstreams branch from it.
- `phase0/<workstream>`: one branch per workstream (`a-platform`, `b-engine`,
  `c-dashboard`, `d-cost-media`).

Never rewrite shared history or force-push shared branches.

## Worktrees

One worktree per workstream, next to the main checkout:

```bash
git fetch origin
git worktree add ../cineforge-ai-wt/a-platform -b phase0/a-platform phase0/foundation
cd ../cineforge-ai-wt/a-platform
uv sync && npm install
```

- Work and run commands only inside your worktree.
- `git worktree list` shows all; `git worktree remove <path>` after merge.
- Only one Docker stack runs at a time (compose project `cineforge`, fixed ports);
  stop it in one worktree before `make up` in another. The Supabase DB is shared.

## Ownership

Each workstream edits only the paths it owns (table in `AGENTS.md`). Platform (A):
`infrastructure/`, `compose.yaml`, `Makefile`, `.github/`, `.dockerignore`,
`.cursor/rules/`, `scripts/` (except `export_contracts.py`, `generate_seed.py`),
`docs/development/`.

## Commits

Small and focused, one logical change each:

```
<area>: <imperative summary>
platform: add compose healthcheck for api
cost: add postgres budget reservations
```

Before committing: `make lint`, `make test-py` (and `make test-js` for dashboard
changes), `make check-media`.

## Contract changes

Shared contracts are frozen (`cineforge/contracts/`, `config.py`, `runtime.py`,
`db.py`, `configuration.py`, `testing.py`, `supabase/migrations/`,
`packages/configurations/`, `packages/schemas/`, root `pyproject.toml`, `uv.lock`,
root `package.json`). To change one:

1. Stop. Do not edit it in your workstream branch.
2. Write the proposal: what, why, which workstreams are affected, migration impact.
3. The integrator applies it on `phase0/foundation`, runs `make contracts`, and
   commits the regenerated `packages/schemas/`.
4. Workstreams rebase or merge `phase0/foundation` into their branch.

`make contracts-check` and CI fail if generated artifacts are stale.

## Integration

The integrator merges workstream branches into `phase0/foundation`, runs the full
suite (`make lint test test-integration`, `make up`, `make demo`, `make test-e2e`) and
opens the PR to `main`.
