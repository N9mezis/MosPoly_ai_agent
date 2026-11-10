#!/bin/sh
# Запуск API: миграции -> начальные данные -> uvicorn.
set -e
cd /repo/backend
alembic upgrade head
python -m app.cli seed
# При первом запуске загружаем нормативку из data/regulations (эмбеддинги — по EMBEDDING_PROVIDER).
python -m app.cli import-kb --if-empty || echo "Нормативка не загружена, см. логи выше"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers "$@"
