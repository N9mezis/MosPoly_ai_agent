from __future__ import annotations

import re
from dataclasses import dataclass

from .models import CheckStatus, ChunkCheckResult, ContractChunk, RegulationChunk
from .ports import ArticleLookup


@dataclass(frozen=True)
class HardConstraintEvaluation:
    """Deterministic findings and articles fully resolved for this chunk."""

    findings: list[ChunkCheckResult]
    resolved_articles: frozenset[str]


LAW_QUOTES = {
    "91": "Нормальная продолжительность рабочего времени не может превышать 40 часов в неделю.",
    "115": "Ежегодный основной оплачиваемый отпуск предоставляется работникам продолжительностью 28 календарных дней.",
    "136": "Заработная плата выплачивается не реже чем каждые полмесяца.",
    "70": "Срок испытания не может превышать трех месяцев, а для руководителей организаций и их заместителей, главных бухгалтеров и их заместителей, руководителей филиалов, представительств или иных обособленных структурных подразделений организаций - шести месяцев, если иное не установлено федеральным законом.",
    "100": "Режим рабочего времени должен предусматривать продолжительность рабочей недели",
}

REQUIRED_TERM_QUOTES = {
    "workplace": (
        "57",
        "Обязательными для включения в трудовой договор являются следующие условия: место работы",
    ),
    "job_function": (
        "57",
        "трудовая функция (работа по должности в соответствии со штатным расписанием, профессии, специальности с указанием квалификации; конкретный вид поручаемой работнику работы)",
    ),
    "salary": (
        "57",
        "условия оплаты труда (в том числе размер тарифной ставки или оклада (должностного оклада) работника, доплаты, надбавки и поощрительные выплаты)",
    ),
    "schedule": ("100", LAW_QUOTES["100"]),
}

NUMBER_WORDS = {
    "один": 1,
    "одного": 1,
    "два": 2,
    "двух": 2,
    "три": 3,
    "трех": 3,
    "трёх": 3,
    "четыре": 4,
    "четырех": 4,
    "четырёх": 4,
    "пять": 5,
    "пяти": 5,
    "шесть": 6,
    "шести": 6,
}

CLAUSE_ID_PATTERN = re.compile(r"^\s*\d+(?:\.\d+)+[.)]?\s*")
HOURS_PATTERN = re.compile(
    r"(?P<value>\d{1,3})\s*(?:-|\s)?час\w*\s+(?:рабоч\w+\s+)?недел\w*|(?P<value_alt>\d{1,3})\s+час\w*\s+в\s+недел\w*"
)
LEAVE_PATTERN = re.compile(
    r"ежегод\w*.*?оплачиваем\w*.*?(?P<value>\d{1,3})\s+календарн\w*\s+дн", re.DOTALL
)
MONTHLY_PAY_PATTERN = re.compile(
    r"заработн\w*\s+плат\w*.*?один\s+раз\s+в\s+месяц|один\s+раз\s+в\s+месяц.*?заработн\w*\s+плат",
    re.DOTALL,
)
PROBATION_PATTERN = re.compile(
    r"испыт\w*(?:\s+\w+){0,5}\s+(?P<value>\d+|один|одного|два|двух|три|трех|трёх|четыре|четырех|четырёх|пять|пяти|шесть|шести)\s+месяц\w*"
)
EMPLOYEE_POSITION_PATTERN = re.compile(
    r"принимает\s+работника\s+на\s+должность\s+(?P<position>[^.\n]{1,120})",
    re.IGNORECASE,
)
LEADERSHIP_POSITION_PATTERN = re.compile(
    r"руководител|директор|заместител|главн\w*\s+бухгалтер",
    re.IGNORECASE,
)
WORKPLACE_CONTEXT_PATTERN = re.compile(r"место\s+(?:работы|выполнения\s+работы)", re.IGNORECASE)
WORKPLACE_VAGUE_PATTERN = re.compile(
    r"место\s+(?:работы|выполнения\s+работы).*?"
    r"(?:не\s+указывается|определяется\s+работодателем|по\s+мере\s+необходимости)",
    re.IGNORECASE | re.DOTALL,
)
JOB_FUNCTION_VAGUE_PATTERN = re.compile(
    r"любые\s+поручения|конкретн\w*\s+вид.*?не\s+определяется",
    re.IGNORECASE | re.DOTALL,
)
SALARY_CONTEXT_PATTERN = re.compile(
    r"заработн\w*\s+плат\w*|оплат\w*\s+труд\w*|оклад\w*|вознагражден\w*",
    re.IGNORECASE,
)
SALARY_AMOUNT_PATTERN = re.compile(r"\b\d[\d\s]{0,12}\s*(?:рубл\w*|₽)", re.IGNORECASE)
SALARY_VAGUE_PATTERN = re.compile(
    r"конкретн\w*\s+размер\w*.*?не\s+устанавливается|"
    r"размер.*?(?:определяет\w*.*?работодател\w*|работодател\w*.*?определяет\w*)|"
    r"работодател\w*.*?определяет\w*.*?размер|"
    r"по\s+своему\s+усмотрению|"
    r"штатн\w*\s+расписан\w*.*?не\s+устанавливается",
    re.IGNORECASE | re.DOTALL,
)
SCHEDULE_CONTEXT_PATTERN = re.compile(
    r"режим\w*\s+работ\w*|рабоч\w*\s+(?:день|дни|недел\w*)|"
    r"врем\w*\s+работ\w*|график\w*|правил\w*\s+внутренн\w*\s+трудов\w*\s+распорядк\w*",
    re.IGNORECASE,
)
SCHEDULE_VAGUE_PATTERN = re.compile(
    r"работодател\w*\s+самостоятельно\s+определяет.*?"
    r"начал\w*\s+и\s+окончан\w*\s+рабоч\w*\s+дн|"
    r"изменит\w*\s+график.*?без\s+уведомления",
    re.IGNORECASE | re.DOTALL,
)


def _normalized_contains(container: str, quote: str) -> bool:
    normalized_container = " ".join(container.lower().split())
    normalized_quote = " ".join(quote.lower().split())
    return normalized_quote in normalized_container


def _regulation_for_quote(
    knowledge_base: ArticleLookup,
    article: str,
    law_quote: str,
) -> RegulationChunk | None:
    for regulation in knowledge_base.find_by_article(article):
        if _normalized_contains(regulation.text, law_quote):
            return regulation
    return None


def _sentence_with_match(text: str, pattern: re.Pattern[str]) -> str:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if pattern.search(sentence.lower()):
            return CLAUSE_ID_PATTERN.sub("", sentence).strip()
    return CLAUSE_ID_PATTERN.sub("", text).strip()


def _finding(
    chunk: ContractChunk,
    knowledge_base: ArticleLookup,
    article: str,
    rule_name: str,
    comment: str,
    pattern: re.Pattern[str],
) -> ChunkCheckResult | None:
    law_quote = LAW_QUOTES[article]
    regulation = _regulation_for_quote(knowledge_base, article, law_quote)
    if regulation is None:
        return None
    return ChunkCheckResult(
        chunk_id=chunk.chunk_id,
        status=CheckStatus.VIOLATION,
        source=regulation.citation,
        contract_quote=_sentence_with_match(chunk.text, pattern),
        law_quote=law_quote,
        comment=comment,
        validation_notes=[f"Детерминированное правило: {rule_name}"],
    )


def _number(value: str) -> int:
    return int(value) if value.isdigit() else NUMBER_WORDS[value]


def _required_term_finding(
    chunk: ContractChunk | None,
    knowledge_base: ArticleLookup,
    term: str,
    rule_name: str,
    comment: str,
) -> ChunkCheckResult | None:
    article, law_quote = REQUIRED_TERM_QUOTES[term]
    regulation = _regulation_for_quote(knowledge_base, article, law_quote)
    if regulation is None:
        return None
    return ChunkCheckResult(
        chunk_id=chunk.chunk_id if chunk else "document",
        status=CheckStatus.WARNING,
        source=regulation.citation,
        contract_quote=(CLAUSE_ID_PATTERN.sub("", chunk.text).strip() if chunk else ""),
        law_quote=law_quote,
        comment=comment,
        validation_notes=[f"Детерминированное правило всего договора: {rule_name}"],
    )


def _first_matching_chunk(
    chunks: list[ContractChunk],
    pattern: re.Pattern[str],
) -> ContractChunk | None:
    return next((chunk for chunk in chunks if pattern.search(chunk.text)), None)


def check_required_terms(
    chunks: list[ContractChunk],
    knowledge_base: ArticleLookup,
) -> list[ChunkCheckResult]:
    """Check required terms that can only be assessed across the whole contract."""
    findings: list[ChunkCheckResult] = []

    workplace_chunk = _first_matching_chunk(chunks, WORKPLACE_CONTEXT_PATTERN)
    if workplace_chunk is None or WORKPLACE_VAGUE_PATTERN.search(workplace_chunk.text):
        finding = _required_term_finding(
            workplace_chunk,
            knowledge_base,
            term="workplace",
            rule_name="missing_or_vague_workplace",
            comment=(
                "Место работы не указано или оставлено на усмотрение Работодателя. "
                "Это обязательное условие трудового договора."
            ),
        )
        if finding:
            findings.append(finding)

    vague_function_chunk = _first_matching_chunk(chunks, JOB_FUNCTION_VAGUE_PATTERN)
    has_position = any(EMPLOYEE_POSITION_PATTERN.search(chunk.text) for chunk in chunks)
    if vague_function_chunk is not None or not has_position:
        finding = _required_term_finding(
            vague_function_chunk,
            knowledge_base,
            term="job_function",
            rule_name="missing_or_vague_job_function",
            comment=(
                "Трудовая функция не определена достаточно конкретно. Нужно указать должность, "
                "профессию, специальность или конкретный вид поручаемой работы."
            ),
        )
        if finding:
            findings.append(finding)

    salary_chunks = [chunk for chunk in chunks if SALARY_CONTEXT_PATTERN.search(chunk.text)]
    vague_salary_chunk = next(
        (chunk for chunk in salary_chunks if SALARY_VAGUE_PATTERN.search(chunk.text)),
        None,
    )
    has_salary_amount = any(SALARY_AMOUNT_PATTERN.search(chunk.text) for chunk in salary_chunks)
    if vague_salary_chunk is not None or not has_salary_amount:
        finding = _required_term_finding(
            vague_salary_chunk or (salary_chunks[0] if salary_chunks else None),
            knowledge_base,
            term="salary",
            rule_name="missing_or_vague_salary_amount",
            comment=(
                "В договоре не указан конкретный размер тарифной ставки или оклада. "
                "Ссылки только на штатное расписание или будущее решение Работодателя недостаточно."
            ),
        )
        if finding:
            findings.append(finding)

    schedule_chunks = [chunk for chunk in chunks if SCHEDULE_CONTEXT_PATTERN.search(chunk.text)]
    vague_schedule_chunk = next(
        (chunk for chunk in schedule_chunks if SCHEDULE_VAGUE_PATTERN.search(chunk.text)),
        None,
    )
    if vague_schedule_chunk is not None or not schedule_chunks:
        finding = _required_term_finding(
            vague_schedule_chunk,
            knowledge_base,
            term="schedule",
            rule_name="missing_or_unilateral_work_schedule",
            comment=(
                "Режим работы не определён или может односторонне изменяться Работодателем. "
                "Нужно уточнить график или применимые правила внутреннего трудового распорядка."
            ),
        )
        if finding:
            findings.append(finding)

    return findings


def check_hard_constraints(
    chunk: ContractChunk,
    document_text: str,
    knowledge_base: ArticleLookup,
) -> list[ChunkCheckResult]:
    """Return deterministic violations (backward-compatible public helper)."""
    return evaluate_hard_constraints(chunk, document_text, knowledge_base).findings


def evaluate_hard_constraints(
    chunk: ContractChunk,
    document_text: str,
    knowledge_base: ArticleLookup,
) -> HardConstraintEvaluation:
    """Check exact limits and record articles that no longer need an LLM pass."""
    text = chunk.text.lower()
    findings: list[ChunkCheckResult] = []
    resolved_articles: set[str] = set()

    if MONTHLY_PAY_PATTERN.search(text):
        resolved_articles.add("136")
        finding = _finding(
            chunk,
            knowledge_base,
            article="136",
            rule_name="salary_once_per_month",
            comment=(
                "Договор устанавливает выплату заработной платы один раз в месяц, "
                "хотя она должна выплачиваться не реже чем каждые полмесяца."
            ),
            pattern=MONTHLY_PAY_PATTERN,
        )
        if finding:
            findings.append(finding)

    hours_match = HOURS_PATTERN.search(text)
    if hours_match:
        resolved_articles.add("91")
        hours = int(hours_match.group("value") or hours_match.group("value_alt"))
        if hours > 40:
            finding = _finding(
                chunk,
                knowledge_base,
                article="91",
                rule_name="weekly_hours_over_40",
                comment=(
                    f"Договор устанавливает {hours} часов работы в неделю, "
                    "что превышает нормальную продолжительность 40 часов."
                ),
                pattern=HOURS_PATTERN,
            )
            if finding:
                findings.append(finding)

    leave_match = LEAVE_PATTERN.search(text)
    if leave_match:
        resolved_articles.add("115")
        days = int(leave_match.group("value"))
        if days < 28:
            finding = _finding(
                chunk,
                knowledge_base,
                article="115",
                rule_name="annual_paid_leave_under_28_days",
                comment=(
                    f"Договор устанавливает ежегодный основной оплачиваемый отпуск "
                    f"продолжительностью {days} календарных дней вместо минимум 28 дней."
                ),
                pattern=LEAVE_PATTERN,
            )
            if finding:
                findings.append(finding)

    probation_match = PROBATION_PATTERN.search(text)
    if probation_match:
        resolved_articles.add("70")
        months = _number(probation_match.group("value"))
        position_match = EMPLOYEE_POSITION_PATTERN.search(document_text)
        position = position_match.group("position") if position_match else ""
        leadership_exception = bool(LEADERSHIP_POSITION_PATTERN.search(position))
        if months > 3 and not leadership_exception:
            finding = _finding(
                chunk,
                knowledge_base,
                article="70",
                rule_name="probation_over_3_months",
                comment=(
                    f"Для указанной должности установлен испытательный срок {months} месяцев, "
                    "хотя общий предельный срок составляет три месяца."
                ),
                pattern=PROBATION_PATTERN,
            )
            if finding:
                findings.append(finding)

    return HardConstraintEvaluation(
        findings=findings,
        resolved_articles=frozenset(resolved_articles),
    )
