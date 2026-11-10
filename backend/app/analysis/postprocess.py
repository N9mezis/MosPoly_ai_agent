"""Перевод результатов конвейера в замечания отчёта: категории, статьи, подсветка."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.models import FindingCategory, FindingStatus
from app.domain.models import CheckStatus, ChunkCheckResult, ContractChunk, TextBlock

ARTICLE_IN_SOURCE = re.compile(r"(?:стать[яи]|ст\.)\s*(\d{1,3}(?:\.\d{1,2})?)", re.IGNORECASE)

ARTICLE_TITLES = {
    "57": "Обязательные условия трудового договора",
    "70": "Испытательный срок",
    "91": "Продолжительность рабочего времени",
    "100": "Режим рабочего времени",
    "115": "Ежегодный оплачиваемый отпуск",
    "136": "Сроки выплаты заработной платы",
}

CATEGORY_ORDER = {
    FindingCategory.CRITICAL: 0,
    FindingCategory.RECOMMENDED: 1,
    FindingCategory.INFO: 2,
}


def article_from_source(source: str) -> str | None:
    match = ARTICLE_IN_SOURCE.search(source or "")
    return match.group(1) if match else None


def categorize(result: ChunkCheckResult) -> FindingCategory:
    """Ф-07: violation — критическая; отсутствующее обязательное условие — критическая;
    неконкретная формулировка — рекомендательная; прочее — информационная."""
    if result.status == CheckStatus.VIOLATION:
        return FindingCategory.CRITICAL
    if result.status == CheckStatus.WARNING:
        if result.chunk_id == "document" and not result.contract_quote:
            return FindingCategory.CRITICAL
        return FindingCategory.RECOMMENDED
    return FindingCategory.INFO


def finding_title(result: ChunkCheckResult, article: str | None) -> str:
    base = ARTICLE_TITLES.get(article or "", "")
    if result.chunk_id == "document" and not result.contract_quote:
        return f"{base}: условие отсутствует" if base else "Условие отсутствует"
    return base or (result.comment.split(".")[0][:80] if result.comment else "Замечание")


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


@dataclass(slots=True)
class HighlightSpan:
    block_id: str
    start: int
    end: int
    page: int | None


def locate_quote(
    quote: str, chunk: ContractChunk | None, blocks: dict[str, TextBlock]
) -> list[HighlightSpan]:
    """Находит цитату в блоках пункта (или всего документа) для подсветки в UI."""
    needle = _norm(quote)
    if len(needle) < 3:
        return []
    candidates = (
        [blocks[bid] for bid in chunk.block_ids if bid in blocks] if chunk else []
    ) or list(blocks.values())

    for block in candidates:
        position = block.text.lower().find(needle)
        if position >= 0:
            return [
                HighlightSpan(block.block_id, position, position + len(needle), block.page_number)
            ]

    # Цитата на несколько абзацев: подсвечиваем абзацы, целиком входящие в цитату,
    # и хвосты на границах.
    spans: list[HighlightSpan] = []
    for block in candidates:
        text = block.text.lower()
        if text and text in needle:
            spans.append(HighlightSpan(block.block_id, 0, len(block.text), block.page_number))
            continue
        head = needle[:40]
        tail = needle[-40:]
        if (pos := text.find(head)) >= 0:
            spans.append(HighlightSpan(block.block_id, pos, len(block.text), block.page_number))
        elif (pos := text.find(tail)) >= 0:
            spans.append(HighlightSpan(block.block_id, 0, pos + len(tail), block.page_number))
    return spans


def to_finding_status(status: CheckStatus) -> FindingStatus:
    return FindingStatus(status.value)


def is_reportable(result: ChunkCheckResult) -> bool:
    return result.status in (CheckStatus.VIOLATION, CheckStatus.WARNING)
