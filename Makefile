SHELL := /bin/bash
COMPOSE := docker compose
FRONTEND := npm --prefix frontend

.PHONY: env cli docs ml-engagement practice-prior sim-graph ml-data ml-train ncpt-priors retention help up up-ollama down logs ps test test-backend test-frontend lint lint-backend \
	lint-frontend lint-language format contracts migrate seed pool rebuild-twin db-shell sim e2e

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-16s %s\n", $$1, $$2}'

env: ## create .env from .env.example with a fresh master key (only if .env is missing)
	@test -f .env || python3 -c "import base64, os, re; t = open('.env.example').read(); \
	k = base64.b64encode(os.urandom(32)).decode(); \
	open('.env', 'w').write(re.sub(r'(?m)^NAJMA_MASTER_KEY=$$', 'NAJMA_MASTER_KEY=' + k, t)); \
	print('Created .env with a new NAJMA_MASTER_KEY (keep it: saved API keys need it)')"

up: env ## build and start every service, wait until healthy
	$(COMPOSE) up -d --build --wait

up-ollama: env ## same as up, plus a containerised Ollama
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

migrate: ## apply database migrations (uses DATABASE_URL, default: compose Postgres)
	uv run alembic upgrade head

seed: ## add the demo user (Amira) with three weeks of practice; prints a sign-in link
	uv run python -m backend.db.seed --token

cli: ## the najma CLI against the running app, e.g. make cli ARGS="chat" (or use bin/najma)
	uv run python -m cli $(ARGS)

pool: ## fill agent.content_pool so play never waits on an LLM
	uv run python -m backend.generation.pool

rebuild-twin: ## recompute a user's profile from the event log: make rebuild-twin USER=<uuid>
	uv run python -m backend.db.rebuild $(USER)

ml-data: ## download the public datasets the models train on into data/ (about 3.1 GB)
	uv run python -m backend.ml.download

ml-train: ## train the growth forecast, write its model card and make it the active model
	uv run python -m backend.ml.train_growth --register

ml-engagement: ## train the engagement-risk model on OULAD, write its model card and make it active
	uv run python -m backend.ml.train_engagement --register

practice-prior: ## refit the average practice gain per round from Lumosity (registry/practice.yaml)
	uv run python -m backend.ml.practice

ncpt-priors: ## recompute skill correlations from NCPT into registry/priors.yaml
	uv run python -m backend.ml.ncpt

retention: ## run the daily retention job now (old traces, checkpoints, events; docs/plan/14)
	uv run python -m backend.ethics.retention

db-shell: ## open psql inside the Postgres container
	$(COMPOSE) exec postgres psql -U najma -d najma

docs: ## regenerate docs/generated/ (skill pages, ACS, data policy, model cards) from the registry and code
	uv run python -m backend.docs_gen

contracts: ## regenerate OpenAPI, registry schemas and TypeScript types
	uv run python -m backend.contracts.export
	$(FRONTEND) run contracts

N ?= 200
sim: ## simulate N users (default 200), write docs/figures, fail if a target is missed
	uv run python -m simulator --users $(N)

sim-graph: ## the wave 2 gate: simulated users through the real graph, experiments 1-5 (~30 min)
	uv run python -m simulator.graph_gate --users $(or $(GRAPH_N),120)

e2e: ## run Playwright end-to-end tests against the running stack (make up first)
	$(FRONTEND) run e2e
