# Docker stack

`compose.yaml` (project name `cineforge`) runs the app. Postgres is **not** in
compose: it is the Supabase CLI local stack (`make db-start`, host port 54322).
Containers reach it through `host.docker.internal:54322`
(`extra_hosts: host.docker.internal:host-gateway`, so it also works on Linux).

## Services

| Service | Image (target) | Port | Command |
|---|---|---|---|
| `redis` | `redis:7-alpine` | 127.0.0.1:6379 | `redis-server --appendonly yes` |
| `api` | `cineforge/python-app:dev` (`app`) | 127.0.0.1:8000 | `uvicorn cineforge_api.main:app --reload` |
| `worker` | `cineforge/python-app:dev` (`app`) | - | `watchfiles ... "python -m cineforge_worker"` |
| `media-worker` | `cineforge/python-media:dev` (`media`) | - | `watchfiles ... "python -m cineforge_media_worker"` |
| `dashboard` | `cineforge/dashboard:dev` (`dev`) | 127.0.0.1:3000 | `npm run dev --workspace @cineforge/dashboard` |

Health checks: `redis-cli ping`; API `GET /health/live` (Python urllib, no curl in the
image); dashboard `GET /` via Node `fetch`. API, worker and media-worker wait for
Redis to be healthy. Ports can be changed with `API_PORT`, `DASHBOARD_PORT`, `REDIS_PORT`.

All published ports bind to **`127.0.0.1` only**. There is no login yet: anyone who can
reach the API can store keys and start paid productions. Keep it that way until auth
exists.

## Provider environment

The Python services read provider settings from `.env` (or your shell) with safe
defaults, so `make up` without a `.env` stays offline and free:

| Variable | Default in compose |
|---|---|
| `PROVIDER_MODE` | `mock` |
| `ALLOW_PAID_PROVIDERS` | `false` |
| `PRICE_CATALOG_VERSION` | `mock-2026-10,open-sources-2026-10,anthropic-2026-10` |
| `SECRETS_BACKEND` | `vault` (fixed: keys from the Sources page, shared by all services) |
| `ANTHROPIC_API_KEY` | empty (use the Sources page) |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` |
| `HTTP_USER_AGENT` | `CineForgeAI/0.2 (...)` (Wikimedia requires one) |

`ANTHROPIC_BASE_URL` and `HTTP_TIMEOUT_SEC` pass through from `.env` when set. Containers
pick up `.env` changes only when recreated: run `make up`, not `make restart`.
Live providers need outbound internet from the containers. See [providers.md](providers.md).

## Images

`infrastructure/docker/python.Dockerfile` (build context = repo root):

- `base`: `python:3.12-slim-bookworm` + uv (copied from `ghcr.io/astral-sh/uv:0.13`),
  non-root user `cineforge` (uid 1000), `/app` and `/data/media` owned by it.
- `deps`: copies only `pyproject.toml`, `uv.lock`, `.python-version` and member
  `pyproject.toml` files, then `uv sync --frozen --all-packages --no-install-workspace`
  with a BuildKit cache mount. Rebuilds only when dependencies change.
- `app`: copies `packages/`, `services/`, `scripts/` and installs the workspace members
  editable. The venv is at `/opt/venv` (outside `/app`), so bind mounts never hide it.
- `media`: `app` + `ffmpeg`, `ffprobe`, `fonts-dejavu-core` (for `drawtext`).

Runtime dependencies (including `httpx`, which the engine now uses for real providers)
come from `uv.lock` via `uv sync --frozen`, so nothing extra is installed by hand.
The **dev dependency group** (pytest, fakeredis, ruff, ...) is included by default
(`INSTALL_DEV=true`), so tests run inside the image:

```bash
make test-docker                                         # pytest -q in the media-worker image
docker compose run --rm --no-deps api pytest -q packages/engine/tests
```

For a slimmer prod-like image: `docker build --build-arg INSTALL_DEV=false ...`.

`infrastructure/docker/dashboard.Dockerfile`: `node:22-alpine`; `deps` runs `npm ci`
from the lockfile; `dev` (compose default) runs `next dev`; `runner` runs
`npm run build` at build time and `npm run start` (pass `--build-arg API_INTERNAL_URL`
if the API is not `http://api:8000`, because Next rewrites are resolved at build time).

## Hot reload

- Python sources are bind-mounted: `./packages`, `./services`, `./scripts` (not the repo
  root). `uvicorn --reload` and `watchfiles` restart on `.py` changes.
  If changes are not picked up, add `WATCHFILES_FORCE_POLLING=true` to `.env`.
- Dashboard: `./apps/dashboard` and `./packages/schemas` are bind-mounted.
  `node_modules` and `.next` stay in anonymous volumes so macOS host files never
  replace the Linux builds. `WATCHPACK_POLLING=true` makes reload reliable on macOS.
- Changed dependencies (`uv.lock`, `package-lock.json`)? Run `make up` (rebuilds and
  renews the dashboard's anonymous volumes).

## Persistent media

Generated media lives in the named volume **`cineforge-media`**, mounted at
`/data/media` in `api`, `worker` and `media-worker` (`STORAGE_LOCAL_ROOT=/data/media`).

| Action | Media kept? |
|---|---|
| `make down` / `docker compose down` | yes |
| `make restart`, `make up`, `make rebuild` | yes |
| Docker Desktop restart, Mac reboot | yes |
| `docker compose down -v` | **no** |
| `make clean-media CONFIRM=1` | **no** |

Inspect it: `docker compose run --rm --no-deps api ls -R /data/media`.
Back it up: `docker run --rm -v cineforge-media:/m -v "$PWD":/out alpine tar czf /out/media.tgz -C /m .`
(keep the archive out of the repo).

Redis data (`redis-data` volume, AOF enabled) also survives `down`.

## Resetting

```bash
make down                    # stop containers, keep everything
make clean-media CONFIRM=1   # delete generated media only
make db-reset                # DESTRUCTIVE: wipe DB, re-apply migrations + seed
make rebuild                 # rebuild images without cache
```

## Apple Silicon / Mac mini M4

- All bases are multi-arch (`python:3.12-slim-bookworm`, `node:22-alpine`,
  `redis:7-alpine`, `ghcr.io/astral-sh/uv`), so images build natively as `arm64`.
  No `platform:` pin and no emulation. CI builds the same files on `amd64`.
- The media image is about 1 GB (Debian's `ffmpeg` pulls many codec libraries);
  the app image is about 450 MB. Layers are shared between them.
- Docker Desktop: give it at least 4 CPUs / 6 GB RAM for rendering. Use the VirtioFS
  file sharing implementation (default) for fast bind mounts.
- Mac mini always-on: enable "Start Docker Desktop when you sign in"; services use
  `restart: unless-stopped`. Run `supabase start` after login (or a launchd job).
- Low disk: `docker builder prune -f` is safe. Never `docker volume prune`.
