"""FastAPI-приложение. Документация API: /docs (Swagger), /openapi.json."""

from __future__ import annotations

from fastapi import APIRouter, FastAPI
from redis.asyncio import Redis
from sqlalchemy import text

from app.api.v1 import analyses, auth, document_types, documents, regulations, reports
from app.api.v1.schemas import HealthOut, ReadyOut
from app.core.config import get_settings
from app.core.db import get_engine
from app.core.errors import install_error_handlers
from app.core.logging import setup_logging

settings = get_settings()
setup_logging(settings.log_level)

app = FastAPI(
    title="Проверка трудовых договоров по ТК РФ",
    version="0.1.0",
    description=(
        "API ИИ-агента проверки трудовых договоров. Ошибки возвращаются в едином формате "
        '`{"error": {"code", "message", "details"}}`. Ответы с заголовком `X-Stub: true` — '
        "заглушки на фикстурах."
    ),
)
install_error_handlers(app)

api_v1 = APIRouter(prefix="/api/v1")
for router in (
    auth.auth_router,
    auth.users_router,
    auth.orgs_router,
    document_types.router,
    documents.router,
    analyses.router,
    reports.router,
    regulations.router,
):
    api_v1.include_router(router)
app.include_router(api_v1)


@app.get("/healthz", response_model=HealthOut, tags=["Служебное"], summary="Процесс жив")
async def healthz() -> HealthOut:
    return HealthOut()


@app.get("/readyz", response_model=ReadyOut, tags=["Служебное"], summary="Готовность зависимостей")
async def readyz() -> ReadyOut:
    db_ok = redis_ok = False
    try:
        async with get_engine().connect() as connection:
            await connection.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass
    try:
        client = Redis.from_url(settings.redis_url)
        redis_ok = bool(await client.ping())
        await client.aclose()
    except Exception:
        pass
    return ReadyOut(
        status="ok" if db_ok and redis_ok else "degraded",
        database=db_ok,
        redis=redis_ok,
        llm_provider=settings.llm_provider,
        embedding_provider=settings.embedding_provider,
        reranker=settings.reranker,
    )
