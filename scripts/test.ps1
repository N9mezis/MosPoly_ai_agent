# Тесты бэкенда в контейнере
Set-Location (Join-Path $PSScriptRoot "..")
docker compose run --rm --no-deps api sh -c "cd /repo/backend && pytest -q"
