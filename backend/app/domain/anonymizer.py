"""Обезличивание персональных данных до любого обращения к внешней модели (Ф-03, НФТ-6).

Заменяет ФИО, паспортные данные, дату рождения, СНИЛС, ИНН, телефоны,
email и адреса проживания условными метками. Адрес работодателя / место
работы НЕ скрывается: это условие договора (ст. 57 ТК РФ), а не персональные
данные работника.

AnonymizedText — маркер-тип: в LLM и в БД попадает только он
(см. analysis/pipeline.py).
"""

from __future__ import annotations

import re


class AnonymizedText(str):
    """Текст, прошедший обезличивание."""


_UPPER = "А-ЯЁ"
_LOWER = "а-яё"
_NAME = rf"[{_UPPER}][{_LOWER}]+(?:-[{_UPPER}][{_LOWER}]+)?"
_UPPER_NAME = rf"[{_UPPER}][{_UPPER}]+(?:-[{_UPPER}][{_UPPER}]+)?"
# Отчество в любом падеже: Петрович/Петровича/Петровичем, Ивановна/Ивановной, Ильинична…
_PATRONYMIC = rf"[{_UPPER}][{_LOWER}]+(?:вич|вн|ичн|инич|ьич)[{_LOWER}]{{0,3}}"
_UPPER_PATRONYMIC = rf"[{_UPPER}][{_UPPER}]+(?:ВИЧ|ВН|ИЧН|ИНИЧ|ЬИЧ)[{_UPPER}]{{0,3}}"
_INITIALS = rf"[{_UPPER}]\.\s?[{_UPPER}]\."

_ADDRESS_LEAD = (
    r"(?:зарегистрирован\w*(?:\s+по\s+(?:месту\s+жительства\s+)?адресу)?"
    r"|проживающ\w*(?:\s+по\s+адресу)?"
    r"|адрес\s+(?:регистрации|места\s+жительства|проживания)"
    r"|место\s+жительства"
    r"|домашний\s+адрес)"
)

# Порядок важен: сначала обрабатываются более специфичные варианты.
PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("[EMAIL]", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "[PHONE]",
        re.compile(r"(?<!\d)(?:\+?7|8)[\s().-]*\d{3}[\s().-]*\d{3}[\s.-]*\d{2}[\s.-]*\d{2}(?!\d)"),
    ),
    (
        "[PASSPORT]",
        re.compile(
            r"(?i)(?<!\w)(?:паспорт\s*:?\s*(?:серия\s*)?\d{2}\s?\d{2}"
            r"\s*[,;]?\s*(?:№|N|номер)?\s*\d{6}|серия\s*\d{2}\s?\d{2}"
            r"\s*[,;]?\s*(?:№|N|номер)?\s*\d{6})(?!\w)"
        ),
    ),
    ("[PASSPORT]", re.compile(r"(?<!\d)\d{2}\s?\d{2}\s?\d{6}(?!\d)")),
    ("[SNILS]", re.compile(r"(?<!\d)\d{3}[ -]?\d{3}[ -]?\d{3}[ -]?\d{2}(?!\d)")),
    ("[INN]", re.compile(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)")),
    (
        "[BIRTH_DATE]",
        re.compile(
            r"(?i)(?<!\w)(?:дата\s+рождения|родил(?:ся|ась))"
            r"\s*[:№-]?\s*\d{1,2}[./-]\d{1,2}[./-]\d{4}(?!\d)"
        ),
    ),
    # Фамилия Имя Отчество / Имя Отчество Фамилия.
    ("[PERSON]", re.compile(rf"\b{_NAME}\s+{_NAME}\s+{_PATRONYMIC}\b")),
    ("[PERSON]", re.compile(rf"\b{_NAME}\s+{_PATRONYMIC}\s+{_NAME}\b")),
    # Те же варианты, набранные полностью заглавными буквами.
    ("[PERSON]", re.compile(rf"\b{_UPPER_NAME}\s+{_UPPER_NAME}\s+{_UPPER_PATRONYMIC}\b")),
    ("[PERSON]", re.compile(rf"\b{_UPPER_NAME}\s+{_UPPER_PATRONYMIC}\s+{_UPPER_NAME}\b")),
    # Фамилия И.О. / И.О. Фамилия.
    ("[PERSON]", re.compile(rf"\b{_NAME}\s+{_INITIALS}")),
    ("[PERSON]", re.compile(rf"{_INITIALS}\s?{_NAME}\b")),
)

ADDRESS_PATTERN = re.compile(
    rf"(?P<lead>{_ADDRESS_LEAD}\s*:?\s*)(?P<address>[^;\n]+?)(?=(?:;|\n|$|,\s*(?:паспорт|СНИЛС|ИНН|тел)))",
    re.IGNORECASE,
)


def anonymize_text(text: str) -> AnonymizedText:
    if isinstance(text, AnonymizedText):
        return text
    result = ADDRESS_PATTERN.sub(lambda m: f"{m.group('lead')}[ADDRESS]", text)
    for placeholder, pattern in PATTERNS:
        result = pattern.sub(placeholder, result)
    return AnonymizedText(result)


def contains_personal_data(text: str) -> bool:
    """Для тестов НФТ-6: остались ли в тексте узнаваемые ПДн."""
    if ADDRESS_PATTERN.search(text) and "[ADDRESS]" not in text:
        return True
    return any(pattern.search(text) for _, pattern in PATTERNS)
