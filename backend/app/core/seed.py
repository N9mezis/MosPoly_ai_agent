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
        "недел": ["91"],
        "часов": ["91"],
        "рабочего времени": ["91", "100"],
        "режим": ["100"],
        "график": ["100"],
        "выходн": ["100"],
        "отпуск": ["115"],
        "испыт": ["70"],
        "заработн": ["136"],
        "выплат": ["136"],
        "оклад": ["57", "136"],
        "оплат": ["57", "136"],
        "место работы": ["57"],
        "функци": ["57"],
        "должност": ["57"],
    },
    # Рамки MVP: стандартный трудовой договор. Раздел XII ТК (ст. 251–351, особенности
    # отдельных категорий работников) не подаётся модели, пока в договоре нет признака
    # соответствующей категории — иначе модель применяет условные нормы к обычному договору.
    "excluded_article_ranges": [[251, 351.99]],
    "unlock_triggers": {
        "несовершеннолет": [[265, 272]],
        "не достигш": [[265, 272]],
        "должность генерального директора": [[273, 281]],
        "должность директора": [[273, 281]],
        "руководителем организации": [[273, 281]],
        "совместительств": [[282, 288]],
        "срочный трудовой договор": [[289, 292]],
        "до двух месяцев": [[289, 292]],
        "сезонн": [[293, 296]],
        "вахт": [[297, 302]],
        "индивидуальный предприниматель": [[303, 309]],
        "работодатель - физическое лицо": [[303, 309]],
        "надомн": [[310, 312]],
        "дистанционн": [[312.1, 312.99]],
        "удаленн": [[312.1, 312.99]],
        "крайнего севера": [[313, 327]],
        "приравненных к ним местностях": [[313, 327]],
        "иностранн": [[327.1, 327.99]],
        "без гражданства": [[327.1, 327.99]],
        "педагогическ": [[331, 336.99]],
        "научн": [[336.1, 336.99]],
        "заемн": [[341.1, 341.99]],
        "религиозн": [[342, 347]],
        "спортсмен": [[348.1, 348.99]],
        "тренер": [[348.1, 348.99]],
        "медицинск": [[350, 350]],
        "творческ": [[351, 351]],
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
