"""Access JWT и непрозрачные refresh-токены."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import UnauthorizedError
from app.core.models import Organization, RefreshToken, User


def decode_access(token: str) -> uuid.UUID:
    try:
        claims = jwt.decode(
            token,
            get_settings().jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"require": ["exp", "sub"]},
        )
        return uuid.UUID(claims["sub"])
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError) as exc:
        raise UnauthorizedError("Недействительный access-токен") from exc


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue_tokens(session: AsyncSession, user: User) -> tuple[str, str, int]:
    settings = get_settings()
    now = datetime.now(UTC)
    ttl = settings.jwt_access_ttl_minutes * 60
    access = jwt.encode(
        {"sub": str(user.id), "iat": now, "exp": now + timedelta(seconds=ttl)},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    refresh = secrets.token_urlsafe(32)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash(refresh),
            expires_at=now + timedelta(days=settings.jwt_refresh_ttl_days),
        )
    )
    return access, refresh, ttl


def active_users():
    return select(User).join(Organization).where(User.is_active, Organization.is_active)
