from __future__ import annotations

import asyncio
import os

import pytest

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("LLM_PROVIDER", "mock")
os.environ.setdefault("EMBEDDING_PROVIDER", "hashing")


def _db_available() -> bool:
    try:
        import asyncpg

        from app.core.config import get_settings

        dsn = get_settings().database_url.replace("postgresql+asyncpg://", "postgresql://")

        async def probe() -> None:
            connection = await asyncpg.connect(dsn, timeout=2)
            await connection.close()

        asyncio.run(probe())
        return True
    except Exception:
        return False


_DB = None


def pytest_collection_modifyitems(config, items):
    global _DB
    if not any("db" in item.keywords for item in items):
        return
    if _DB is None:
        _DB = _db_available()
    if not _DB:
        skip = pytest.mark.skip(
            reason="PostgreSQL недоступен (DATABASE_URL); запустите docker compose up db"
        )
        for item in items:
            if "db" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(scope="session")
def client(tmp_path_factory):
    """TestClient поверх настоящей БД (миграции + seed должны быть применены)."""
    os.environ["UPLOAD_TMP_DIR"] = str(tmp_path_factory.mktemp("uploads"))
    from app.core.config import get_settings

    get_settings.cache_clear()
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
