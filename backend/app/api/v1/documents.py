"""Загрузка документа (Ф-01, ТЗ 4.2 «Загрузка документа»). Зона агента A."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import log_event
from app.core.config import get_settings
from app.core.db import get_session
from app.core.models import Document
from app.core.security import CurrentUser, get_current_user
from app.documents.upload import store_upload

from .schemas import DocumentUploaded, ErrorResponse

router = APIRouter(prefix="/documents", tags=["Документы"])


@router.post(
    "",
    response_model=DocumentUploaded,
    status_code=status.HTTP_201_CREATED,
    summary="Загрузить договор (DOCX/PDF, до 10 МБ)",
    responses={422: {"model": ErrorResponse, "description": "Файл отклонён"}},
)
async def upload_document(
    file: UploadFile = File(..., description="Трудовой договор в формате DOCX или PDF"),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> DocumentUploaded:
    settings = get_settings()
    stored = await store_upload(
        file, upload_dir=settings.upload_tmp_dir, max_bytes=settings.max_upload_bytes
    )
    document = Document(
        organization_id=user.organization_id,
        uploaded_by=user.id,
        original_filename=stored.filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        page_count=stored.page_count,
        storage_key=stored.storage_key,
    )
    session.add(document)
    await session.flush()
    await log_event(
        session,
        actor=user,
        action="document.upload",
        entity_type="document",
        entity_id=str(document.id),
        payload={"size_bytes": stored.size_bytes, "mime_type": stored.mime_type},
    )
    await session.commit()
    return DocumentUploaded(
        document_id=document.id,
        filename=stored.filename,
        size_bytes=stored.size_bytes,
        page_count=stored.page_count,
    )
