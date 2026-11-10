from __future__ import annotations

import re

from .models import ParsedDocument

EMPLOYMENT_MARKERS = (
    "трудовой договор",
    "работодатель",
    "работник",
    "трудовая функция",
    "место работы",
    "оплата труда",
    "режим рабочего времени",
)


def is_supported_employment_contract(document: ParsedDocument) -> bool:
    text = " ".join(block.text for block in document.blocks).lower()
    marker_count = sum(marker in text for marker in EMPLOYMENT_MARKERS)
    has_numbered_sections = bool(re.search(r"(?:^|\s)\d+(?:\.\d+)+[.)]?\s", text))
    return "трудовой договор" in text and marker_count >= 3 and has_numbered_sections
