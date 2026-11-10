from __future__ import annotations

import re

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("[EMAIL]", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
    (
        "[PHONE]",
        re.compile(r"(?<!\d)(?:\+7|8)[\s()-]*\d{3}[\s()-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)"),
    ),
    ("[PASSPORT]", re.compile(r"(?<!\d)\d{2}\s?\d{2}\s?\d{6}(?!\d)")),
    ("[SNILS]", re.compile(r"(?<!\d)\d{3}-?\d{3}-?\d{3}[ -]?\d{2}(?!\d)")),
    ("[INN]", re.compile(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)")),
)


def anonymize_text(text: str) -> str:
    result = text
    for placeholder, pattern in PATTERNS:
        result = pattern.sub(placeholder, result)
    return result
