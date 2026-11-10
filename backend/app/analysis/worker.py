"""ARQ-воркер: проверки документов и индексация нормативки. Зона агента A.

Запуск: arq app.analysis.worker.WorkerSettings
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import setup_logging
from app.knowledge import service as knowledge
from app.llm.factory import build_embedder, build_llm_client, build_reranker

from .service import PipelineDeps, recover_stale, run_analysis

logger = logging.getLogger(__name__)
settings = get_settings()


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging(settings.log_level)
    ctx["deps"] = PipelineDeps(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        llm=build_llm_client(settings),
        embedder=build_embedder(settings),
        reranker=build_reranker(settings),
    )
    logger.info(
        "Воркер готов: LLM=%s, эмбеддинги=%s, реранкер=%s",
        settings.llm_provider,
        settings.embedding_provider,
        settings.reranker,
    )


async def shutdown(ctx: dict[str, Any]) -> None:
    await get_engine().dispose()


async def analyze(ctx: dict[str, Any], analysis_id: str) -> None:
    await run_analysis(ctx["deps"], uuid.UUID(analysis_id))


async def index_regulation_version(ctx: dict[str, Any], version_id: str, activate: bool) -> str:
    deps: PipelineDeps = ctx["deps"]
    version = await knowledge.index_version(deps.sessionmaker, uuid.UUID(version_id), deps.embedder)
    if activate and version.status.value == "ready":
        async with deps.sessionmaker() as session:
            await knowledge.activate_version(session, version.id)
            await session.commit()
        return "active"
    return version.status.value


async def watchdog(ctx: dict[str, Any]) -> None:
    """Сторож: возвращает в очередь проверки, у которых умер воркер."""
    for analysis_id in await recover_stale(ctx["deps"].sessionmaker):
        await ctx["redis"].enqueue_job(
            "analyze", str(analysis_id), _job_id=f"analysis:{analysis_id}:{uuid.uuid4().hex[:8]}"
        )


class WorkerSettings:
    functions = [analyze, index_regulation_version]
    cron_jobs = [cron(watchdog, second=0)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    max_jobs = 20
    job_timeout = 900
    keep_result = 3600
