"""Авторизация, пользователи, организации (Ф-15, НФ-09). Зона агента B."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.audit.service import log_event
from app.auth.passwords import hash_password, verify_password
from app.auth.tokens import active_users, issue_tokens, token_hash
from app.core.db import get_session
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, UnauthorizedError
from app.core.models import Organization, RefreshToken, User, UserRole
from app.core.security import CurrentUser, get_current_user, require_role

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
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)) -> TokenPair:
    user = await session.scalar(
        active_users().where(func.lower(User.email) == body.email.strip().lower()).with_for_update(of=User)
    )
    if user is None or not await run_in_threadpool(verify_password, user.password_hash, body.password):
        raise UnauthorizedError("Неверный email или пароль")
    user.last_login_at = datetime.now(UTC)
    pair = _issue_pair(session, user)
    await _audit_auth(session, user, "auth.login")
    await session.commit()
    return pair


def _issue_pair(session: AsyncSession, user: User) -> TokenPair:
    access, refresh_token, ttl = issue_tokens(session, user)
    return TokenPair(access_token=access, refresh_token=refresh_token, expires_in=ttl)


async def _audit_auth(session: AsyncSession, user: User, action: str) -> None:
    actor = CurrentUser(user.id, user.organization_id, user.role, user.email, user.full_name)
    await log_event(session, actor=actor, action=action, entity_type="user", entity_id=str(user.id))


async def _revoke_refresh(session: AsyncSession, token: str) -> uuid.UUID | None:
    now = datetime.now(UTC)
    return await session.scalar(
        update(RefreshToken)
        .where(
            RefreshToken.token_hash == token_hash(token),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .returning(RefreshToken.user_id)
    )


@auth_router.post("/refresh", response_model=TokenPair, summary="Обновить access-токен")
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_session)) -> TokenPair:
    owner_id = select(RefreshToken.user_id).where(
        RefreshToken.token_hash == token_hash(body.refresh_token)
    ).scalar_subquery()
    user = await session.scalar(active_users().where(User.id == owner_id).with_for_update(of=User))
    if user is None or await _revoke_refresh(session, body.refresh_token) is None:
        raise UnauthorizedError("Недействительный refresh-токен")
    pair = _issue_pair(session, user)
    await session.commit()
    return pair


@auth_router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Выход")
async def logout(body: RefreshRequest, session: AsyncSession = Depends(get_session)) -> None:
    user_id = await _revoke_refresh(session, body.refresh_token)
    if user_id is not None:
        user = await session.get(User, user_id)
        if user is not None:
            await _audit_auth(session, user, "auth.logout")
    await session.commit()


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
    actor: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN)),
    session: AsyncSession = Depends(get_session),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Page[UserOut]:
    query = _visible_users(actor)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    users = await session.scalars(
        query.order_by(User.created_at, User.id).offset((page - 1) * page_size).limit(page_size)
    )
    return Page[UserOut](
        items=[UserOut.model_validate(user) for user in users],
        total=total or 0,
        page=page,
        page_size=page_size,
    )


def _visible_users(actor: CurrentUser):
    query = select(User)
    if actor.role is UserRole.ORG_ADMIN:
        query = query.where(User.organization_id == actor.organization_id)
    return query


def _check_managed_role(actor: CurrentUser, role: UserRole) -> None:
    if actor.role is UserRole.ORG_ADMIN and role not in {UserRole.USER, UserRole.ORG_ADMIN}:
        raise ForbiddenError("Недостаточно прав для управления этой ролью")


@users_router.post("", response_model=UserOut, status_code=201, summary="Создать пользователя")
async def create_user(
    body: UserCreate,
    actor: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    _check_managed_role(actor, body.role)
    organization_id = body.organization_id or actor.organization_id
    if actor.role is UserRole.ORG_ADMIN and organization_id != actor.organization_id:
        raise ForbiddenError("Нельзя создавать пользователей в другой организации")
    org = await session.get(Organization, organization_id)
    if org is None or not org.is_active:
        raise NotFoundError("Организация не найдена")
    user = User(
        organization_id=organization_id,
        email=body.email.strip().lower(),
        full_name=body.full_name,
        role=body.role,
        password_hash=await run_in_threadpool(hash_password, body.password),
    )
    session.add(user)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError("Не удалось создать пользователя: проверьте уникальность email") from exc
    await log_event(session, actor=actor, action="user.create", entity_type="user", entity_id=str(user.id))
    await session.commit()
    return UserOut.model_validate(user)


@users_router.patch("/{user_id}", response_model=UserOut, summary="Изменить пользователя")
async def update_user(
    user_id: uuid.UUID,
    body: UserUpdate,
    actor: CurrentUser = Depends(require_role(UserRole.ORG_ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> UserOut:
    user = await session.scalar(_visible_users(actor).where(User.id == user_id).with_for_update())
    if user is None:
        raise NotFoundError("Пользователь не найден")
    _check_managed_role(actor, user.role)
    if body.role is not None:
        _check_managed_role(actor, body.role)
        user.role = body.role
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password is not None:
        user.password_hash = await run_in_threadpool(hash_password, body.password)
    if body.is_active is False or body.password is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    await log_event(session, actor=actor, action="user.update", entity_type="user", entity_id=str(user.id))
    await session.commit()
    return UserOut.model_validate(user)


@orgs_router.get("", response_model=list[OrganizationOut], summary="Организации")
async def list_orgs(
    _: CurrentUser = Depends(require_role(UserRole.SERVICE_ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> list[OrganizationOut]:
    organizations = await session.scalars(select(Organization).order_by(Organization.name, Organization.id))
    return [OrganizationOut.model_validate(org) for org in organizations]


@orgs_router.post(
    "", response_model=OrganizationOut, status_code=201, summary="Создать организацию"
)
async def create_org(
    body: OrganizationCreate,
    actor: CurrentUser = Depends(require_role(UserRole.SERVICE_ADMIN)),
    session: AsyncSession = Depends(get_session),
) -> OrganizationOut:
    org = Organization(name=body.name, inn=body.inn)
    session.add(org)
    await session.flush()
    await log_event(
        session, actor=actor, action="organization.create", entity_type="organization", entity_id=str(org.id)
    )
    await session.commit()
    return OrganizationOut.model_validate(org)
