SHELL := /bin/bash
COMPOSE := docker compose
FRONTEND := npm --prefix frontend

.PHONY: help up up-ollama down logs ps test test-backend test-frontend lint lint-backend \
	lint-frontend lint-language format contracts sim e2e

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

up: ## build and start every service, wait until healthy
	$(COMPOSE) up -d --build --wait

up-ollama: ## same as up, plus a containerised Ollama
	$(COMPOSE) --profile ollama up -d --build --wait

down: ## stop every service (data volumes are kept)
	$(COMPOSE) --profile ollama down

logs: ## follow service logs
	$(COMPOSE) logs -f --tail=100

ps: ## show service status
	$(COMPOSE) ps

test: test-backend test-frontend ## run all unit tests

test-backend:
	uv run pytest

test-frontend:
	$(FRONTEND) run test

lint: lint-backend lint-frontend lint-language ## run every linter and type checker

lint-backend:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

lint-frontend:
	$(FRONTEND) run lint
	$(FRONTEND) run format:check
	$(FRONTEND) run typecheck

lint-language: ## check user-facing text for banned clinical words
	uv run python -m backend.coach.lint_language

format: ## auto-format backend and frontend
	uv run ruff format .
	uv run ruff check --fix .
	$(FRONTEND) run format

contracts: ## regenerate OpenAPI, registry schemas and TypeScript types
	uv run python -m backend.contracts.export
	$(FRONTEND) run contracts

sim: ## run the simulator (WP1.2)
	@echo "The simulator arrives in WP1.2." && exit 1

e2e: ## run end-to-end tests (WP1.3)
	@echo "End-to-end tests arrive in WP1.3." && exit 1
