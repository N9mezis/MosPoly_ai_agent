"""Зависимости авторизации — ФИКСИРОВАННЫЕ СИГНАТУРЫ, на них опирается весь API.

Агент B заменяет тело `get_current_user` на проверку JWT; сигнатуры
`CurrentUser`, `get_current_user`, `require_role`, `can_read_analysis` не меняются.

Пока `AUTH_DEV_MODE=true`, все запросы выполняются от имени сид-администратора
(создаётся `python -m app.cli seed`).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import get_settings
from .db import get_session
from .errors import ForbiddenError, UnauthorizedError
from .models import User, UserRole


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: uuid.UUID
    organization_id: uuid.UUID
    role: UserRole
    email: str
    full_name: str

    def has_role(self, *roles: UserRole) -> bool:
        return self.role in roles


async def get_current_user(session: AsyncSession = Depends(get_session)) -> CurrentUser:
    settings = get_settings()
    if not settings.auth_dev_mode:
        # TODO(агент B): разобрать Authorization: Bearer <JWT>, проверить подпись и срок,
        # загрузить пользователя, проверить is_active.
        raise UnauthorizedError("Требуется авторизация")
    user = await session.scalar(select(User).where(User.email == settings.seed_admin_email.lower()))
    if user is None:
        raise UnauthorizedError("Dev-пользователь не найден: выполните `python -m app.cli seed`")
    return CurrentUser(
        id=user.id,
        organization_id=user.organization_id,
        role=user.role,
        email=user.email,
        full_name=user.full_name,
    )


def require_role(*roles: UserRole) -> Callable[..., Awaitable[CurrentUser]]:
    """Зависимость: пропускает только пользователей с одной из ролей.

    service_admin проходит всегда.
    """

    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role is UserRole.SERVICE_ADMIN or user.role in roles:
            return user
        raise ForbiddenError("Недостаточно прав для этого действия")

    return dependency


def can_read_analysis(
    user: CurrentUser, *, organization_id: uuid.UUID, created_by: uuid.UUID | None
) -> bool:
    """Матрица доступа к проверкам (НФ-09).

    user — только свои; org_admin — все в своей организации; service_admin — все.
    kb_expert — как user (свои проверки).
    """
    if user.role is UserRole.SERVICE_ADMIN:
        return True
    if user.organization_id != organization_id:
        return False
    if user.role is UserRole.ORG_ADMIN:
        return True
    return created_by == user.id
