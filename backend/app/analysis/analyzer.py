"""Оркестратор проверки одного документа (чистая логика конвейера без БД).

Порядок: обезличивание блоков → чанкирование → проверка полноты всего договора →
по каждому пункту (параллельно, с ограничением): правила → поиск норм → LLM →
проверка цитат → дедупликация.

`knowledge_base` — любой объект с `search(query, top_k)` (sync или async) и
`find_by_article(article)`: in-memory база в тестах или `HybridRetriever` из БД.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path

from app.documents.parser import parse_document
from app.domain.anonymizer import anonymize_text
from app.domain.chunker import chunk_document
from app.domain.models import (
    AnalysisReport,
    CheckStatus,
    ChunkCheckResult,
    ContractChunk,
    ParsedDocument,
    RetrievedRegulation,
    TextBlock,
)
from app.domain.report_md import build_markdown_report
from app.domain.rules import check_required_terms, evaluate_hard_constraints
from app.domain.validation import validate_chunk_result
from app.llm.calllog import set_current_chunk
from app.llm.client import LLMClient, LLMResponseFormatError

ProgressCallback = Callable[[int, int], Awaitable[None]]


def anonymize_document(document: ParsedDocument) -> ParsedDocument:
    """Единственная точка, где сырой текст превращается в обезличенный (Р-7)."""
    return ParsedDocument(
        filename=document.filename,
        blocks=[
            TextBlock(
                block_id=block.block_id,
                text=anonymize_text(block.text),
                page_number=block.page_number,
            )
            for block in document.blocks
        ],
    )


class ContractAnalyzer:
    def __init__(
        self,
        knowledge_base,
        llm_client: LLMClient,
        top_k: int = 3,
        *,
        max_parallel: int = 5,
        required_articles: tuple[str, ...] = ("57", "100"),
    ) -> None:
        self._knowledge_base = knowledge_base
        self._llm_client = llm_client
        self._top_k = top_k
        self._max_parallel = max(1, max_parallel)
        self._required_articles = required_articles

    async def analyze(self, path: str | Path) -> AnalysisReport:
        return await self.analyze_document(parse_document(path))

    async def _search(self, query: str) -> list[RetrievedRegulation]:
        result = self._knowledge_base.search(query, top_k=self._top_k)
        if inspect.isawaitable(result):
            result = await result
        return list(result)

    async def analyze_document(
        self,
        document: ParsedDocument,
        *,
        progress: ProgressCallback | None = None,
    ) -> AnalysisReport:
        document = anonymize_document(document)
        chunks = chunk_document(document)
        document_text = "\n".join(block.text for block in document.blocks)
        set_context = getattr(self._knowledge_base, "set_document_context", None)
        if set_context is not None:
            set_context(document_text)
        technical: list[ChunkCheckResult] = []
        required_term_results = await self._check_document_requirements(
            chunks, document_text, technical
        )
        required_by_chunk: dict[str, list[ChunkCheckResult]] = {}
        for result in required_term_results:
            required_by_chunk.setdefault(result.chunk_id, []).append(result)

        semaphore = asyncio.Semaphore(self._max_parallel)
        done = 0
        lock = asyncio.Lock()
        retrievals: dict[str, list[RetrievedRegulation]] = {}

        async def run(chunk: ContractChunk) -> list[ChunkCheckResult]:
            nonlocal done
            async with semaphore:
                token = set_current_chunk(chunk.chunk_id)
                try:
                    results = await self._check_chunk(chunk, document_text, retrievals)
                finally:
                    set_current_chunk(None)
                    del token
            if progress is not None:
                async with lock:
                    done += 1
                    await progress(done, len(chunks))
            return results + required_by_chunk.get(chunk.chunk_id, [])

        per_chunk = await asyncio.gather(*(run(chunk) for chunk in chunks))
        results = technical + [item for chunk_results in per_chunk for item in chunk_results]
        results.extend(required_by_chunk.get("document", []))
        results = _deduplicate_results(results)

        return AnalysisReport(
            filename=document.filename,
            supported_document=True,
            message="Анализ завершён.",
            chunks_total=len(chunks),
            results=results,
            markdown=build_markdown_report(document.filename, results),
            blocks=document.blocks,
            chunks=chunks,
            retrievals=retrievals,
        )

    async def _check_chunk(
        self,
        chunk: ContractChunk,
        document_text: str,
        retrievals: dict[str, list[RetrievedRegulation]],
    ) -> list[ChunkCheckResult]:
        results: list[ChunkCheckResult] = []
        rule_evaluation = evaluate_hard_constraints(
            chunk=chunk,
            document_text=document_text,
            knowledge_base=self._knowledge_base,
        )
        results.extend(rule_evaluation.findings)

        found = await self._search(chunk.text)
        retrievals[chunk.chunk_id] = found
        regulations = [
            item
            for item in found
            if item.regulation.article not in rule_evaluation.resolved_articles
        ]
        if not regulations:
            if not rule_evaluation.resolved_articles:
                results.append(
                    ChunkCheckResult(
                        chunk_id=chunk.chunk_id,
                        status=CheckStatus.NOT_APPLICABLE,
                        comment="Релевантные нормы не найдены.",
                        origin="llm_chunk",
                    )
                )
            return results

        try:
            llm_results = await self._llm_client.check_chunk(chunk, regulations)
            rule_quotes = [
                _norm(item.contract_quote)
                for item in rule_evaluation.findings
                if item.contract_quote
            ]
            for llm_result in llm_results:
                checked = validate_chunk_result(llm_result, chunk, regulations)
                checked.origin = "llm_chunk"
                if checked.status in (CheckStatus.VIOLATION, CheckStatus.WARNING) and _overlaps(
                    _norm(checked.contract_quote), rule_quotes
                ):
                    # Ту же фразу уже квалифицировало детерминированное правило: модель,
                    # не видя «занятой» статьи, склонна подбирать неприменимую соседнюю норму.
                    checked.status = CheckStatus.NOT_APPLICABLE
                    checked.validation_notes.append(
                        "Скрыто: эту формулировку уже квалифицировало правило"
                    )
                results.append(checked)
        except LLMResponseFormatError as error:
            results.append(
                _technical_error(
                    chunk.chunk_id,
                    "Пункт не проверен: модель дважды вернула ответ в некорректном формате.",
                    error,
                    regulations,
                )
            )
        except Exception as error:
            results.append(
                _technical_error(
                    chunk.chunk_id,
                    "Пункт не проверен из-за технической ошибки языковой модели.",
                    error,
                    regulations,
                )
            )
        return results

    async def _check_document_requirements(
        self,
        chunks: list[ContractChunk],
        document_text: str,
        technical_results: list[ChunkCheckResult],
    ) -> list[ChunkCheckResult]:
        deterministic_results = check_required_terms(chunks, self._knowledge_base)
        checker = getattr(self._llm_client, "check_required_terms", None)
        if checker is None or len(document_text) > 30_000:
            return deterministic_results

        regulations = self._required_term_regulations()
        if not regulations:
            return deterministic_results
        try:
            token = set_current_chunk("document")
            try:
                semantic_results = await checker(chunks, regulations)
            finally:
                set_current_chunk(None)
                del token
            if semantic_results is None:
                return deterministic_results
            chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
            document_chunk = ContractChunk(chunk_id="document", text=document_text)
            validated: list[ChunkCheckResult] = []
            for result in semantic_results:
                target_chunk = chunks_by_id.get(result.chunk_id, document_chunk)
                checked = validate_chunk_result(
                    result,
                    target_chunk,
                    regulations,
                    allow_warning=True,
                    allow_missing_contract_quote=True,
                )
                checked.origin = "llm_document"
                if checked.status == CheckStatus.VIOLATION:
                    checked.status = CheckStatus.WARNING
                    checked.validation_notes.append("Проверка полноты не создаёт прямое нарушение")
                validated.append(checked)
            return validated
        except Exception as error:
            technical_results.append(
                ChunkCheckResult(
                    chunk_id="document",
                    status=CheckStatus.ERROR,
                    comment=(
                        "Семантическую проверку полноты выполнить не удалось. "
                        "Применены базовые правила."
                    ),
                    validation_notes=[f"{type(error).__name__}: {error}"],
                    origin="llm_document",
                )
            )
            return deterministic_results

    def _required_term_regulations(self) -> list[RetrievedRegulation]:
        regulations: list[RetrievedRegulation] = []
        for article in self._required_articles:
            regulations.extend(
                RetrievedRegulation(regulation=item, similarity_score=1.0)
                for item in self._knowledge_base.find_by_article(article)
            )
        return regulations


def _technical_error(
    chunk_id: str,
    comment: str,
    error: Exception,
    regulations: list[RetrievedRegulation],
) -> ChunkCheckResult:
    return ChunkCheckResult(
        chunk_id=chunk_id,
        status=CheckStatus.ERROR,
        comment=comment + " Повторите проверку.",
        retrieval_score=regulations[0].similarity_score if regulations else None,
        validation_notes=[f"{type(error).__name__}: {error}"],
        origin="llm_chunk",
    )


def _deduplicate_results(results: list[ChunkCheckResult]) -> list[ChunkCheckResult]:
    """Keep the first equivalent finding; deterministic rules are added first."""
    unique: list[ChunkCheckResult] = []
    seen: set[tuple[str, str, str, str]] = set()
    for result in results:
        if result.status in {CheckStatus.OK, CheckStatus.NOT_APPLICABLE, CheckStatus.ERROR}:
            unique.append(result)
            continue
        key = dedup_key(result)
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique


def dedup_key(result: ChunkCheckResult) -> tuple[str, str, str, str]:
    return (
        result.chunk_id,
        " ".join(result.source.lower().split()),
        " ".join(result.contract_quote.lower().split()),
        " ".join(result.law_quote.lower().split()),
    )


def _norm(text: str) -> str:
    return " ".join(text.lower().replace("ё", "е").split()).strip(" .;:")


def _overlaps(quote: str, others: list[str]) -> bool:
    """Цитаты пересекаются, если одна содержит другую (или совпадают)."""
    if len(quote) < 8:
        return False
    return any(other and (quote in other or other in quote) for other in others)
