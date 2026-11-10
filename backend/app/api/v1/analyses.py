"""Проверки: запуск, статус, результат, история (Ф-11, Ф-13). Зона агента A."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis import results
from app.analysis.queue import enqueue_analysis
from app.analysis.service import create_analysis
from app.audit.service import log_event
from app.core.db import get_session
from app.core.models import AnalysisStatus
from app.core.security import CurrentUser, get_current_user

from .schemas import (
    AnalysisCreate,
    AnalysisCreated,
    AnalysisListItem,
    AnalysisResult,
    AnalysisStatusOut,
    ErrorResponse,
    Page,
)

router = APIRouter(prefix="/analyses", tags=["Проверки"])


@router.post(
    "",
    response_model=AnalysisCreated,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Запустить проверку загруженного документа",
    description="Повторный запрос с тем же `Idempotency-Key` вернёт уже созданную проверку.",
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def start_analysis(
    body: AnalysisCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=128),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisCreated:
    analysis, created = await create_analysis(
        session,
        user=user,
        document_id=body.document_id,
        document_type_id=body.document_type_id,
        idempotency_key=idempotency_key,
    )
    await session.commit()
    if created:
        await enqueue_analysis(analysis.id)
    else:
        response.status_code = status.HTTP_200_OK
    return AnalysisCreated(analysis_id=analysis.id, status=analysis.status)


@router.get(
    "",
    response_model=Page[AnalysisListItem],
    summary="История проверок (свои; для org_admin — вся организация)",
)
async def list_analyses(
    status_filter: AnalysisStatus | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> Page[AnalysisListItem]:
    return await results.list_history(
        session, user, status=status_filter, page=page, page_size=page_size
    )


@router.get(
    "/{analysis_id}",
    response_model=AnalysisStatusOut,
    summary="Статус проверки",
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis_status(
    analysis_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisStatusOut:
    analysis = await results.get_analysis_for_user(session, analysis_id, user)
    return results.status_out(analysis)


@router.get(
    "/{analysis_id}/result",
    response_model=AnalysisResult,
    summary="Результат проверки: текст документа, замечания, технические сбои",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_analysis_result(
    analysis_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisResult:
    return await results.load_analysis_result(session, analysis_id, user)


@router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отменить (если идёт) или удалить проверку",
    responses={404: {"model": ErrorResponse}},
)
async def delete_analysis(
    analysis_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    analysis = await results.get_analysis_for_user(session, analysis_id, user)
    if analysis.status in (
        AnalysisStatus.QUEUED,
        AnalysisStatus.EXTRACTING,
        AnalysisStatus.ANALYZING,
    ):
        analysis.status = AnalysisStatus.CANCELLED
        analysis.stage = "Отменена"
        action = "analysis.cancel"
    else:
        await session.delete(analysis)
        action = "analysis.delete"
    await log_event(
        session, actor=user, action=action, entity_type="analysis", entity_id=str(analysis_id)
    )
    await session.commit()
