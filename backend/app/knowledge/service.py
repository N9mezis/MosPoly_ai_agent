"""Нормативная база в БД: загрузка версий, индексация, активация, откат (Ф-16).

Версии неизменяемы: правка нормы — это новая версия. Эмбеддинги считаются один раз
при индексации версии; активация — одна транзакция без пересчёта.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import UTC, date, datetime

from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.models import (
    RegulationChunk,
    RegulationSource,
    RegulationVersion,
    RegulationVersionStatus,
)
from app.llm.embeddings import AsyncEmbedder

from .embedding_cache import CachedEmbedder

logger = logging.getLogger(__name__)

MAX_CHUNK_CHARS = 1500


class RegulationFileRejected(AppError):
    status_code = 422
    code = "regulation_rejected"


# ------------------------------------------------------------------ формат файла


class SourceChunkIn(BaseModel):
    chunk_id: str | None = None
    article: str | None = None
    part: str | None = None
    title: str = ""
    text: str

    @field_validator("text")
    @classmethod
    def _text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Нормативный фрагмент не может быть пустым")
        return normalized


class SourceFileIn(BaseModel):
    source_id: str
    source_title: str
    label: str = ""
    source_url: str | None = None
    edition_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    chunks: list[SourceChunkIn] = Field(min_length=1)

    @field_validator("source_id")
    @classmethod
    def _source_id(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value):
            raise ValueError("source_id может содержать только латиницу, цифры, _ и -")
        return value


def parse_source_file(raw: bytes) -> SourceFileIn:
    try:
        return SourceFileIn.model_validate_json(raw)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(item) for item in first.get("loc", ()))
        raise RegulationFileRejected(
            f"Файл нормативки не соответствует формату: {location} — {first.get('msg')}",
            details={"errors": json.loads(error.json())[:10]},
        ) from error


def _split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    if len(text) <= limit:
        return [text]
    sentences = re.split(r"(?<=[.;])\s+", text)
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if current and len(current) + len(sentence) + 1 > limit:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def embedding_text(source_title: str, chunk: RegulationChunk) -> str:
    """Текст для эмбеддинга с контекстным заголовком: короткие части без него теряют смысл."""
    header = source_title
    if chunk.article:
        header += f", ст. {chunk.article}"
    if chunk.title:
        header += f" «{chunk.title}»"
    if chunk.part:
        header += f", ч. {chunk.part}"
    return f"{header}: {chunk.text}"


# ------------------------------------------------------------------ операции


async def create_version(
    session: AsyncSession, raw: bytes, *, uploaded_by: uuid.UUID | None
) -> RegulationVersion:
    data = parse_source_file(raw)
    canonical = json.dumps(data.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    source = await session.get(RegulationSource, data.source_id)
    if source is None:
        source = RegulationSource(
            id=data.source_id, title=data.source_title, source_url=data.source_url
        )
        session.add(source)
        await session.flush()

    duplicate = await session.scalar(
        select(RegulationVersion).where(
            RegulationVersion.source_id == data.source_id,
            RegulationVersion.content_hash == content_hash,
        )
    )
    if duplicate is not None:
        raise ConflictError(
            "Такая версия уже загружена",
            code="duplicate_version",
            details={"version_id": str(duplicate.id)},
        )

    version = RegulationVersion(
        source_id=data.source_id,
        label=data.label or (data.edition_date.isoformat() if data.edition_date else ""),
        edition_date=data.edition_date,
        effective_from=data.effective_from,
        effective_to=data.effective_to,
        status=RegulationVersionStatus.DRAFT,
        content_hash=content_hash,
        uploaded_by=uploaded_by,
    )
    session.add(version)
    await session.flush()

    count = 0
    seen: set[str] = set()
    for index, item in enumerate(data.chunks, start=1):
        base_key = item.chunk_id or f"{data.source_id}_{item.article or 'x'}_{index}"
        pieces = _split_text(item.text)
        for piece_index, piece in enumerate(pieces, start=1):
            key = base_key if len(pieces) == 1 else f"{base_key}_{piece_index}"
            if key in seen:
                raise RegulationFileRejected(f"Повторяющийся chunk_id: {key}")
            seen.add(key)
            session.add(
                RegulationChunk(
                    version_id=version.id,
                    chunk_key=key,
                    article=item.article,
                    part=item.part,
                    title=item.title,
                    text=piece,
                )
            )
            count += 1
    version.chunks_count = count
    await session.flush()
    return version


async def index_version(
    sessionmaker: async_sessionmaker[AsyncSession],
    version_id: uuid.UUID,
    embedder: AsyncEmbedder,
) -> RegulationVersion:
    """Считает эмбеддинги всех фрагментов версии. Статус: indexing → ready | failed."""
    async with sessionmaker() as session:
        version = await session.get(RegulationVersion, version_id)
        if version is None:
            raise NotFoundError("Версия нормативки не найдена")
        source = await session.get(RegulationSource, version.source_id)
        previous_status = version.status
        version.status = RegulationVersionStatus.INDEXING
        await session.commit()

        chunks = list(
            await session.scalars(
                select(RegulationChunk)
                .where(RegulationChunk.version_id == version_id)
                .order_by(RegulationChunk.chunk_key)
            )
        )
        try:
            cached = CachedEmbedder(embedder, sessionmaker)
            vectors = await cached.embed(
                [embedding_text(source.title if source else "", chunk) for chunk in chunks]
            )
            for chunk, vector in zip(chunks, vectors, strict=True):
                chunk.embedding = vector
            version.embedding_model = embedder.model_name
            version.error_message = ""
            version.status = (
                RegulationVersionStatus.ACTIVE
                if previous_status is RegulationVersionStatus.ACTIVE
                else RegulationVersionStatus.READY
            )
        except Exception as error:
            logger.exception("Индексация версии %s не удалась", version_id)
            version.status = RegulationVersionStatus.FAILED
            version.error_message = f"Не удалось рассчитать эмбеддинги: {type(error).__name__}"
        await session.commit()
        await session.refresh(version)
        return version


async def activate_version(session: AsyncSession, version_id: uuid.UUID) -> RegulationVersion:
    """Делает версию активной; прежняя активная версия источника уходит в архив. Это же — откат."""
    version = await session.get(RegulationVersion, version_id, with_for_update=True)
    if version is None:
        raise NotFoundError("Версия нормативки не найдена")
    if version.status is RegulationVersionStatus.ACTIVE:
        return version
    if version.status not in (RegulationVersionStatus.READY, RegulationVersionStatus.ARCHIVED):
        raise ConflictError(
            "Активировать можно только проиндексированную или архивную версию",
            code="version_not_ready",
        )
    missing = await session.scalar(
        select(func.count())
        .select_from(RegulationChunk)
        .where(RegulationChunk.version_id == version_id, RegulationChunk.embedding.is_(None))
    )
    if missing:
        raise ConflictError("У версии есть фрагменты без эмбеддингов: переиндексируйте её")

    await session.execute(
        update(RegulationVersion)
        .where(
            RegulationVersion.source_id == version.source_id,
            RegulationVersion.status == RegulationVersionStatus.ACTIVE,
        )
        .values(status=RegulationVersionStatus.ARCHIVED)
    )
    await session.flush()
    version.status = RegulationVersionStatus.ACTIVE
    version.activated_at = datetime.now(UTC)
    await session.flush()
    return version


async def archive_version(session: AsyncSession, version_id: uuid.UUID) -> RegulationVersion:
    version = await session.get(RegulationVersion, version_id, with_for_update=True)
    if version is None:
        raise NotFoundError("Версия нормативки не найдена")
    if version.status in (RegulationVersionStatus.INDEXING,):
        raise ConflictError("Версия ещё индексируется")
    version.status = RegulationVersionStatus.ARCHIVED
    await session.flush()
    return version


async def active_versions_count(session: AsyncSession) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(RegulationVersion)
            .where(RegulationVersion.status == RegulationVersionStatus.ACTIVE)
        )
        or 0
    )
