"""Нормативная база: источники, версии, активация, откат (Ф-16). Зона агента A.

ЗАГЛУШКА (Шаг 0): отвечает фикстурами с заголовком X-Stub: true.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Response, UploadFile, status

from app.core.models import RegulationVersionStatus, UserRole
from app.core.security import CurrentUser, get_current_user, require_role

from . import fixtures
from .common import mark_stub
from .schemas import ErrorResponse, RegulationChunkOut, RegulationSourceOut, RegulationVersionOut

router = APIRouter(prefix="/regulations", tags=["Нормативная база"])


@router.get("", response_model=list[RegulationSourceOut], summary="Источники и их версии")
async def list_sources(
    response: Response, _: CurrentUser = Depends(get_current_user)
) -> list[RegulationSourceOut]:
    mark_stub(response)
    return fixtures.fixture_regulations()


@router.post(
    "",
    response_model=RegulationVersionOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Загрузить новую версию источника (JSON); индексация идёт в фоне",
    responses={422: {"model": ErrorResponse}},
)
async def upload_version(
    response: Response,
    file: UploadFile = File(..., description="JSON в формате data/regulations/source.example.json"),
    _: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    mark_stub(response)
    version = fixtures.fixture_regulations()[0].versions[0]
    return version.model_copy(
        update={
            "id": uuid.uuid4(),
            "status": RegulationVersionStatus.INDEXING,
            "label": file.filename or "",
        }
    )


@router.get(
    "/versions/{version_id}/chunks",
    response_model=list[RegulationChunkOut],
    summary="Фрагменты версии",
)
async def list_version_chunks(
    version_id: uuid.UUID, response: Response, _: CurrentUser = Depends(get_current_user)
) -> list[RegulationChunkOut]:
    mark_stub(response)
    return fixtures.fixture_chunks()


@router.post(
    "/versions/{version_id}/activate",
    response_model=RegulationVersionOut,
    summary="Активировать версию (прежняя активная уходит в архив). Это же — откат.",
    responses={409: {"model": ErrorResponse}},
)
async def activate_version(
    version_id: uuid.UUID,
    response: Response,
    _: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    mark_stub(response)
    version = fixtures.fixture_regulations()[0].versions[0]
    return version.model_copy(update={"id": version_id})


@router.post(
    "/versions/{version_id}/archive",
    response_model=RegulationVersionOut,
    summary="Отправить версию в архив",
)
async def archive_version(
    version_id: uuid.UUID,
    response: Response,
    _: CurrentUser = Depends(require_role(UserRole.KB_EXPERT)),
) -> RegulationVersionOut:
    mark_stub(response)
    version = fixtures.fixture_regulations()[0].versions[1]
    return version.model_copy(update={"id": version_id})
