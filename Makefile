# Короткие команды (Linux/macOS/WSL). На Windows — scripts/*.ps1.
DC = docker compose
DEV = docker compose -f docker-compose.yml -f docker-compose.dev.yml

.PHONY: env up dev down logs ps test lint fmt migrate seed shell psql

env:            ## создать .env из шаблона
	test -f .env || cp .env.example .env

up: env         ## собрать и запустить всё: http://localhost:8080
	$(DC) up -d --build

dev: env        ## режим разработки (hot-reload)
	$(DEV) up --build

down:           ## остановить (данные БД сохраняются)
	$(DC) down

logs:           ## логи api и worker
	$(DC) logs -f api worker

ps:
	$(DC) ps

test:           ## тесты бэкенда в контейнере
	$(DC) run --rm --no-deps api sh -c "cd /repo/backend && pytest -q"

lint:
	$(DC) run --rm --no-deps api sh -c "cd /repo/backend && ruff check app tests && ruff format --check app tests"

fmt:
	$(DC) run --rm --no-deps api sh -c "cd /repo/backend && ruff format app tests && ruff check --fix app tests"

migrate:        ## применить миграции
	$(DC) run --rm api alembic upgrade head

seed:
	$(DC) run --rm api python -m app.cli seed

shell:
	$(DC) run --rm api bash

psql:
	$(DC) exec db psql -U tk -d tk
