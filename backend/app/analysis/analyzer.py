from __future__ import annotations

from pathlib import Path

from app.documents.parser import parse_document
from app.domain.chunker import chunk_document
from app.domain.models import (
    AnalysisReport,
    CheckStatus,
    ChunkCheckResult,
    ContractChunk,
    RetrievedRegulation,
)
from app.domain.report_md import build_markdown_report
from app.domain.rules import check_required_terms, evaluate_hard_constraints
from app.domain.validation import validate_chunk_result
from app.knowledge.memory import KnowledgeBase
from app.llm.client import LLMClient, LLMResponseFormatError


class ContractAnalyzer:
    def __init__(
        self,
        knowledge_base: KnowledgeBase,
        llm_client: LLMClient,
        top_k: int = 3,
    ) -> None:
        self._knowledge_base = knowledge_base
        self._llm_client = llm_client
        self._top_k = top_k

    async def analyze(self, path: str | Path) -> AnalysisReport:
        document = parse_document(path)
        chunks = chunk_document(document)
        document_text = "\n".join(block.text for block in document.blocks)
        results: list[ChunkCheckResult] = []
        required_term_results = await self._check_document_requirements(
            chunks,
            document_text,
            results,
        )
        required_terms_by_chunk: dict[str, list[ChunkCheckResult]] = {}
        for result in required_term_results:
            required_terms_by_chunk.setdefault(result.chunk_id, []).append(result)

        for chunk in chunks:
            rule_evaluation = evaluate_hard_constraints(
                chunk=chunk,
                document_text=document_text,
                knowledge_base=self._knowledge_base,
            )
            rule_results = rule_evaluation.findings
            chunk_required_results = required_terms_by_chunk.get(chunk.chunk_id, [])
            results.extend(rule_results)
            if chunk_required_results:
                results.extend(chunk_required_results)

            regulations = self._knowledge_base.search(chunk.text, top_k=self._top_k)
            regulations = [
                item
                for item in regulations
                if item.regulation.article not in rule_evaluation.resolved_articles
            ]
            if not regulations:
                if not rule_evaluation.resolved_articles:
                    results.append(
                        ChunkCheckResult(
                            chunk_id=chunk.chunk_id,
                            status=CheckStatus.NOT_APPLICABLE,
                            comment=("Нормативная база пуста или релевантные нормы не найдены."),
                        )
                    )
                continue

            try:
                llm_results = await self._llm_client.check_chunk(chunk, regulations)
                results.extend(
                    validate_chunk_result(llm_result, chunk, regulations)
                    for llm_result in llm_results
                )
            except LLMResponseFormatError as error:
                results.append(
                    ChunkCheckResult(
                        chunk_id=chunk.chunk_id,
                        status=CheckStatus.ERROR,
                        comment=(
                            "Пункт не проверен: модель дважды вернула ответ "
                            "в некорректном формате. Повторите проверку."
                        ),
                        retrieval_score=regulations[0].similarity_score,
                        validation_notes=[f"{type(error).__name__}: {error}"],
                    )
                )
            except Exception as error:
                results.append(
                    ChunkCheckResult(
                        chunk_id=chunk.chunk_id,
                        status=CheckStatus.ERROR,
                        comment=(
                            "Пункт не проверен из-за технической ошибки LLM. Повторите проверку."
                        ),
                        retrieval_score=regulations[0].similarity_score,
                        validation_notes=[f"{type(error).__name__}: {error}"],
                    )
                )

        results.extend(required_terms_by_chunk.get("document", []))
        results = _deduplicate_results(results)

        markdown = build_markdown_report(document.filename, results)
        return AnalysisReport(
            filename=document.filename,
            supported_document=True,
            message="Анализ завершён.",
            chunks_total=len(chunks),
            results=results,
            markdown=markdown,
        )

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
            semantic_results = await checker(chunks, regulations)
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
                )
            )
            return deterministic_results

    def _required_term_regulations(self) -> list[RetrievedRegulation]:
        regulations: list[RetrievedRegulation] = []
        for article in ("57", "100"):
            regulations.extend(
                RetrievedRegulation(regulation=item, similarity_score=1.0)
                for item in self._knowledge_base.find_by_article(article)
            )
        return regulations


def _deduplicate_results(results: list[ChunkCheckResult]) -> list[ChunkCheckResult]:
    """Keep the first equivalent finding; deterministic rules are added first."""
    unique: list[ChunkCheckResult] = []
    seen: set[tuple[str, str, str, str]] = set()
    for result in results:
        if result.status in {CheckStatus.OK, CheckStatus.NOT_APPLICABLE, CheckStatus.ERROR}:
            unique.append(result)
            continue
        key = (
            result.chunk_id,
            " ".join(result.source.lower().split()),
            " ".join(result.contract_quote.lower().split()),
            " ".join(result.law_quote.lower().split()),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique
