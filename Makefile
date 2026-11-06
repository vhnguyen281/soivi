.DEFAULT_GOAL := help
# Cloud mode: the pipeline, scheduler, review app, API and site use Neon and S3 from .env
# (docker-compose.cloud.yml); otherwise the local Postgres and MinIO. The default comes from
# SOIVI_CLOUD=1 in .env, so every target starts in the same mode (starting `web` also
# restarts `api`, which must not fall back to local). Override once with CLOUD=0 or CLOUD=1.
CLOUD ?= $(shell sed -n 's/^SOIVI_CLOUD=//p' .env 2>/dev/null | tail -1)
IS_CLOUD := $(filter 1,$(strip $(CLOUD)))
MODE := $(if $(IS_CLOUD),cloud (Neon + S3),local (Docker Postgres + MinIO))
COMPOSE := docker compose$(if $(IS_CLOUD), -f docker-compose.yml -f docker-compose.cloud.yml)
RUN := $(COMPOSE) run --rm pipeline

.PHONY: help up down api web web-test review scheduler scheduler-logs test test-ocr lint fmt migrate seed check-seeds pipeline shell

help: ## List targets
	@echo "Mode: $(MODE) (SOIVI_CLOUD in .env; override with CLOUD=0/1)"
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

up: ## Start postgres, minio and the pipeline container
	$(COMPOSE) up -d --build

api: ## Start the public API on http://127.0.0.1:$${API_PORT:-8002} (docs at /docs)
	@echo "Mode: $(MODE)"
	$(COMPOSE) up -d --build api
	@echo "API: http://127.0.0.1:$${API_PORT:-8002}/methodology"

web: ## Start the public site on http://127.0.0.1:$${WEB_PORT:-3000} (builds from the API on start)
	@echo "Mode: $(MODE)"
	$(COMPOSE) up -d --build web
	@echo "Site: http://127.0.0.1:$${WEB_PORT:-3000} (first start builds every page; see: docker compose logs -f web)"

web-test: ## Site checks: unit tests, types, lint
	cd web && npm test && npm run typecheck && npm run lint

review: ## Start the review app on http://127.0.0.1:$${REVIEW_PORT:-8001} (login from .env)
	@echo "Mode: $(MODE)"
	$(COMPOSE) up -d --build review
	@echo "Review app: http://127.0.0.1:$${REVIEW_PORT:-8001}"

scheduler: ## Start the scheduler
	$(COMPOSE) --profile scheduler up -d --build scheduler

scheduler-logs: ## Follow the scheduler's output
	$(COMPOSE) logs -f scheduler

down: ## Stop all containers (data volumes are kept)
	$(COMPOSE) --profile scheduler down

test: ## Run the offline test suite (skips slow OCR tests)
	uv run pytest -m "not ocr"

test-ocr: ## Run the slow OCR tests (needs Tesseract)
	uv run pytest -m ocr

lint: ## Ruff (lint + format check) and mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

fmt: ## Auto-fix lint issues and format code
	uv run ruff check --fix .
	uv run ruff format .

migrate: ## Apply database migrations (inside Docker)
	$(RUN) alembic upgrade head

seed: ## Load seed data from data/seeds/ (inside Docker; safe to re-run)
	$(RUN) python -m core.seed

pipeline: ## Run the pipeline in Docker, e.g. make pipeline ARGS="run --all-due"
	$(RUN) python -m pipeline $(ARGS)

check-seeds: ## Re-check seed URLs politely (robots.txt, 5 s per host); prints CSV
	uv run python -m pipeline.fetch.url_check --seeds

shell: ## Open a shell in the pipeline container
	$(RUN) bash
