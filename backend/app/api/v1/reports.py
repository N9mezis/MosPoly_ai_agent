"""Выгрузка отчёта PDF/DOCX (Ф-14). Зона агента B.

Строится поверх AnalysisResult (тот же DTO, что видит фронт). Пока A не подключил
настоящий конвейер, можно разрабатывать на app.api.v1.fixtures.fixture_result().
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.core.security import CurrentUser, get_current_user

from .common import NotImplementedYet
from .schemas import ErrorResponse, ReportFormat

router = APIRouter(prefix="/analyses", tags=["Отчёты"])


@router.get(
    "/{analysis_id}/report",
    summary="Скачать отчёт",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/pdf": {},
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": {},
            }
        },
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "Проверка ещё не завершена"},
    },
)
async def download_report(
    analysis_id: uuid.UUID,
    format: ReportFormat = Query(ReportFormat.PDF),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    raise NotImplementedYet("B")
