"""Выгрузка отчёта PDF/DOCX (Ф-14). Зона агента B."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.analysis.results import load_analysis_result
from app.core.db import get_session
from app.core.models import DocumentType
from app.core.security import CurrentUser, get_current_user
from app.reports.export import render_report

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
    session: AsyncSession = Depends(get_session),
) -> Response:
    result = await load_analysis_result(session, analysis_id, user)
    document_type = await session.get(DocumentType, result.document_type_id)
    content = await run_in_threadpool(
        render_report, result, format, document_type.title if document_type else None
    )
    extension = format.value
    filename = quote(f"Отчёт о проверке.{extension}", safe="")
    return Response(
        content,
        media_type=(
            "application/pdf"
            if format is ReportFormat.PDF
            else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f"attachment; filename=report.{extension}; filename*=UTF-8''{filename}",
            "Cache-Control": "private, no-store",
        },
    )
