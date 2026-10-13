# CineForge AI developer shortcuts. Run `make help`. Docs: docs/development/
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
APP_SERVICES := api worker media-worker dashboard
DASHBOARD_WS := @cineforge/dashboard
MEDIA_VOLUME := cineforge-media

API_URL ?= http://localhost:8000
DASHBOARD_URL ?= http://localhost:3000

s ?=

# Runs a dashboard npm script, or skips politely if apps/dashboard is not there yet.
define dashboard_npm
	@if [ -f apps/dashboard/package.json ]; then \
		npm run $(1) --workspace $(DASHBOARD_WS); \
	else \
		echo "SKIP dashboard $(1): apps/dashboard/package.json not found"; \
	fi
endef

.PHONY: help setup db-start db-stop db-reset up down down-all restart rebuild build logs ps \
	shell test test-py test-integration test-js test-e2e test-docker lint fmt contracts \
	contracts-check demo check-media check-media-selftest clean-media

help: ## Show this help
	@echo "CineForge AI - make targets"
	@echo
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "Examples: make logs s=api | make shell s=worker | make clean-media CONFIRM=1"

# --- Setup ---------------------------------------------------------------------

setup: ## Check prerequisites, install Python + JS deps, create .env if missing
	@missing=0; \
	for tool in docker supabase uv node npm; do \
		if command -v $$tool >/dev/null 2>&1; then \
			printf "  %-9s %s\n" "$$tool" "$$($$tool --version 2>/dev/null | head -1)"; \
		else \
			echo "  $$tool     MISSING"; missing=1; \
		fi; \
	done; \
	if ! docker compose version >/dev/null 2>&1; then echo "  docker compose v2 MISSING"; missing=1; fi; \
	if [ $$missing -ne 0 ]; then echo "Install the missing tools (docs/development/setup.md)."; exit 1; fi
	uv sync
	npm install
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; else echo ".env already exists (left unchanged)"; fi

# --- Database (Supabase CLI, runs outside compose) ------------------------------

db-start: ## Start the local Supabase Postgres (port 54322)
	@if supabase status >/dev/null 2>&1; then echo "Supabase already running"; else supabase start; fi

db-stop: ## Stop the local Supabase stack (data is kept)
	supabase stop

db-reset: ## DESTRUCTIVE: wipe local DB, re-apply migrations + seed
	@echo "WARNING: 'supabase db reset' deletes ALL local database data (productions, ledger, assets)."
	@echo "Media files in the $(MEDIA_VOLUME) volume are NOT deleted."
	@read -r -p "Type 'reset' to continue: " answer; [ "$$answer" = "reset" ] || { echo "Aborted."; exit 1; }
	supabase db reset

# --- Docker stack ----------------------------------------------------------------

up: db-start ## Start DB + build and start all services
	$(COMPOSE) up -d --build --renew-anon-volumes
	@echo
	@echo "CineForge is starting:"
	@echo "  Dashboard  $(DASHBOARD_URL)"
	@echo "  API docs   $(API_URL)/docs"
	@echo "  Health     $(API_URL)/health"
	@echo "Logs: make logs   (one service: make logs s=api)"

down: ## Stop services (keeps the media volume, Redis data and the DB)
	$(COMPOSE) rm --force --stop --volumes dashboard
	$(COMPOSE) down

down-all: down ## Stop services and the Supabase stack (data is kept)
	supabase stop

restart: ## Restart services (no rebuild)
	$(COMPOSE) restart $(s)

build: ## Build app images (uses cache)
	$(COMPOSE) build $(APP_SERVICES)

rebuild: ## Rebuild app images from scratch (no cache)
	$(COMPOSE) build --no-cache $(APP_SERVICES)

logs: ## Follow logs (all services, or s=<service>)
	$(COMPOSE) logs -f --tail=200 $(s)

ps: ## Show service status
	$(COMPOSE) ps

shell: ## Open a shell in a running service (s=api by default)
	$(COMPOSE) exec $(or $(s),api) bash

# --- Tests and quality -------------------------------------------------------------

test: test-py test-js ## Run Python + dashboard unit tests

test-py: ## Python tests (integration tests skip without DB)
	uv run pytest -q

test-integration: ## Python integration tests (needs `make db-start` + redis)
	uv run pytest -q -m integration

test-js: ## Dashboard tests
	$(call dashboard_npm,test)

test-e2e: ## End-to-end tests against the running stack (`make up` first)
	uv run pytest -q -m e2e tests/e2e

test-docker: ## Run Python tests inside the media-worker image (has ffmpeg)
	$(COMPOSE) run --rm --no-deps media-worker pytest -q

lint: ## Ruff lint + format check, dashboard lint + typecheck
	uv run ruff check .
	uv run ruff format --check .
	$(call dashboard_npm,lint)
	$(call dashboard_npm,typecheck)

fmt: ## Auto-format Python (ruff) and fix lint where safe
	uv run ruff check --fix .
	uv run ruff format .

contracts: ## Regenerate JSON Schema + TS types from Pydantic contracts
	uv run python scripts/export_contracts.py
	npm run contracts:types

contracts-check: ## Fail if generated contract artifacts are stale
	uv run python scripts/export_contracts.py --check
	npm run contracts:types
	git diff --exit-code packages/schemas

# --- Demo and hygiene ------------------------------------------------------------

demo: ## Create + run a sample production (stack must be up)
	API_URL=$(API_URL) DASHBOARD_URL=$(DASHBOARD_URL) bash scripts/demo.sh

check-media: ## Fail if Git tracks media, files > 5 MB, or secrets
	bash scripts/check_no_media.sh

check-media-selftest: ## Self-test for check-media
	bash scripts/tests/test_check_no_media.sh

clean-media: ## DESTRUCTIVE: delete the media volume (needs CONFIRM=1)
	@if [ "$(CONFIRM)" != "1" ]; then \
		echo "WARNING: this deletes ALL generated media in the '$(MEDIA_VOLUME)' Docker volume."; \
		echo "Database rows will still reference the deleted files."; \
		echo "Re-run with: make clean-media CONFIRM=1"; \
		exit 1; \
	fi
	$(COMPOSE) down
	docker volume rm $(MEDIA_VOLUME)
	@echo "Deleted volume $(MEDIA_VOLUME)."
