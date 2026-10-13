# Testing

## Layers

| Layer | Where | Needs | Command |
|---|---|---|---|
| Unit (Python) | `packages/engine/tests/<area>/`, `services/<svc>/tests/` | nothing (memory/inline backends) | `make test-py` |
| Integration (Python) | same folders, `@pytest.mark.integration` | Postgres + Redis | `make test-integration` |
| FFmpeg | same folders, `@pytest.mark.ffmpeg` | `ffmpeg`/`ffprobe` | `uv run pytest -m ffmpeg` (host ffmpeg) or `make test-docker` |
| Dashboard | `apps/dashboard` (Vitest) | Node | `make test-js` |
| End-to-end | `tests/e2e/` (integrator), `@pytest.mark.e2e` | running stack (`make up`) | `make test-e2e` |
| Repo hygiene | `scripts/check_no_media.sh` | git | `make check-media`, `make check-media-selftest` |

Markers are declared in the root `pyproject.toml` (`--strict-markers`, so unknown
markers fail). Integration tests skip themselves when `DATABASE_URL` / `REDIS_URL`
are unreachable, so `make test-py` always works offline.

## Commands

```bash
make test               # test-py + test-js
make test-py            # uv run pytest -q
make test-integration   # uv run pytest -q -m integration (make db-start; docker compose up -d redis)
make test-e2e           # uv run pytest -q -m e2e tests/e2e (make up first)
make test-docker        # pytest -q inside the media-worker image (includes ffmpeg tests)
docker compose run --rm media-worker pytest -q -m integration   # integration, in Docker
make lint               # ruff check + ruff format --check + dashboard lint/typecheck
make contracts-check    # generated schemas/types are up to date
```

Host integration tests use `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:54322/postgres`
and `REDIS_URL=redis://127.0.0.1:6379/0` (the `.env.example` defaults).

## Writing tests

- Every change ships with tests; your workstream's test command must pass.
- Unit tests use `PERSISTENCE_BACKEND=memory` and `QUEUE_BACKEND=inline`; no network.
- Never call paid providers in tests. Mock providers only.
- No media fixtures in Git except tiny files under `tests/fixtures/approved/`.
  Generate test media at runtime (e.g. `ffmpeg -f lavfi -i color=...`) into a tmp dir.

## CI (`.github/workflows/ci.yml`)

Runs on every push and pull request:

- **python**: `uv sync --frozen`, ruff check + format check, contract schema check,
  installs ffmpeg, applies `supabase/migrations/*.sql` + `supabase/seed.sql` to a
  `postgres:17` service, then `pytest -q` and `pytest -q -m integration` (with `redis:7`).
- **dashboard**: `npm ci`, regenerate TS contract types and `git diff --exit-code
  packages/schemas`, then lint, typecheck, test and build `@cineforge/dashboard`.
- **hygiene**: `scripts/check_no_media.sh` and its self-test.
- **docker** (after python + dashboard): `docker compose config`, builds api, worker,
  media-worker and dashboard images, smoke-tests imports, ffmpeg and engine tests.

E2E tests are not run in CI yet (they need the full stack).
