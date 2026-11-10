"""Каталог типов документов. Зона агента A."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.models import DocumentType
from app.core.security import CurrentUser, get_current_user

from .schemas import DocumentTypeOut

router = APIRouter(prefix="/document-types", tags=["Типы документов"])


@router.get("", response_model=list[DocumentTypeOut], summary="Каталог типов документов")
async def list_document_types(
    session: AsyncSession = Depends(get_session),
    _: CurrentUser = Depends(get_current_user),
) -> list[DocumentType]:
    rows = await session.scalars(select(DocumentType).order_by(DocumentType.sort_order))
    return list(rows)
