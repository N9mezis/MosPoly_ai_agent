Set-Location (Join-Path $PSScriptRoot "..")
docker compose logs -f api worker
