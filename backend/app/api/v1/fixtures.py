"""Фикстуры для эндпоинтов-заглушек: фронт может работать до готовности конвейера.

Удаляются по мере реализации настоящих эндпоинтов. Ответы-заглушки помечаются
заголовком `X-Stub: true`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from app.core.models import (
    AnalysisStatus,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    RegulationVersionStatus,
)

from .schemas import (
    ANALYSIS_STATUS_LABELS,
    CATEGORY_LABELS,
    AnalysisListItem,
    AnalysisResult,
    AnalysisStatusOut,
    AnalysisSummary,
    DocumentBlock,
    FindingOut,
    Highlight,
    RegulationChunkOut,
    RegulationRef,
    RegulationSourceOut,
    RegulationVersionOut,
    TechnicalIssue,
)

FIXTURE_ANALYSIS_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
_NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

TK = "Трудовой кодекс Российской Федерации"
_EDITION = date(2026, 5, 15)

_BLOCKS = [
    DocumentBlock(block_id="p1", text="ТРУДОВОЙ ДОГОВОР № [NUM]", page=1),
    DocumentBlock(
        block_id="p2",
        text="ООО «[ORG]», именуемое в дальнейшем «Работодатель», в лице генерального "
        "директора [PERSON_1], и [PERSON_2], именуемый в дальнейшем «Работник», "
        "заключили настоящий договор о нижеследующем.",
        page=1,
    ),
    DocumentBlock(block_id="p3", text="1. Предмет договора", page=1, clause="1"),
    DocumentBlock(
        block_id="p4",
        text="1.1. Работник принимается на должность бухгалтера в отдел учёта.",
        page=1,
        clause="1.1",
    ),
    DocumentBlock(block_id="p5", text="3. Оплата труда", page=1, clause="3"),
    DocumentBlock(
        block_id="p6",
        text="3.1. Работнику устанавливается должностной оклад в размере 80 000 рублей в месяц.",
        page=1,
        clause="3.1",
    ),
    DocumentBlock(
        block_id="p7",
        text="3.2. Заработная плата выплачивается один раз в месяц, 10 числа месяца, "
        "следующего за отработанным.",
        page=1,
        clause="3.2",
    ),
    DocumentBlock(block_id="p8", text="4. Режим рабочего времени и отдыха", page=2, clause="4"),
    DocumentBlock(
        block_id="p9",
        text="4.1. Работнику устанавливается пятидневная рабочая неделя продолжительностью "
        "45 часов.",
        page=2,
        clause="4.1",
    ),
    DocumentBlock(
        block_id="p10",
        text="4.3. Работнику предоставляется ежегодный оплачиваемый отпуск продолжительностью "
        "21 календарный день.",
        page=2,
        clause="4.3",
    ),
    DocumentBlock(block_id="p11", text="5. Испытание", page=2, clause="5"),
    DocumentBlock(
        block_id="p12",
        text="5.1. Работнику устанавливается испытательный срок продолжительностью 6 месяцев.",
        page=2,
        clause="5.1",
    ),
]


def _hl(block_id: str, quote: str) -> list[Highlight]:
    block = next(b for b in _BLOCKS if b.block_id == block_id)
    start = block.text.find(quote)
    return [Highlight(block_id=block_id, start=start, end=start + len(quote), page=block.page)]


def _finding(
    n: int,
    chunk_key: str,
    category: FindingCategory,
    status: FindingStatus,
    origin: FindingOrigin,
    article: str,
    title: str,
    block_id: str | None,
    contract_quote: str,
    law_quote: str,
    explanation: str,
    recommendation: str,
) -> FindingOut:
    return FindingOut(
        id=uuid.UUID(int=n),
        chunk_key=chunk_key,
        category=category,
        category_label=CATEGORY_LABELS[category],
        status=status,
        origin=origin,
        title=title,
        contract_quote=contract_quote,
        regulation=RegulationRef(source_title=TK, article=article, edition_date=_EDITION),
        law_quote=law_quote,
        explanation=explanation,
        recommendation=recommendation,
        highlights=_hl(block_id, contract_quote) if block_id else [],
    )


_FINDINGS = [
    _finding(
        1,
        "3.2",
        FindingCategory.CRITICAL,
        FindingStatus.VIOLATION,
        FindingOrigin.RULE,
        "136",
        "Зарплата выплачивается реже двух раз в месяц",
        "p7",
        "Заработная плата выплачивается один раз в месяц",
        "Заработная плата выплачивается не реже чем каждые полмесяца.",
        "Договор устанавливает выплату заработной платы один раз в месяц, что противоречит "
        "требованию о выплате не реже чем каждые полмесяца.",
        "Указать две даты выплаты в месяц с интервалом не более 15 календарных дней, "
        "например: «25 числа текущего месяца и 10 числа следующего месяца».",
    ),
    _finding(
        2,
        "4.1",
        FindingCategory.CRITICAL,
        FindingStatus.VIOLATION,
        FindingOrigin.RULE,
        "91",
        "Рабочая неделя длиннее 40 часов",
        "p9",
        "продолжительностью 45 часов",
        "Нормальная продолжительность рабочего времени не может превышать 40 часов в неделю.",
        "Договор устанавливает 45 часов работы в неделю, что превышает нормальную "
        "продолжительность 40 часов.",
        "Установить продолжительность рабочей недели не более 40 часов.",
    ),
    _finding(
        3,
        "4.3",
        FindingCategory.CRITICAL,
        FindingStatus.VIOLATION,
        FindingOrigin.RULE,
        "115",
        "Отпуск короче 28 календарных дней",
        "p10",
        "продолжительностью 21 календарный день",
        "Ежегодный основной оплачиваемый отпуск предоставляется работникам "
        "продолжительностью 28 календарных дней.",
        "Договор предоставляет отпуск 21 календарный день вместо минимальных 28.",
        "Указать продолжительность ежегодного основного оплачиваемого отпуска "
        "не менее 28 календарных дней.",
    ),
    _finding(
        4,
        "5.1",
        FindingCategory.CRITICAL,
        FindingStatus.VIOLATION,
        FindingOrigin.LLM_CHUNK,
        "70",
        "Испытательный срок больше трёх месяцев",
        "p12",
        "испытательный срок продолжительностью 6 месяцев",
        "Срок испытания не может превышать трех месяцев, а для руководителей организаций и их "
        "заместителей, главных бухгалтеров и их заместителей … — шести месяцев.",
        "Должность бухгалтера (не главного) не относится к исключениям, для неё испытание "
        "не может превышать трёх месяцев.",
        "Сократить испытательный срок до трёх месяцев или менее.",
    ),
    _finding(
        5,
        "document",
        FindingCategory.RECOMMENDED,
        FindingStatus.WARNING,
        FindingOrigin.LLM_DOCUMENT,
        "57",
        "Не указано место работы",
        None,
        "",
        "Обязательными для включения в трудовой договор являются следующие условия: место работы …",
        "В договоре не указано место работы (адрес или обособленное подразделение).",
        "Добавить пункт «Место работы: …» с наименованием и адресом работодателя или "
        "обособленного подразделения.",
    ),
    _finding(
        6,
        "1.1",
        FindingCategory.INFO,
        FindingStatus.WARNING,
        FindingOrigin.LLM_CHUNK,
        "57",
        "Трудовая функция описана кратко",
        "p4",
        "на должность бухгалтера в отдел учёта",
        "трудовая функция (работа по должности в соответствии со штатным расписанием, "
        "профессии, специальности с указанием квалификации; конкретный вид поручаемой работы)",
        "Должность указана, но без ссылки на штатное расписание и квалификацию.",
        "Сослаться на штатное расписание и должностную инструкцию.",
    ),
]


def fixture_result(analysis_id: uuid.UUID = FIXTURE_ANALYSIS_ID) -> AnalysisResult:
    return AnalysisResult(
        id=analysis_id,
        status=AnalysisStatus.COMPLETED,
        filename="problematic_01_multiple_violations.docx",
        document_type_id="employment-contract",
        created_at=_NOW,
        finished_at=_NOW + timedelta(seconds=41),
        is_partial=False,
        summary=AnalysisSummary(
            critical=4, recommended=1, info=1, technical_errors=1, chunks_total=9
        ),
        blocks=_BLOCKS,
        findings=_FINDINGS,
        technical_issues=[
            TechnicalIssue(
                chunk_key="6.2",
                message="Пункт не проверен: модель дважды вернула ответ в некорректном формате.",
            )
        ],
    )


def fixture_status(analysis_id: uuid.UUID = FIXTURE_ANALYSIS_ID) -> AnalysisStatusOut:
    return AnalysisStatusOut(
        id=analysis_id,
        status=AnalysisStatus.COMPLETED,
        status_label=ANALYSIS_STATUS_LABELS[AnalysisStatus.COMPLETED],
        stage="Готово",
        progress=1.0,
        created_at=_NOW,
        started_at=_NOW + timedelta(seconds=1),
        finished_at=_NOW + timedelta(seconds=41),
    )


def fixture_history() -> list[AnalysisListItem]:
    items = []
    statuses = [AnalysisStatus.COMPLETED, AnalysisStatus.ANALYZING, AnalysisStatus.FAILED]
    for i, status in enumerate(statuses):
        items.append(
            AnalysisListItem(
                id=FIXTURE_ANALYSIS_ID if i == 0 else uuid.UUID(int=100 + i),
                filename=[
                    "problematic_01_multiple_violations.docx",
                    "correct_01_accountant.docx",
                    "scan.pdf",
                ][i],
                document_type_id="employment-contract",
                status=status,
                status_label=ANALYSIS_STATUS_LABELS[status],
                summary=AnalysisSummary(critical=4, recommended=1, info=1, chunks_total=9)
                if i == 0
                else AnalysisSummary(),
                created_by_name="Администратор сервиса",
                created_at=_NOW - timedelta(hours=i),
                finished_at=_NOW if status is not AnalysisStatus.ANALYZING else None,
            )
        )
    return items


FIXTURE_VERSION_ID = uuid.UUID("00000000-0000-4000-8000-0000000000a1")


def fixture_regulations() -> list[RegulationSourceOut]:
    active = RegulationVersionOut(
        id=FIXTURE_VERSION_ID,
        source_id="tk_rf",
        label="Ключевые статьи (57, 70, 91, 100, 115, 136)",
        status=RegulationVersionStatus.ACTIVE,
        edition_date=_EDITION,
        chunks_count=14,
        embedding_model="Embeddings",
        uploaded_by_name="Администратор сервиса",
        activated_at=_NOW - timedelta(days=3),
        created_at=_NOW - timedelta(days=3),
    )
    archived = active.model_copy(
        update={
            "id": uuid.UUID("00000000-0000-4000-8000-0000000000a0"),
            "status": RegulationVersionStatus.ARCHIVED,
            "label": "Первая редакция",
            "chunks_count": 10,
            "created_at": _NOW - timedelta(days=30),
        }
    )
    return [
        RegulationSourceOut(
            id="tk_rf",
            title=TK,
            source_url="http://pravo.gov.ru/proxy/ips/?docbody=&nd=102074279",
            active_version_id=active.id,
            versions=[active, archived],
        )
    ]


def fixture_chunks() -> list[RegulationChunkOut]:
    return [
        RegulationChunkOut(
            id=uuid.UUID(int=1000),
            chunk_key="tk_rf_article_91_1",
            article="91",
            part="2",
            title="Понятие рабочего времени. Нормальная продолжительность рабочего времени",
            text="Нормальная продолжительность рабочего времени не может превышать 40 часов "
            "в неделю.",
        )
    ]
