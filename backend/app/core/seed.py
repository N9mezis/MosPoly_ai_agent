"""Начальные данные: организация, сид-администратор, типы документов, профиль проверки.

Идемпотентно: повторный запуск ничего не дублирует. Вызывается при старте api-контейнера.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.domain.document_types import DOCUMENT_TYPES

from .config import get_settings
from .models import (
    CheckProfile,
    DocumentType,
    Organization,
    ProfileSource,
    RegulationSource,
    User,
    UserRole,
)

logger = logging.getLogger(__name__)

TK_RF_SOURCE_ID = "tk_rf"

DEFAULT_PROFILE_PARAMS: dict = {
    "candidates": 12,
    "top_k": 4,
    "similarity_floor": 0.0,
    # Статьи, которые подаются в проверку полноты договора напрямую, без поиска.
    "required_articles": ["57", "100"],
    # Подсказки «тема → статьи» для канала article hints в поиске.
    "article_hints": {
        "рабочее время": ["91"],
        "рабочей недели": ["91"],
        "часов в неделю": ["91"],
        "режим работы": ["100"],
        "режим рабочего времени": ["100"],
        "отпуск": ["115"],
        "испытани": ["70"],
        "заработн": ["136"],
        "оплат": ["136", "57"],
        "выплат": ["136"],
        "место работы": ["57"],
        "трудовая функция": ["57"],
        "должност": ["57"],
    },
    # Пороги детерминированных правил (пока правила читают свои константы).
    "rules": {
        "max_work_week_hours": 40,
        "min_annual_leave_days": 28,
        "max_probation_months": 3,
        "max_salary_payment_interval_days": 15,
    },
}


async def seed(session: AsyncSession) -> None:
    settings = get_settings()

    org = await session.scalar(
        select(Organization).where(Organization.name == settings.seed_org_name)
    )
    if org is None:
        org = Organization(name=settings.seed_org_name)
        session.add(org)
        await session.flush()
        logger.info("Создана организация «%s»", org.name)

    admin_email = settings.seed_admin_email.lower()
    admin = await session.scalar(select(User).where(User.email == admin_email))
    if admin is None:
        session.add(
            User(
                organization_id=org.id,
                email=admin_email,
                password_hash=hash_password(settings.seed_admin_password.get_secret_value()),
                full_name="Администратор сервиса",
                role=UserRole.SERVICE_ADMIN,
            )
        )
        logger.info("Создан сид-администратор %s", admin_email)

    for order, item in enumerate(DOCUMENT_TYPES):
        if await session.get(DocumentType, item.id) is None:
            session.add(
                DocumentType(
                    id=item.id,
                    title=item.title,
                    description=item.description,
                    scope=item.scope,
                    allowed_extensions=item.allowed_extensions,
                    is_enabled=item.enabled,
                    sort_order=order,
                )
            )
    await session.flush()

    if await session.get(RegulationSource, TK_RF_SOURCE_ID) is None:
        session.add(
            RegulationSource(
                id=TK_RF_SOURCE_ID,
                title="Трудовой кодекс Российской Федерации",
                source_url="http://pravo.gov.ru/proxy/ips/?docbody=&nd=102074279",
            )
        )
        await session.flush()

    profile = await session.scalar(
        select(CheckProfile).where(
            CheckProfile.document_type_id == "employment-contract", CheckProfile.is_active
        )
    )
    if profile is None:
        profile = CheckProfile(
            document_type_id="employment-contract",
            version=1,
            params=DEFAULT_PROFILE_PARAMS,
            is_active=True,
        )
        session.add(profile)
        await session.flush()
        session.add(ProfileSource(profile_id=profile.id, source_id=TK_RF_SOURCE_ID))
        logger.info("Создан профиль проверки трудового договора v1")

    await session.commit()
