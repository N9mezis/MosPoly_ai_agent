"""Авторизация, пользователи, организации (Ф-15, НФ-09). Зона агента B.

ЗАГЛУШКА (Шаг 0): /auth/me работает от dev-пользователя, остальное — 501.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import NotFoundError
from app.core.models import Organization, User, UserRole
from app.core.security import CurrentUser, get_current_user, require_role

from .common import NotImplementedYet
from .schemas import (
    ErrorResponse,
    LoginRequest,
    MeOut,
    OrganizationCreate,
    OrganizationOut,
    Page,
    RefreshRequest,
    TokenPair,
    UserCreate,
    UserOut,
    UserUpdate,
)

auth_router = APIRouter(prefix="/auth", tags=["Авторизация"])
users_router = APIRouter(prefix="/users", tags=["Пользователи"])
orgs_router = APIRouter(prefix="/organizations", tags=["Организации"])

ROLE_PERMISSIONS: dict[UserRole, list[str]] = {
    UserRole.USER: ["analyses:create"],
    UserRole.KB_EXPERT: ["analyses:create", "regulations:manage"],
    UserRole.ORG_ADMIN: ["analyses:create", "analyses:read_org", "users:manage"],
    UserRole.SERVICE_ADMIN: [
        "analyses:create",
        "analyses:read_org",
        "users:manage",
        "regulations:manage",
        "organizations:manage",
    ],
}


@auth_router.post(
    "/token",
    response_model=TokenPair,
    summary="Вход по email и паролю",
    responses={401: {"model": ErrorResponse}},
)
async def login(body: LoginRequest) -> TokenPair:
    raise NotImplementedYet("B")


@auth_router.post("/refresh", response_model=TokenPair, summary="Обновить access-токен")
async def refresh(body: RefreshRequest) -> TokenPair:
    raise NotImplementedYet("B")


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход")
async def logout(body: RefreshRequest) -> None:
    raise NotImplementedYet("B")


@auth_router.get("/me", response_model=MeOut, summary="Текущий пользователь и его права")
async def me(
    user: CurrentUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MeOut:
    db_user = await session.get(User, user.id)
    org = await session.get(Organization, user.organization_id)
    if db_user is None or org is None:
        raise NotFoundError("Пользователь не найден")
    return MeOut(
        **UserOut.model_validate(db_user).model_dump(),
        organization=OrganizationOut.model_validate(org),
        permissions=ROLE_PERMISSIONS[user.role],
    )


@users_router.get("", response_model=Page[UserOut], summary="Пользователи организации")
async def list_users(
    _: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN)),
) -> Page[UserOut]:
    raise NotImplementedYet("B")


@users_router.post("", response_model=UserOut, status_code=201, summary="Создать пользователя")
async def create_user(
    body: UserCreate, _: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN))
) -> UserOut:
    raise NotImplementedYet("B")


@users_router.patch("/{user_id}", response_model=UserOut, summary="Изменить пользователя")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    _: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN)),
) -> UserOut:
    raise NotImplementedYet("B")


@orgs_router.get("", response_model=list[OrganizationOut], summary="Организации")
async def list_orgs(
    _: CurrentUser = Depends(require_role(UserRole.SERVICE_ADMIN)),
) -> list[OrganizationOut]:
    raise NotImplementedYet("B")


@orgs_router.post(
    "", response_model=OrganizationOut, status_code=201, summary="Создать организацию"
)
async def create_org(
    body: OrganizationCreate, _: CurrentUser = Depends(require_role(UserRole.SERVICE_ADMIN))
) -> OrganizationOut:
    raise NotImplementedYet("B")
