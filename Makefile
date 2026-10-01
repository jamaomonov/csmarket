# csmarket — Makefile is the single entrypoint for all common tasks.
# Prefer `make <target>` over invoking raw tools. New targets must also appear in AGENTS.md.

.DEFAULT_GOAL := help
SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

COMPOSE_DEV  := docker compose -f docker-compose.yml
COMPOSE_PROD := docker compose -f docker-compose.prod.yml

# ---------- meta ----------

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\ncsmarket — make targets\n\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(MAKEFILE_LIST)

##@ Setup

.PHONY: bootstrap
bootstrap: ## Install all deps (pnpm + uv) + pre-commit + gen api client
	corepack enable
	corepack prepare pnpm@9.12.0 --activate
	pnpm install --frozen-lockfile=false
	uv sync --all-packages --all-groups
	pnpm exec husky install || true
	pre-commit install || echo "pre-commit not on PATH; install with: uv tool install pre-commit"
	$(MAKE) gen-api || echo "gen-api skipped: api app not yet scaffolded"

##@ Development

.PHONY: dev
dev: ## Bring up the full dev stack
	$(COMPOSE_DEV) up --build

.PHONY: dev-detached
dev-detached: ## Bring up the dev stack in the background
	$(COMPOSE_DEV) up -d --build

.PHONY: dev-api
dev-api: ## Run only the API (host process; requires postgres+redis up)
	cd apps/api && uv run uvicorn csmarket.main:app --reload --host 0.0.0.0 --port 8100

.PHONY: dev-worker
dev-worker: ## Run only the worker
	cd apps/worker && uv run python -m csmarket_worker.consumer

.PHONY: dev-scheduler
dev-scheduler: ## Run only the scheduler
	cd apps/scheduler && uv run python -m csmarket_scheduler.main

.PHONY: dev-web
dev-web: ## Run only the public web (host process, :3100)
	pnpm --filter @csmarket/web exec next dev --turbo -p 3100

.PHONY: dev-admin
dev-admin: ## Run only the admin SPA (host process, :3102)
	pnpm --filter @csmarket/admin exec vite --port 3102

.PHONY: down
down: ## Bring the dev stack down
	$(COMPOSE_DEV) down

.PHONY: logs
logs: ## Tail a service's logs: make logs service=api
	@if [ -z "$(service)" ]; then echo "Usage: make logs service=api"; exit 1; fi
	$(COMPOSE_DEV) logs -f $(service)

##@ Database

.PHONY: migrate
migrate: ## Apply all alembic migrations inside the api container
	$(COMPOSE_DEV) exec api alembic upgrade head

.PHONY: migration
migration: ## Create a new alembic migration: make migration name=add_orders
	@if [ -z "$(name)" ]; then echo "Usage: make migration name=add_x"; exit 1; fi
	$(COMPOSE_DEV) exec api alembic revision --autogenerate -m "$(name)"

.PHONY: psql
psql: ## Open a psql shell inside the postgres container
	$(COMPOSE_DEV) exec postgres psql -U csmarket_app -d csmarket

##@ Quality

.PHONY: lint
lint: lint-py lint-ts ## Lint everything

.PHONY: lint-py
lint-py: ## Ruff check + format check + check-no-yupay
	uv run ruff check apps
	uv run ruff format --check apps
	bash scripts/check-no-yupay.sh

.PHONY: check-no-yupay
check-no-yupay: ## Fail on YuPay-specific tokens in source
	bash scripts/check-no-yupay.sh

.PHONY: lint-ts
lint-ts: ## ESLint + Prettier check
	pnpm exec turbo run lint
	pnpm exec prettier --check .

.PHONY: lint-fix
lint-fix: ## Autofix everything
	uv run ruff check --fix apps
	uv run ruff format apps
	pnpm exec turbo run lint:fix
	pnpm exec prettier --write .

.PHONY: typecheck
typecheck: ## mypy + tsc
	uv run mypy apps
	pnpm exec turbo run typecheck

##@ Testing

.PHONY: test
test: test-py test-ts ## All tests (Python + TS)

.PHONY: test-py
test-py: ## Python unit + integration tests
	COVERAGE_CORE=sysmon uv run pytest -n auto

.PHONY: test-ts
test-ts: ## TS tests across all packages and apps
	pnpm exec turbo run test

.PHONY: test-e2e
test-e2e: ## Playwright e2e tests (requires running stack)
	pnpm --filter @csmarket/e2e exec playwright test

##@ Build / release

.PHONY: build
build: ## Build all Docker images locally
	$(COMPOSE_DEV) build

.PHONY: gen-api
gen-api: ## Regenerate docs/api/openapi.json + packages/api-client
	@if [ -d apps/api/src/csmarket ]; then \
		cd apps/api && uv run python -m csmarket.scripts.export_openapi ../../docs/api/openapi.json && cd ../..; \
		pnpm --filter @csmarket/api-client gen:api; \
	else \
		echo "apps/api not scaffolded yet"; \
	fi

.PHONY: deploy
deploy: ## Deploy via GitHub Actions: make deploy tag=sha-xxxxxxx
	@if [ -z "$(tag)" ]; then echo "Usage: make deploy tag=sha-xxxxxxx  (or vX.Y.Z, or main)"; exit 1; fi
	gh workflow run deploy.yml -f environment=production -f image_tag='$(tag)'

##@ Ops

.PHONY: backup
backup: ## One-off pg_backup.sh run (the backup service itself runs nightly)
	$(COMPOSE_PROD) run --rm backup /bin/bash /scripts/pg_backup.sh

.PHONY: restore
restore: ## Restore DB from backup: make restore file=path
	@if [ -z "$(file)" ]; then echo "Usage: make restore file=/path/to/backup.dump"; exit 1; fi
	$(COMPOSE_PROD) run --rm -v $(file):/restore.dump backup /bin/bash /scripts/restore.sh /restore.dump
