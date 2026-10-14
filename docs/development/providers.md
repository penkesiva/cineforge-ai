# Providers, live mode and API keys

Phase 1 adds real providers for research and preproduction. The defaults stay
**offline and free**: `PROVIDER_MODE=mock`, `ALLOW_PAID_PROVIDERS=false`. Nothing below
happens until you opt in.

| Provider | Capability | Cost | Needs |
|---|---|---|---|
| Anthropic (Claude) | LLM (planning, research synthesis, script) | **paid** | API key, budget |
| Wikipedia | research sources | free | internet |
| Wikimedia Commons | media search | free | internet |
| Openverse | media search | free | internet |
| mock providers | everything | $0 (simulated) | nothing |

Routing (`ProviderRegistry`, contracts section 9) picks the **ready** provider with the
lowest priority number (real 10, mock 100). If no real provider is ready, the mock wins.

## Safety layers

A **paid** call happens only when all five are true. The first one that fails blocks it
(the Sources page shows which one as the provider status):

| # | Layer | Where | Blocked status |
|---|---|---|---|
| 1 | `PROVIDER_MODE=live` | `.env` | `blocked_mock_mode` |
| 2 | provider enabled (paid ones start disabled) | Sources page | `disabled` |
| 3 | `ALLOW_PAID_PROVIDERS=true` | `.env` | `blocked_paid_off` |
| 4 | API key present (env var or Vault) | Sources page / `.env` | `missing_key` |
| 5 | budget can reserve the estimated cost | production budget | call refused, production pauses |

Free providers need only layers 1 and 2 (enabled by default) plus internet access.
Every provider call still goes through `PaidCallGuard`: reserve budget first, commit the
actual cost after. A model with no price in the catalog cannot be called at all
(`UnknownPriceError`, fails closed).

## The Sources page

Dashboard -> **Sources** (`/api/v1/providers` behind it):

- Shows each capability, its providers, their status and which one routing would pick.
- **Enable / disable** a provider and change its priority (stored per tenant in the
  `provider_settings` table).
- **Set key / remove key**: write-only. The key is stored encrypted in Supabase Vault and
  never returned by the API; the page only shows the source (`env` or `vault`) and a hint
  like `...a1b2`.
- **Test**: a connectivity check, free where possible (the result says if the check
  itself was a paid call).

## Keys: Vault vs environment

| | Sources page -> Vault | `.env` (`ANTHROPIC_API_KEY=...`) |
|---|---|---|
| Storage | encrypted in the local Supabase Postgres (`vault.secrets`) | plain text in your `.env` (ignored by Git) |
| Shared by api + workers | yes (`SECRETS_BACKEND=vault`, forced in `compose.yaml`) | yes (compose passes it to every Python container) |
| Change without restart | yes | no: run `make up` to recreate containers |
| Priority | used when no env key | **wins** over a stored key |
| Survives `make db-reset` | **no** (re-enter the key) | yes |

Recommended: leave `ANTHROPIC_API_KEY` empty and use the Sources page. Never put a real
key in `.env.example`, docs or code: `make check-media` (and CI) fail on strings that look
like Anthropic (`sk-ant-...`) or OpenAI keys, and on non-placeholder `*_API_KEY` values in
tracked env files.

## Before enabling paid calls: verify prices

Spend is computed from `packages/configurations/pricing/anthropic-2026-10.yaml`
(USD per 1k input / output tokens):

1. Compare each entry with <https://www.anthropic.com/pricing>.
2. Check that `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`) has entries there.
3. If prices changed, do **not** edit the file: ask the integrator for a new versioned
   catalog and add it to `PRICE_CATALOG_VERSION`
   (default `mock-2026-10,open-sources-2026-10,anthropic-2026-10`).

An old `.env` copied before Phase 1 may still say `PRICE_CATALOG_VERSION=mock-2026-10`;
then Anthropic has no price and stays unusable. Update it from `.env.example`.

## Going live

```bash
# 1. .env (copy new keys from .env.example if your .env is older)
PROVIDER_MODE=live
ALLOW_PAID_PROVIDERS=false   # free sources only; set true to allow Anthropic

# 2. Recreate the containers so they see the new env (`make restart` is not enough)
make up

# 3. Dashboard -> Sources: enable providers, add the Anthropic key, press Test.
```

Going back: set `PROVIDER_MODE=mock` (or `ALLOW_PAID_PROVIDERS=false`) and `make up`.

## `make demo-live` (CAN COST MONEY)

Runs `scripts/demo_live.sh`: a preproduction-only production against the running stack.

```bash
make demo-live                       # budget cap DEMO_BUDGET_USD, default 1.00
DEMO_BUDGET_USD=0.50 make demo-live  # smaller cap
```

It:

1. Refuses unless `PROVIDER_MODE=live` and `ALLOW_PAID_PROVIDERS=true` (environment
   first, then `.env`), and unless `GET /api/v1/providers` on the running API agrees.
2. Prints the budget cap and the provider routing picks, then asks you to type `spend`.
3. Creates a production (topic "Eiffel Tower, 1889", theme `time-traveler`,
   `budget_limit_usd=DEMO_BUDGET_USD`, `auto_approve=false`) and runs it.
4. Waits until `AWAITING_APPROVAL` (research, script, storyboard; **no generation**), then
   prints the claims count, approved assets and actual spend from
   `/api/v1/productions/{id}/costs`.

Review the claims and approve or cancel in the dashboard. Overrides: `API_URL`,
`DASHBOARD_URL`, `TOPIC`, `THEME_ID`, `DEMO_TIMEOUT_SEC` (default 900), `DEMO_POLL_SEC`.
The gating logic has an offline self-test: `make test-scripts`.

## `make test-live` (CAN COST MONEY)

```bash
make test-live    # RUN_LIVE_TESTS=1 uv run pytest -q -m live
```

Tests marked `@pytest.mark.live` make real network calls and, with a key set, paid
calls. They are skipped everywhere else: the root `conftest.py` skips them unless
`RUN_LIVE_TESTS=1`, and `make test-py`, `make test-integration`, `make test-docker` and
CI pin `RUN_LIVE_TESTS=0`. "No live tests collected" is not a failure.

## Localhost only

There is **no login yet**. Anyone who can reach the API can change providers, store keys
and start paid productions.

- `compose.yaml` publishes dashboard (3000), API (8000) and Redis (6379) on
  `127.0.0.1` only. Do not change that, and do not put the stack behind a tunnel or
  reverse proxy.
- The Supabase CLI stack (Postgres 54322, API gateway 54321, Studio 54323) is started by
  `supabase start` and may listen on all interfaces. It holds the Vault keys. Only run it
  on a trusted network, or block those ports with the macOS firewall.
