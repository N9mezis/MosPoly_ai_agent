"""Нормативная база: источники, версии, активация, откат (Ф-16). Зона агента A."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.queue import enqueue_indexing
from app.audit.service import log_event
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.models import (
    RegulationChunk,
    RegulationSource,
    RegulationVersion,
    RegulationVersionStatus,
    User,
    UserRole,
)
from app.core.security import CurrentUser, get_current_user, require_role
from app.knowledge import service

from .schemas import ErrorResponse, RegulationChunkOut, RegulationSourceOut, RegulationVersionOut

router = APIRouter(prefix="/regulations", tags=["Нормативная база"])

MAX_REGULATION_FILE = 5 * 1024 * 1024


async def _version_out(session: AsyncSession, version: RegulationVersion) -> RegulationVersionOut:
    uploader = await session.get(User, version.uploaded_by) if version.uploaded_by else None
    out = RegulationVersionOut.model_validate(version)
    out.uploaded_by_name = uploader.full_name if uploader else ""
    return out


@router.get("", response_model=list[RegulationSourceOut], summary="Источники и их версии")
async def list_sources(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> list[RegulationSourceOut]:
    sources = list(await session.scalars(select(RegulationSource).order_by(RegulationSource.id)))
    versions = list(
        await session.scalars(
            select(RegulationVersion).order_by(RegulationVersion.created_at.desc())
        )
    )
    uploaders = {
        user.id: user.full_name
        for user in await session.scalars(
            select(User).where(User.id.in_({v.uploaded_by for v in versions if v.uploaded_by}))
        )
    }
    result: list[RegulationSourceOut] = []
    for source in sources:
        own = [v for v in versions if v.source_id == source.id]
        outs = []
        for version in own:
            out = RegulationVersionOut.model_validate(version)
            out.uploaded_by_name = uploaders.get(version.uploaded_by, "")
            outs.append(out)
        result.append(
            RegulationSourceOut(
                id=source.id,
                title=source.title,
                source_url=source.source_url,
                active_version_id=next(
                    (v.id for v in own if v.status is RegulationVersionStatus.ACTIVE), None
                ),
                versions=outs,
            )
        )
    return result


@router.post(
    "",
    response_model=RegulationVersionOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Загрузить новую версию источника (JSON); индексация идёт в фоне",
    description=(
        "Формат — `data/regulations/source.example.json`. Версия создаётся в статусе `draft`, "
        "воркер считает эмбеддинги (`indexing` → `ready`). С `activate=true` версия станет "
        "активной сразу после индексации."
    ),
    responses={409: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def upload_version(
    file: UploadFile = File(..., description="JSON в формате data/regulations/source.example.json"),
    activate: bool = Query(False, description="Активировать после индексации"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    raw = await file.read(MAX_REGULATION_FILE + 1)
    if len(raw) > MAX_REGULATION_FILE:
        raise service.RegulationFileRejected("Файл нормативки больше 5 МБ")
    version = await service.create_version(session, raw, uploaded_by=user.id)
    await log_event(
        session,
        actor=user,
        action="regulation.upload",
        entity_type="regulation_version",
        entity_id=str(version.id),
        payload={"source_id": version.source_id, "chunks": version.chunks_count},
    )
    await session.commit()
    await enqueue_indexing(version.id, activate=activate)
    return await _version_out(session, version)


@router.get(
    "/versions/{version_id}/chunks",
    response_model=list[RegulationChunkOut],
    summary="Фрагменты версии",
)
async def list_version_chunks(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> list[RegulationChunk]:
    if await session.get(RegulationVersion, version_id) is None:
        raise NotFoundError("Версия нормативки не найдена")
    rows = await session.scalars(
        select(RegulationChunk)
        .where(RegulationChunk.version_id == version_id)
        .order_by(RegulationChunk.chunk_key)
    )
    return list(rows)


@router.post(
    "/versions/{version_id}/activate",
    response_model=RegulationVersionOut,
    summary="Активировать версию (прежняя активная уходит в архив). Это же — откат.",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def activate_version(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    version = await service.activate_version(session, version_id)
    await log_event(
        session,
        actor=user,
        action="regulation.activate",
        entity_type="regulation_version",
        entity_id=str(version_id),
        payload={"source_id": version.source_id},
    )
    await session.commit()
    return await _version_out(session, version)


@router.post(
    "/versions/{version_id}/archive",
    response_model=RegulationVersionOut,
    summary="Отправить версию в архив",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def archive_version(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    version = await service.archive_version(session, version_id)
    await log_event(
        session,
        actor=user,
        action="regulation.archive",
        entity_type="regulation_version",
        entity_id=str(version_id),
        payload={"source_id": version.source_id},
    )
    await session.commit()
    return await _version_out(session, version)


@router.post(
    "/versions/{version_id}/reindex",
    response_model=RegulationVersionOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Пересчитать эмбеддинги версии (после смены модели эмбеддингов)",
)
async def reindex_version(
    version_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    version = await session.get(RegulationVersion, version_id)
    if version is None:
        raise NotFoundError("Версия нормативки не найдена")
    await enqueue_indexing(version.id)
    return await _version_out(session, version)
