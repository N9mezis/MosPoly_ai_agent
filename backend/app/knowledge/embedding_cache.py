"""Кеш эмбеддингов в PostgreSQL: один и тот же текст не оплачивается дважды.

Особенно важно для прогонов оценки на 40 договорах и переиндексаций.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.models import EmbeddingCache
from app.llm.embeddings import AsyncEmbedder


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class CachedEmbedder:
    def __init__(
        self, inner: AsyncEmbedder, sessionmaker: async_sessionmaker[AsyncSession]
    ) -> None:
        self._inner = inner
        self._sessionmaker = sessionmaker
        self.model_name = inner.model_name

    def query_text(self, text: str) -> str:
        return getattr(self._inner, "query_text", lambda value: value)(text)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        hashes = [_sha(text) for text in texts]
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(EmbeddingCache.text_sha256, EmbeddingCache.embedding).where(
                    EmbeddingCache.model == self.model_name,
                    EmbeddingCache.text_sha256.in_(set(hashes)),
                )
            )
            found = {sha: list(vector) for sha, vector in rows}
            missing = [i for i, sha in enumerate(hashes) if sha not in found]
            unique_missing: dict[str, int] = {}
            for i in missing:
                unique_missing.setdefault(hashes[i], i)
            if unique_missing:
                fresh = await self._inner.embed([texts[i] for i in unique_missing.values()])
                values = []
                for sha, vector in zip(unique_missing, fresh, strict=True):
                    found[sha] = vector
                    values.append(
                        {"model": self.model_name, "text_sha256": sha, "embedding": vector}
                    )
                await session.execute(
                    insert(EmbeddingCache).values(values).on_conflict_do_nothing()
                )
                await session.commit()
        return [found[sha] for sha in hashes]
