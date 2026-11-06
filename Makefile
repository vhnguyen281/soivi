.DEFAULT_GOAL := help
# CLOUD=1: the pipeline, scheduler, review app and API use Neon and S3 from .env
# (docker-compose.cloud.yml). Without it they use the local Postgres and MinIO.
COMPOSE := docker compose$(if $(CLOUD), -f docker-compose.yml -f docker-compose.cloud.yml)
RUN := $(COMPOSE) run --rm pipeline

.PHONY: help up down api web web-test review scheduler scheduler-logs test test-ocr lint fmt migrate seed check-seeds pipeline shell

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-10s %s\n", $$1, $$2}'

up: ## Start postgres, minio and the pipeline container
	$(COMPOSE) up -d --build

api: ## Start the public API on http://127.0.0.1:$${API_PORT:-8002} (/v1/..., docs at /docs)
	$(COMPOSE) up -d --build api
	@echo "API: http://127.0.0.1:$${API_PORT:-8002}/v1/methodology"

web: ## Start the public site on http://127.0.0.1:$${WEB_PORT:-3000} (builds from the API on start)
	$(COMPOSE) up -d --build web
	@echo "Site: http://127.0.0.1:$${WEB_PORT:-3000} (first start builds every page; see: docker compose logs -f web)"

web-test: ## Site checks: unit tests, types, lint
	cd web && npm test && npm run typecheck && npm run lint

review: ## (CLOUD=1 for Neon and S3) Start the review app on http://127.0.0.1:$${REVIEW_PORT:-8001} (login from .env)
	$(COMPOSE) up -d --build review
	@echo "Review app: http://127.0.0.1:$${REVIEW_PORT:-8001}"

scheduler: ## Start the scheduler (CLOUD=1 to write to Neon and S3)
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

migrate: ## Apply database migrations (inside Docker; CLOUD=1 for Neon)
	$(RUN) alembic upgrade head

seed: ## Load seed data from data/seeds/ (inside Docker; safe to re-run; CLOUD=1 for Neon)
	$(RUN) python -m core.seed

pipeline: ## Run the pipeline in Docker, e.g. make pipeline ARGS="run --all-due"
	$(RUN) python -m pipeline $(ARGS)

check-seeds: ## Re-check seed URLs politely (robots.txt, 5 s per host); prints CSV
	uv run python -m pipeline.fetch.url_check --seeds

shell: ## Open a shell in the pipeline container
	$(RUN) bash
