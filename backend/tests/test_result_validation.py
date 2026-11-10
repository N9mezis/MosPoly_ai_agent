import pytest

from app.domain.models import (
    CheckStatus,
    ContractChunk,
    LLMChunkResult,
    RegulationChunk,
    RetrievedRegulation,
)
from app.domain.validation import validate_chunk_result


def _regulation() -> RetrievedRegulation:
    return RetrievedRegulation(
        regulation=RegulationChunk(
            chunk_id="tk-57",
            source_id="tk",
            source_title="ТК РФ",
            article="57",
            text="Обязательными являются условия оплаты труда.",
        ),
        similarity_score=0.82,
    )


def test_keeps_supported_violation() -> None:
    chunk = ContractChunk(
        chunk_id="5.2",
        text="Оплата труда определяется работодателем.",
    )
    result = LLMChunkResult(
        chunk_id="5.2",
        status=CheckStatus.VIOLATION,
        source="ТК РФ, статья 57",
        contract_quote="Оплата труда определяется работодателем",
        law_quote="Обязательными являются условия оплаты труда",
        comment="Работодатель единолично определяет размер оплаты.",
    )

    validated = validate_chunk_result(result, chunk, [_regulation()])

    assert validated.status == CheckStatus.VIOLATION
    assert not validated.validation_notes


def test_hides_violation_with_invented_quote() -> None:
    chunk = ContractChunk(chunk_id="5.2", text="Указан оклад 80000 рублей.")
    result = LLMChunkResult(
        chunk_id="5.2",
        status=CheckStatus.VIOLATION,
        source="ТК РФ, статья 57",
        contract_quote="Оклад не указан",
        law_quote="Обязательными являются условия оплаты труда",
        comment="Нарушение.",
    )

    validated = validate_chunk_result(result, chunk, [_regulation()])

    assert validated.status == CheckStatus.NOT_APPLICABLE
    assert validated.validation_notes


def test_uses_canonical_source_for_matching_law_quote() -> None:
    chunk = ContractChunk(
        chunk_id="5.2",
        text="Оплата труда определяется работодателем.",
    )
    result = LLMChunkResult(
        chunk_id="5.2",
        status=CheckStatus.WARNING,
        source="ТК РФ",
        contract_quote="Оплата труда определяется работодателем",
        law_quote="Обязательными являются условия оплаты труда",
        comment="Не указан размер оклада.",
    )

    validated = validate_chunk_result(
        result,
        chunk,
        [_regulation()],
        allow_warning=True,
    )

    assert validated.source == "ТК РФ, статья 57"


def test_hides_chunk_warning_even_with_valid_quotes() -> None:
    chunk = ContractChunk(
        chunk_id="1.3",
        text="Дата начала работы: 05 октября 2026 года.",
    )
    result = LLMChunkResult(
        chunk_id="1.3",
        status=CheckStatus.WARNING,
        source="ТК РФ, статья 57",
        contract_quote="Дата начала работы: 05 октября 2026 года",
        law_quote="Обязательными являются условия оплаты труда",
        comment="Дата указана, но требует уточнения.",
    )

    validated = validate_chunk_result(result, chunk, [_regulation()])

    assert validated.status == CheckStatus.NOT_APPLICABLE


def test_allows_document_level_missing_term_warning() -> None:
    chunk = ContractChunk(chunk_id="document", text="Трудовой договор")
    result = LLMChunkResult(
        chunk_id="document",
        status=CheckStatus.WARNING,
        source="ТК РФ, статья 57",
        contract_quote="",
        law_quote="Обязательными являются условия оплаты труда",
        comment="В договоре отсутствует конкретный размер оклада.",
    )

    validated = validate_chunk_result(
        result,
        chunk,
        [_regulation()],
        allow_warning=True,
        allow_missing_contract_quote=True,
    )

    assert validated.status == CheckStatus.WARNING


@pytest.mark.parametrize(
    "comment",
    [
        "Договор соответствует норме, условие законное.",
        "Нарушение отсутствует, условие в пределах допустимого.",
        "Договор не упоминает обособленное подразделение.",
        "Договор не указывает минимальный отпуск для инвалидов.",
        "Отсутствует информация о форме расчётного листка.",
    ],
)
def test_hides_self_contradictory_or_missing_term_chunk_violation(comment: str) -> None:
    chunk = ContractChunk(
        chunk_id="5.2",
        text="Оплата труда определяется работодателем.",
    )
    result = LLMChunkResult(
        chunk_id="5.2",
        status=CheckStatus.VIOLATION,
        source="ТК РФ, статья 57",
        contract_quote="Оплата труда определяется работодателем",
        law_quote="Обязательными являются условия оплаты труда",
        comment=comment,
    )

    validated = validate_chunk_result(result, chunk, [_regulation()])

    assert validated.status == CheckStatus.NOT_APPLICABLE
    assert validated.validation_notes
