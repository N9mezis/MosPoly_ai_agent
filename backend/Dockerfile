# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Системные библиотеки для WeasyPrint (PDF-отчёты) и шрифты с кириллицей.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b libffi8 \
        fonts-dejavu-core fonts-liberation \
    && apt-get clean

WORKDIR /repo/backend

# Сначала только зависимости — слой кешируется между сборками.
COPY backend/pyproject.toml ./
COPY backend/app/__init__.py ./app/__init__.py
RUN pip install -e ".[dev]"

COPY backend/ ./
COPY certs/ /repo/certs/
COPY data/ /repo/data/
COPY evals/ /repo/evals/

# Скрипты могли прийти с CRLF из Windows-клона.
RUN pip install --no-deps -e . && sed -i 's/\r$//' docker/*.sh

EXPOSE 8000
