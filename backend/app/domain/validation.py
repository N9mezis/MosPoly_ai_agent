from __future__ import annotations

import re

from .models import (
    CheckStatus,
    ChunkCheckResult,
    ContractChunk,
    LLMChunkResult,
    RetrievedRegulation,
)

NO_VIOLATION_COMMENT_PATTERN = re.compile(
    r"(?:"
    r"нарушени\w*\s+отсутств\w*|"
    r"не\s+явля\w*\s+нарушени\w*|"
    r"не\s+наруша\w*|"
    r"соответству\w*\s+(?:норм\w*|требовани\w*)|"
    r"услови\w*\s+законн\w*|"
    r"в\s+пределах\s+(?:допустим\w*|установленн\w*)"
    r")",
    re.IGNORECASE,
)

MISSING_TERM_COMMENT_PATTERN = re.compile(
    r"(?:"
    r"не\s+(?:указ\w*|упомин\w*|содерж\w*|предусмотр\w*|уточн\w*|устанавлива\w*|"
    r"определ\w*|конкретизир\w*|оговар\w*|гарантир\w*)|"
    r"лишь\s+на|только\s+на|"
    r"отсутству\w*\s+(?:информац\w*|сведен\w*|услови\w*|указан\w*)"
    r")",
    re.IGNORECASE,
)


PLACEHOLDER_ONLY = re.compile(r"^[\s\W]*(?:\[[A-Z_]+\][\s\W]*)+$")


def _only_placeholders(quote: str) -> bool:
    """«[PERSON]», «[PERSON], [PASSPORT]» — метки обезличивания, а не текст договора."""
    return bool(quote) and bool(PLACEHOLDER_ONLY.match(quote))


def _normalized_contains(container: str, quote: str) -> bool:
    normalized_container = " ".join(container.lower().split())
    normalized_quote = " ".join(quote.lower().split())
    return bool(normalized_quote) and normalized_quote in normalized_container


def validate_chunk_result(
    result: LLMChunkResult,
    chunk: ContractChunk,
    regulations: list[RetrievedRegulation],
    *,
    allow_warning: bool = False,
    allow_missing_contract_quote: bool = False,
) -> ChunkCheckResult:
    notes: list[str] = []
    status = result.status
    law_text = "\n".join(item.regulation.text for item in regulations)
    source = result.source
    regulation_chunk_id: str | None = None

    contract_quote_valid = _normalized_contains(chunk.text, result.contract_quote)
    law_quote_valid = _normalized_contains(law_text, result.law_quote)

    if law_quote_valid:
        matching_regulation = next(
            (
                item.regulation
                for item in regulations
                if _normalized_contains(item.regulation.text, result.law_quote)
            ),
            None,
        )
        if matching_regulation is not None:
            source = matching_regulation.citation
            regulation_chunk_id = matching_regulation.chunk_id

    if result.contract_quote and not contract_quote_valid:
        notes.append("Цитата договора отсутствует в проверяемом чанке")
    if result.law_quote and not law_quote_valid:
        notes.append("Цитата нормы отсутствует в найденных нормативных фрагментах")

    if status in {CheckStatus.VIOLATION, CheckStatus.WARNING} and _only_placeholders(
        result.contract_quote
    ):
        status = CheckStatus.NOT_APPLICABLE
        notes.append("Вывод скрыт: цитата договора состоит из меток обезличивания")

    if status == CheckStatus.WARNING and not allow_warning:
        status = CheckStatus.NOT_APPLICABLE
        notes.append("Чанковые предупреждения скрыты: они проверяются на уровне договора")

    if status == CheckStatus.VIOLATION:
        if NO_VIOLATION_COMMENT_PATTERN.search(result.comment):
            status = CheckStatus.NOT_APPLICABLE
            notes.append("Вывод скрыт: комментарий сам отрицает нарушение")
        elif MISSING_TERM_COMMENT_PATTERN.search(result.comment):
            status = CheckStatus.NOT_APPLICABLE
            notes.append(
                "Вывод скрыт: отсутствие условия проверяется для всего договора, "
                "а не как прямое противоречие отдельного пункта"
            )

    if status in {CheckStatus.VIOLATION, CheckStatus.WARNING}:
        contract_evidence_valid = contract_quote_valid or (
            allow_missing_contract_quote
            and chunk.chunk_id == "document"
            and not result.contract_quote
        )
        gates_passed = all(
            (
                source,
                result.comment,
                contract_evidence_valid,
                law_quote_valid,
            )
        )
        if not gates_passed:
            status = CheckStatus.NOT_APPLICABLE
            notes.append("Вывод скрыт из-за отсутствия точных подтверждающих цитат")

    top_score = regulations[0].similarity_score if regulations else None
    return ChunkCheckResult(
        chunk_id=chunk.chunk_id,
        status=status,
        source=source,
        contract_quote=result.contract_quote,
        law_quote=result.law_quote,
        comment=result.comment,
        recommendation=result.recommendation,
        retrieval_score=top_score,
        validation_notes=notes,
        regulation_chunk_id=regulation_chunk_id,
    )
