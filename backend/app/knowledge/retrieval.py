"""Гибридный поиск норм по пункту договора.

Три независимых канала по активным версиям источников профиля:

1. dense   — косинусная близость эмбеддингов (pgvector), top-20;
2. lexical — полнотекстовый поиск PostgreSQL ('russian'), OR-запрос по словам пункта, top-20.
   websearch_to_tsquery соединял бы слова через AND и почти ничего не находил;
3. hints   — явные ссылки «ст. 91» и словарь «тема → статьи» из профиля проверки.

Слияние — Reciprocal Rank Fusion (k=60) → кандидаты top-N → реранкер → top-k.
Каждая выдача несёт `trace` с рангами и скорами каналов: он сохраняется в `retrievals`,
чтобы отличать ошибку поиска от ошибки модели.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import Text, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.models import (
    ProfileSource,
    RegulationChunk,
    RegulationSource,
    RegulationVersion,
    RegulationVersionStatus,
)
from app.domain.models import RegulationChunk as DomainChunk
from app.domain.models import RetrievedRegulation
from app.llm.embeddings import AsyncEmbedder

from .bm25 import BM25Index, parse_tsvector
from .rerank import NoReranker, Reranker

RRF_K = 60
CHANNEL_LIMIT = 20
ALL_CHANNELS = frozenset({"dense", "lexical", "hints"})

ARTICLE_REF = re.compile(r"(?:ст\.|стать[яиеюйё]\w*)\s*(\d{1,3}(?:\.\d{1,2})?)", re.IGNORECASE)
WORD = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)
PLACEHOLDER = re.compile(r"\[[A-Z_0-9]+\]")


class KnowledgeBaseEmpty(AppError):
    status_code = 409
    code = "knowledge_base_empty"


@dataclass(slots=True)
class RetrievalSettings:
    candidates: int = 12
    top_k: int = 4
    similarity_floor: float = 0.0
    channels: frozenset[str] = ALL_CHANNELS
    article_hints: dict[str, list[str]] = field(default_factory=dict)
    # Не больше N частей одной статьи в выдаче: цель — подать модели разные нормы.
    max_per_article: int = 2
    # Веса каналов в RRF. Подсказки по статьям точны, но покрывают не всё.
    channel_weights: dict[str, float] = field(
        default_factory=lambda: {"dense": 1.0, "lexical": 1.0, "hints": 2.0}
    )


def build_tsquery(text: str, limit: int = 48) -> str:
    """OR-запрос из слов пункта (стемминг и стоп-слова делает to_tsquery('russian'))."""
    cleaned = PLACEHOLDER.sub(" ", text.lower())
    words: list[str] = []
    for word in WORD.findall(cleaned):
        if word.isdigit() or word in words:
            continue
        words.append(word)
        if len(words) >= limit:
            break
    return " | ".join(words)


def hinted_articles(text: str, hints: dict[str, list[str]]) -> list[str]:
    lowered = text.lower()
    articles: list[str] = [match.group(1) for match in ARTICLE_REF.finditer(text)]
    for keyword, mapped in hints.items():
        if keyword.lower() in lowered:
            articles.extend(mapped)
    return list(dict.fromkeys(articles))


def rrf_fuse(
    rankings: dict[str, list[str]],
    k: int = RRF_K,
    weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for name, ranked in rankings.items():
        weight = (weights or {}).get(name, 1.0)
        for rank, item_id in enumerate(ranked, start=1):
            scores[item_id] = scores.get(item_id, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda pair: pair[1], reverse=True)


async def load_scope(
    session: AsyncSession,
    *,
    profile_id: uuid.UUID | None,
    on_date: date | None = None,
) -> list[DomainChunk]:
    """Все фрагменты активных версий источников профиля (на дату проверки)."""
    query = (
        select(RegulationChunk, RegulationVersion, RegulationSource)
        .join(RegulationVersion, RegulationVersion.id == RegulationChunk.version_id)
        .join(RegulationSource, RegulationSource.id == RegulationVersion.source_id)
        .where(RegulationVersion.status == RegulationVersionStatus.ACTIVE)
    )
    if profile_id is not None:
        query = query.join(
            ProfileSource,
            and_(
                ProfileSource.source_id == RegulationVersion.source_id,
                ProfileSource.profile_id == profile_id,
            ),
        )
    if on_date is not None:
        query = query.where(
            or_(
                RegulationVersion.effective_from.is_(None),
                RegulationVersion.effective_from <= on_date,
            ),
            or_(
                RegulationVersion.effective_to.is_(None), RegulationVersion.effective_to >= on_date
            ),
        )
    rows = await session.execute(query.order_by(RegulationChunk.chunk_key))
    return [
        DomainChunk(
            chunk_id=chunk.chunk_key,
            db_id=str(chunk.id),
            source_id=source.id,
            source_title=source.title,
            article=chunk.article,
            part=chunk.part,
            title=chunk.title,
            text=chunk.text,
            source_url=source.source_url,
            edition_date=version.edition_date.isoformat() if version.edition_date else None,
            effective_from=version.effective_from.isoformat() if version.effective_from else None,
            effective_to=version.effective_to.isoformat() if version.effective_to else None,
        )
        for chunk, version, source in rows
    ]


class HybridRetriever:
    """Поиск по снимку активной нормативки. Снимок фиксируется при `load()` (НФТ-7)."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        embedder: AsyncEmbedder,
        *,
        settings: RetrievalSettings | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._embedder = embedder
        self.settings = settings or RetrievalSettings()
        self._reranker = reranker or NoReranker()
        self._chunks: dict[str, DomainChunk] = {}
        self._bm25: BM25Index | None = None
        self._by_article: dict[str, list[DomainChunk]] = {}

    @property
    def size(self) -> int:
        return len(self._chunks)

    @property
    def chunks(self) -> list[DomainChunk]:
        return list(self._chunks.values())

    async def load(self, *, profile_id: uuid.UUID | None, on_date: date | None = None) -> None:
        async with self._sessionmaker() as session:
            scope = await load_scope(session, profile_id=profile_id, on_date=on_date)
        if not scope:
            raise KnowledgeBaseEmpty(
                "База норм не настроена: нет активных версий нормативных источников"
            )
        self._chunks = {chunk.db_id: chunk for chunk in scope if chunk.db_id}
        self._by_article = {}
        for chunk in scope:
            if chunk.article:
                self._by_article.setdefault(chunk.article, []).append(chunk)
        # Леммы фрагментов для BM25 (тот же стеммер PostgreSQL, что и у полнотекстового индекса).
        async with self._sessionmaker() as session:
            rows = await session.execute(
                select(RegulationChunk.id, cast(RegulationChunk.fts, Text)).where(
                    RegulationChunk.id.in_([uuid.UUID(i) for i in self._chunks])
                )
            )
            self._bm25 = BM25Index({str(cid): parse_tsvector(fts) for cid, fts in rows})

    # ArticleLookup — прямая выборка по статье (правила, проверка полноты).
    def find_by_article(self, article: str) -> list[DomainChunk]:
        return list(self._by_article.get(article, []))

    async def _dense(
        self, session: AsyncSession, vector: list[float], ids: list[str] | None = None
    ) -> dict[str, float]:
        distance = RegulationChunk.embedding.cosine_distance(vector)
        rows = await session.execute(
            select(RegulationChunk.id, distance)
            .where(
                RegulationChunk.id.in_([uuid.UUID(i) for i in (ids or self._chunks)]),
                RegulationChunk.embedding.is_not(None),
                func.vector_dims(RegulationChunk.embedding) == len(vector),
            )
            .order_by(distance)
            .limit(CHANNEL_LIMIT)
        )
        return {str(chunk_id): 1.0 - float(dist) for chunk_id, dist in rows}

    async def _lexical(self, session: AsyncSession, query: str) -> dict[str, float]:
        """BM25 по леммам: запрос лемматизируется тем же to_tsvector('russian')."""
        cleaned = PLACEHOLDER.sub(" ", query)
        if not cleaned.strip() or self._bm25 is None:
            return {}
        lexemes = await session.scalar(select(cast(func.to_tsvector("russian", cleaned), Text)))
        terms = parse_tsvector(lexemes or "")
        return self._bm25.search(list(terms), limit=CHANNEL_LIMIT)

    async def _hints(
        self, session: AsyncSession, query: str, vector: list[float] | None
    ) -> list[str]:
        """Части подсказанных статей; внутри — по близости к пункту (если есть вектор).
        Порядок: по одной лучшей части каждой статьи, затем остальные."""
        per_article: list[list[str]] = []
        for article in hinted_articles(query, self.settings.article_hints):
            ids = [chunk.db_id for chunk in self._by_article.get(article, []) if chunk.db_id]
            if not ids:
                continue
            if vector is not None and len(ids) > 1:
                scores = await self._dense(session, vector, ids)
                ids.sort(key=lambda i: scores.get(i, -1.0), reverse=True)
            per_article.append(ids)
        ordered: list[str] = []
        depth = max((len(ids) for ids in per_article), default=0)
        for level in range(depth):
            ordered.extend(ids[level] for ids in per_article if level < len(ids))
        return list(dict.fromkeys(ordered))

    async def search(
        self,
        query: str,
        top_k: int | None = None,
        *,
        channels: Iterable[str] | None = None,
        use_reranker: bool = True,
    ) -> list[RetrievedRegulation]:
        if not query.strip() or not self._chunks:
            return []
        active = frozenset(channels) if channels is not None else self.settings.channels
        limit = top_k or self.settings.top_k

        dense: dict[str, float] = {}
        lexical: dict[str, float] = {}
        hints: list[str] = []
        vector = None
        if active & {"dense", "hints"}:
            vector = (await self._embedder.embed([query]))[0]
        async with self._sessionmaker() as session:
            if "dense" in active:
                dense = await self._dense(session, vector)
            if "lexical" in active:
                lexical = await self._lexical(session, query)
            if "hints" in active:
                hints = await self._hints(session, query, vector)

        rankings = {
            "dense": list(dense),
            "lexical": list(lexical),
            "hints": hints,
        }
        fused = rrf_fuse(
            {name: ids for name, ids in rankings.items() if ids},
            weights=self.settings.channel_weights,
        )
        candidates = fused[: max(self.settings.candidates, limit)]

        floor = self.settings.similarity_floor
        if floor > 0:
            candidates = [
                (cid, score)
                for cid, score in candidates
                if cid in lexical or cid in hints or dense.get(cid, 0.0) >= floor
            ]

        rerank_scores: list[float] | None = None
        if use_reranker and candidates:
            rerank_scores = await self._reranker.rerank(
                query, [self._chunks[cid].text for cid, _ in candidates]
            )
        order = list(range(len(candidates)))
        if rerank_scores is not None:
            order.sort(key=lambda i: (rerank_scores[i], candidates[i][1]), reverse=True)

        selected: list[int] = []
        per_article: dict[str, int] = {}
        cap = self.settings.max_per_article
        for index in order:
            article = self._chunks[candidates[index][0]].article
            if cap and article and per_article.get(article, 0) >= cap:
                continue
            if article:
                per_article[article] = per_article.get(article, 0) + 1
            selected.append(index)
            if len(selected) >= limit:
                break

        results: list[RetrievedRegulation] = []
        for position, index in enumerate(selected, start=1):
            cid, fused_score = candidates[index]
            trace = {
                "rank": position,
                "channels": [name for name, ids in rankings.items() if cid in ids],
                "vector_score": dense.get(cid),
                "lexical_score": lexical.get(cid),
                "fused_score": fused_score,
                "rerank_score": rerank_scores[index] if rerank_scores is not None else None,
            }
            results.append(
                RetrievedRegulation(
                    regulation=self._chunks[cid],
                    similarity_score=dense.get(cid, 0.0),
                    trace=trace,
                )
            )
        return results
