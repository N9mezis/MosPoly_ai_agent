Set-Location (Join-Path $PSScriptRoot "..")
docker compose run --rm --no-deps api sh -c "cd /repo/backend && ruff check app tests && ruff format --check app tests"
