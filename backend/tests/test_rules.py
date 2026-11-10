import pytest

from app.domain.models import CheckStatus, ContractChunk, RegulationChunk
from app.domain.rules import (
    LAW_QUOTES,
    REQUIRED_TERM_QUOTES,
    check_hard_constraints,
    check_required_terms,
    evaluate_hard_constraints,
)
from app.knowledge.memory import KnowledgeBase
from app.llm.embeddings import HashingEmbedder


def _knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        chunks=[
            RegulationChunk(
                chunk_id=f"tk-{article}",
                source_id="tk",
                source_title="Трудовой кодекс Российской Федерации",
                article=article,
                text=quote,
            )
            for article, quote in LAW_QUOTES.items()
        ],
        embedder=HashingEmbedder(),
    )


def _required_terms_knowledge_base() -> KnowledgeBase:
    return KnowledgeBase(
        chunks=[
            RegulationChunk(
                chunk_id=f"tk-required-{term}",
                source_id="tk",
                source_title="Трудовой кодекс Российской Федерации",
                article=article,
                text=quote,
            )
            for term, (article, quote) in REQUIRED_TERM_QUOTES.items()
        ],
        embedder=HashingEmbedder(),
    )


@pytest.mark.parametrize(
    ("chunk_text", "article"),
    [
        ("3.2 Заработная плата выплачивается один раз в месяц 20 числа.", "136"),
        ("4.1 Продолжительность рабочего времени составляет 45 часов в неделю.", "91"),
        (
            "4.3 Ежегодный основной оплачиваемый отпуск предоставляется "
            "продолжительностью 14 календарных дней.",
            "115",
        ),
        ("5.1 Работнику устанавливается испытательный срок шесть месяцев.", "70"),
    ],
)
def test_detects_direct_numeric_violation(chunk_text: str, article: str) -> None:
    chunk = ContractChunk(chunk_id="test", text=chunk_text)
    document_text = "Работодатель принимает Работника на должность специалиста отдела продаж."

    results = check_hard_constraints(chunk, document_text, _knowledge_base())

    assert len(results) == 1
    result = results[0]
    assert result.status == CheckStatus.VIOLATION
    assert result.source.endswith(f"статья {article}")
    assert result.contract_quote
    assert result.law_quote == LAW_QUOTES[article]


@pytest.mark.parametrize(
    "chunk_text",
    [
        "3.2 Заработная плата выплачивается 20 и 5 числа каждого месяца.",
        "4.1 Продолжительность рабочего времени составляет 40 часов в неделю.",
        "4.3 Ежегодный основной оплачиваемый отпуск составляет 28 календарных дней.",
        "5.1 Испытательный срок составляет три месяца.",
    ],
)
def test_does_not_flag_compliant_limits(chunk_text: str) -> None:
    chunk = ContractChunk(chunk_id="test", text=chunk_text)
    document_text = "Работодатель принимает Работника на должность специалиста."

    assert check_hard_constraints(chunk, document_text, _knowledge_base()) == []


@pytest.mark.parametrize(
    ("chunk_text", "article"),
    [
        ("4.1 Продолжительность работы 40 часов в неделю.", "91"),
        ("4.2 Ежегодный оплачиваемый отпуск 28 календарных дней.", "115"),
        ("7.1 Испытательный срок составляет три месяца.", "70"),
    ],
)
def test_marks_compliant_numeric_article_as_resolved(
    chunk_text: str,
    article: str,
) -> None:
    evaluation = evaluate_hard_constraints(
        ContractChunk(chunk_id="test", text=chunk_text),
        "Работодатель принимает Работника на должность специалиста.",
        _knowledge_base(),
    )

    assert evaluation.findings == []
    assert article in evaluation.resolved_articles


def test_allows_six_month_probation_for_director() -> None:
    chunk = ContractChunk(
        chunk_id="5.1",
        text="5.1 Работнику устанавливается испытательный срок шесть месяцев.",
    )
    document_text = "Работодатель принимает Работника на должность директора организации."

    assert check_hard_constraints(chunk, document_text, _knowledge_base()) == []


def test_detects_multiple_numeric_violations_in_one_chunk() -> None:
    chunk = ContractChunk(
        chunk_id="4.1",
        text=(
            "4.1 Продолжительность рабочего времени составляет 45 часов в неделю. "
            "Ежегодный основной оплачиваемый отпуск составляет 14 календарных дней."
        ),
    )

    results = check_hard_constraints(
        chunk,
        "Работодатель принимает Работника на должность специалиста.",
        _knowledge_base(),
    )

    assert {result.source.rsplit(" ", 1)[-1] for result in results} == {"91", "115"}


def test_required_terms_accepts_specific_contract_terms() -> None:
    chunks = [
        ContractChunk(
            chunk_id="1.1",
            text="1.1 Работодатель принимает Работника на должность бухгалтера.",
        ),
        ContractChunk(
            chunk_id="1.2",
            text="1.2 Работник ведет бухгалтерский учет и готовит отчетность.",
        ),
        ContractChunk(chunk_id="1.3", text="1.3 Место работы: г. Москва."),
        ContractChunk(
            chunk_id="3.1",
            text="3.1 Работнику устанавливается оклад 80 000 рублей в месяц.",
        ),
        ContractChunk(
            chunk_id="4.2",
            text=("4.2 Режим работы: пятидневная рабочая неделя; время работы с 9:00 до 18:00."),
        ),
    ]

    assert check_required_terms(chunks, _required_terms_knowledge_base()) == []


def test_required_terms_detects_vague_terms_in_relevant_chunks() -> None:
    chunks = [
        ContractChunk(
            chunk_id="1.1",
            text="1.1 Работодатель принимает Работника на должность специалиста.",
        ),
        ContractChunk(
            chunk_id="1.2",
            text=(
                "1.2 Работник выполняет любые поручения Работодателя. "
                "Конкретный вид поручаемой работы договором не определяется."
            ),
        ),
        ContractChunk(
            chunk_id="1.3",
            text="1.3 Место выполнения работы не указывается.",
        ),
        ContractChunk(
            chunk_id="3.1",
            text="3.1 Размер заработной платы определяет Работодатель.",
        ),
        ContractChunk(
            chunk_id="4.2",
            text=(
                "4.2 Работодатель самостоятельно определяет начало и окончание "
                "рабочего дня и может изменить график без уведомления."
            ),
        ),
    ]

    results = check_required_terms(chunks, _required_terms_knowledge_base())

    assert [(result.chunk_id, result.source.rsplit(" ", 1)[-1]) for result in results] == [
        ("1.3", "57"),
        ("1.2", "57"),
        ("3.1", "57"),
        ("4.2", "100"),
    ]
    assert all(result.status == CheckStatus.WARNING for result in results)
    assert all(result.contract_quote for result in results)


def test_required_terms_reports_terms_absent_from_document() -> None:
    chunks = [ContractChunk(chunk_id="intro", text="Трудовой договор")]

    results = check_required_terms(chunks, _required_terms_knowledge_base())

    assert len(results) == 4
    assert all(result.chunk_id == "document" for result in results)
    assert all(not result.contract_quote for result in results)
