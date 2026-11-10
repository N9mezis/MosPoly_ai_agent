#!/bin/sh
# Запуск API: миграции -> начальные данные -> uvicorn.
set -e
cd /repo/backend
alembic upgrade head
python -m app.cli seed
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers "$@"
