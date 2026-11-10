"""Постановка задач в очередь ARQ (Redis)."""

from __future__ import annotations

import uuid

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.core.config import get_settings

_pool: ArqRedis | None = None


async def get_queue() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    return _pool


async def close_queue() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
        _pool = None


async def enqueue_analysis(analysis_id: uuid.UUID) -> None:
    queue = await get_queue()
    await queue.enqueue_job("analyze", str(analysis_id), _job_id=f"analysis:{analysis_id}")


async def enqueue_indexing(version_id: uuid.UUID, *, activate: bool = False) -> None:
    queue = await get_queue()
    await queue.enqueue_job(
        "index_regulation_version", str(version_id), activate, _job_id=f"index:{version_id}"
    )
