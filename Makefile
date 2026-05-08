.PHONY: help install setup up down logs build migrate superuser shell test lint fmt sync-tools clean

PROJECT := batitong
COMPOSE := docker compose
DJANGO  := $(COMPOSE) exec django-web python manage.py

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Install Python dependencies into local virtualenv (for IDE / lint)
	poetry install

setup:  ## First-run: build images, run migrations, create superuser, sync tools
	$(COMPOSE) --profile full build
	$(COMPOSE) --profile core up -d postgres redis
	@sleep 3
	$(COMPOSE) --profile full up -d
	@sleep 5
	$(DJANGO) migrate
	$(DJANGO) sync_mcp_tools || echo "MCP tools not ready yet — run 'make sync-tools' once kali-mcp is healthy"

up:  ## Start full stack (web + tools + ollama)
	$(COMPOSE) --profile full up -d

up-core:  ## Start only control plane (no tool containers)
	$(COMPOSE) --profile core up -d

down:  ## Stop all services
	$(COMPOSE) --profile full down

logs:  ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

build:  ## Rebuild all images
	$(COMPOSE) --profile full build

migrate:  ## Run Django migrations
	$(DJANGO) migrate

makemigrations:  ## Generate Django migrations
	$(DJANGO) makemigrations

superuser:  ## Create Django superuser
	$(DJANGO) createsuperuser

shell:  ## Open Django shell
	$(DJANGO) shell

bash:  ## Open bash inside django-web container
	$(COMPOSE) exec django-web bash

sync-tools:  ## Sync MCP tool registry from kali-mcp + hexstrike
	$(DJANGO) sync_mcp_tools

test:  ## Run pytest
	poetry run pytest -x -ra

lint:  ## Run ruff + black --check
	poetry run ruff check gui/
	poetry run black --check gui/

fmt:  ## Auto-format with black + ruff --fix
	poetry run ruff check --fix gui/
	poetry run black gui/

clean:  ## Remove containers, volumes, and pyc cache
	$(COMPOSE) --profile full down -v
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
