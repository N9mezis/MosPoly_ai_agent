"""Журнал значимых действий (Ф-17, НФ-12). Владелец — агент B.

СИГНАТУРА `log_event` ФИКСИРОВАНА: её вызывают сервисы обеих команд.
В payload нельзя класть ПДн, тексты договоров и секреты — только идентификаторы,
статусы, счётчики.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import AuditLog
from app.core.security import CurrentUser


async def log_event(
    session: AsyncSession,
    *,
    actor: CurrentUser | None,
    action: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, Any] | None = None,
    ip_address: str | None = None,
) -> None:
    """Добавляет запись в audit_log в текущей транзакции (commit делает вызывающий)."""
    session.add(
        AuditLog(
            organization_id=actor.organization_id if actor else None,
            actor_user_id=actor.id if actor else None,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload or {},
            ip_address=ip_address,
        )
    )
