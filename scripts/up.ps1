# Собрать и запустить всё: http://localhost:8080
Set-Location (Join-Path $PSScriptRoot "..")
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Создан .env из .env.example" }
docker compose up -d --build
docker compose ps
