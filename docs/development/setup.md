# Local setup

Target machines: Apple Silicon Macs (MacBook Pro for development, Mac mini M4 for
always-on runs). Linux works the same way.

## Prerequisites

| Tool | Version | Install (macOS) |
|---|---|---|
| Docker Desktop | 4.x with Compose v2.24+ | <https://www.docker.com/products/docker-desktop/> |
| Supabase CLI | 2.x | `brew install supabase/tap/supabase` |
| uv | 0.13+ | `brew install uv` |
| Node.js | 22 LTS (20.9+ works) | `brew install node@22` or `nvm install 22` |
| GNU make, git, curl, python3 | any recent | Xcode Command Line Tools |
| ffmpeg (optional on host) | 5+ | `brew install ffmpeg` (only for host-side media tests) |

Python 3.12 is pinned in `.python-version`; uv downloads it if needed.

## First-time setup

```bash
git clone <repo> cineforge-ai && cd cineforge-ai
make setup      # checks tools, uv sync, npm install, creates .env from .env.example
make up         # supabase start + docker compose up -d --build
make demo       # creates and runs a sample production
```

Then open:

- Dashboard: <http://localhost:3000>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>

The defaults run the full demo with **no cloud credentials and no paid API calls**
(`PROVIDER_MODE=mock`, `ALLOW_PAID_PROVIDERS=false`). A `.env` file is optional.

Real providers (Anthropic, Wikipedia, Wikimedia Commons, Openverse), the dashboard
Sources page, API keys and `make demo-live` are covered in [providers.md](providers.md).

The stack only listens on `127.0.0.1` (there is no login yet). Do not expose it on the
LAN or the internet.

## Daily commands

```bash
make up                 # start everything (rebuilds images if needed)
make logs               # follow all logs; make logs s=worker for one service
make ps                 # status
make down               # stop containers (keeps DB, Redis data and media)
make test               # Python + dashboard unit tests
make lint               # ruff + dashboard lint/typecheck
make contracts          # regenerate JSON Schema + TS types after a contract change
make help               # everything else
```

## Environment files

- `.env.example` is the template (committed, placeholders only).
- `.env` is yours (ignored by Git). Host tools (pytest, uvicorn on the host) read
  `DATABASE_URL=...127.0.0.1:54322...` and `REDIS_URL=...127.0.0.1:6379...`.
- Containers get their own values from `compose.yaml` (`host.docker.internal:54322`,
  `redis:6379`, `/data/media`), so the same `.env` works for both.
  Override container DB/Redis with `DOCKER_DATABASE_URL` / `DOCKER_REDIS_URL`.
- Provider settings (`PROVIDER_MODE`, `ALLOW_PAID_PROVIDERS`, `PRICE_CATALOG_VERSION`,
  `ANTHROPIC_*`, `HTTP_*`) flow from `.env` into the containers; missing values fall back
  to mock + paid off. After changing `.env`, run `make up` (`make restart` keeps the
  old environment).
- A `.env` created before Phase 1 lacks the new provider variables and may pin
  `PRICE_CATALOG_VERSION=mock-2026-10`. Compare it with `.env.example`.

## Running services on the host (without Docker)

```bash
make db-start
docker compose up -d redis
uv run uvicorn cineforge_api.main:app --reload --port 8000
uv run python -m cineforge_worker
uv run python -m cineforge_media_worker      # needs ffmpeg on the host
npm run dev --workspace @cineforge/dashboard # API_INTERNAL_URL=http://localhost:8000
```

On the host, media is stored under `./var/media` (ignored by Git).

## Troubleshooting

- **Port already in use** (3000, 8000, 6379): set `DASHBOARD_PORT`, `API_PORT` or
  `REDIS_PORT` in `.env`.
- **Can't reach the dashboard from another device**: intended. Ports bind to
  `127.0.0.1` until the app has login.
- **Real providers never used**: check the status on the Sources page
  (`blocked_mock_mode`, `disabled`, `blocked_paid_off`, `missing_key`); see
  [providers.md](providers.md).
- **API can't reach the DB**: run `supabase status`; the DB must listen on 54322.
- **Low disk space**: `docker builder prune -f` removes build cache only. Do not prune
  volumes unless you want to lose data.
