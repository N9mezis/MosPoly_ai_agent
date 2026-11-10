# Режим разработки с hot-reload
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
