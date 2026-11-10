"""ARQ-воркер: фоновые проверки и индексация нормативки. Зона агента A.

Запуск: arq app.analysis.worker.WorkerSettings
Шаг 0: только служебная задача ping; задачи analyze / index_regulation_version — дальше.
"""

from __future__ import annotations

from typing import Any

from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.logging import setup_logging

settings = get_settings()


async def ping(ctx: dict[str, Any]) -> str:
    return "pong"


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging(settings.log_level)


class WorkerSettings:
    functions = [ping]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    job_timeout = 600
