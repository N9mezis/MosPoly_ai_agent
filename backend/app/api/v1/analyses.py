"""Проверки: запуск, статус, результат, история (Ф-11, Ф-13). Зона агента A.

ЗАГЛУШКА (Шаг 0): отвечает фикстурами с заголовком X-Stub: true.
Контракт ответов окончательный (см. schemas.py).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Response, status

from app.core.models import AnalysisStatus
from app.core.security import CurrentUser, get_current_user

from . import fixtures
from .common import mark_stub
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
    responses={404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def create_analysis(
    body: AnalysisCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisCreated:
    mark_stub(response)
    return AnalysisCreated(analysis_id=fixtures.FIXTURE_ANALYSIS_ID, status=AnalysisStatus.QUEUED)


@router.get(
    "",
    response_model=Page[AnalysisListItem],
    summary="История проверок (свои; для org_admin — вся организация)",
)
async def list_analyses(
    response: Response,
    status_filter: AnalysisStatus | None = Query(default=None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: CurrentUser = Depends(get_current_user),
) -> Page[AnalysisListItem]:
    mark_stub(response)
    items = fixtures.fixture_history()
    if status_filter:
        items = [i for i in items if i.status == status_filter]
    return Page(items=items, total=len(items), page=page, page_size=page_size)


@router.get(
    "/{analysis_id}",
    response_model=AnalysisStatusOut,
    summary="Статус проверки",
    responses={404: {"model": ErrorResponse}},
)
async def get_analysis_status(
    analysis_id: uuid.UUID,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisStatusOut:
    mark_stub(response)
    return fixtures.fixture_status(analysis_id)


@router.get(
    "/{analysis_id}/result",
    response_model=AnalysisResult,
    summary="Результат проверки: текст документа, замечания, технические сбои",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def get_analysis_result(
    analysis_id: uuid.UUID,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> AnalysisResult:
    mark_stub(response)
    return fixtures.fixture_result(analysis_id)


@router.delete(
    "/{analysis_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отменить (если идёт) или удалить проверку",
)
async def delete_analysis(
    analysis_id: uuid.UUID,
    response: Response,
    user: CurrentUser = Depends(get_current_user),
) -> None:
    mark_stub(response)
