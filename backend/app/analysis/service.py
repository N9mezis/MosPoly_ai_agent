"""Жизненный цикл проверки: создание, выполнение в воркере, сохранение результата.

Инварианты:
- исходный файл удаляется сразу после извлечения текста (НФ-04);
- в БД пишется только обезличенный текст;
- технические сбои отделены от юридических замечаний; при сбое LLM сохраняются
  замечания правил, проверка помечается is_partial (частичный результат лучше отказа);
- снимок входа (версии нормативки, модели, промпты, параметры) — в analyses.snapshot (НФТ-7).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.service import log_event
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.core.models import (
    Analysis,
    AnalysisChunk,
    AnalysisStatus,
    CheckProfile,
    Document,
    DocumentType,
    Finding,
    FindingCitation,
    FindingOrigin,
    LLMCall,
    RegulationVersion,
    RegulationVersionStatus,
    Retrieval,
)
from app.core.security import CurrentUser
from app.documents.parser import parse_document
from app.domain.chunker import CLAUSE_PATTERN
from app.domain.classifier import is_supported_employment_contract
from app.domain.models import AnalysisReport, CheckStatus
from app.knowledge.embedding_cache import CachedEmbedder
from app.knowledge.rerank import Reranker
from app.knowledge.retrieval import HybridRetriever, KnowledgeBaseEmpty, RetrievalSettings
from app.llm import client as llm_prompts
from app.llm.calllog import start_call_log, stop_call_log
from app.llm.client import LLMClient
from app.llm.embeddings import AsyncEmbedder

from .analyzer import ContractAnalyzer, dedup_key
from .postprocess import (
    article_from_source,
    categorize,
    finding_title,
    is_reportable,
    locate_quote,
    to_finding_status,
)

logger = logging.getLogger(__name__)

STAGE_LABELS = {
    "queued": "В очереди",
    "extracting": "Извлечение текста",
    "analyzing": "Проверка пунктов",
    "saving": "Сохранение результата",
    "done": "Готово",
}


class AnalysisFailed(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(slots=True)
class PipelineDeps:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    llm: LLMClient
    embedder: AsyncEmbedder
    reranker: Reranker


# ============================================================ создание (API)


async def create_analysis(
    session: AsyncSession,
    *,
    user: CurrentUser,
    document_id: uuid.UUID,
    document_type_id: str,
    idempotency_key: str | None,
) -> tuple[Analysis, bool]:
    """Создаёт проверку. Возвращает (analysis, created); при повторе Idempotency-Key — прежнюю."""
    if idempotency_key:
        existing = await session.scalar(
            select(Analysis).where(
                Analysis.organization_id == user.organization_id,
                Analysis.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            return existing, False

    document = await session.get(Document, document_id)
    if (
        document is None
        or document.organization_id != user.organization_id
        or (
            document.uploaded_by != user.id
            and user.role.value not in ("org_admin", "service_admin")
        )
    ):
        raise NotFoundError("Документ не найден")
    if document.storage_key is None:
        raise ConflictError(
            "Файл этого документа уже обработан и удалён. Загрузите документ повторно.",
            code="document_already_processed",
        )
    already = await session.scalar(select(Analysis.id).where(Analysis.document_id == document_id))
    if already is not None:
        raise ConflictError(
            "Для этого документа проверка уже запущена.",
            code="analysis_exists",
            details={"analysis_id": str(already)},
        )

    document_type = await session.get(DocumentType, document_type_id)
    if document_type is None:
        raise NotFoundError("Неизвестный тип документа")
    if not document_type.is_enabled:
        raise AppError(
            "Проверка этого типа документов пока недоступна.",
            code="document_type_disabled",
            status_code=422,
        )
    profile = await session.scalar(
        select(CheckProfile).where(
            CheckProfile.document_type_id == document_type_id, CheckProfile.is_active
        )
    )

    analysis = Analysis(
        document_id=document.id,
        organization_id=user.organization_id,
        created_by=user.id,
        document_type_id=document_type_id,
        profile_id=profile.id if profile else None,
        status=AnalysisStatus.QUEUED,
        stage=STAGE_LABELS["queued"],
        idempotency_key=idempotency_key,
    )
    session.add(analysis)
    await session.flush()
    await log_event(
        session,
        actor=user,
        action="analysis.create",
        entity_type="analysis",
        entity_id=str(analysis.id),
        payload={"document_id": str(document.id), "document_type_id": document_type_id},
    )
    return analysis, True


# ============================================================ выполнение (воркер)


async def _set(sessionmaker, analysis_id: uuid.UUID, **values) -> None:
    async with sessionmaker() as session:
        await session.execute(update(Analysis).where(Analysis.id == analysis_id).values(**values))
        await session.commit()


def _purge_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Не удалось удалить временный файл %s", path.name)


def _prompt_hash(*parts: str) -> str:
    return hashlib.sha256("\n---\n".join(parts).encode("utf-8")).hexdigest()[:16]


async def run_analysis(deps: PipelineDeps, analysis_id: uuid.UUID) -> None:
    sessionmaker = deps.sessionmaker
    async with sessionmaker() as session:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None:
            logger.warning("Проверка %s не найдена", analysis_id)
            return
        if analysis.status not in (AnalysisStatus.QUEUED,):
            logger.info("Проверка %s уже в статусе %s", analysis_id, analysis.status.value)
            return
        document = await session.get(Document, analysis.document_id)
        profile = (
            await session.get(CheckProfile, analysis.profile_id) if analysis.profile_id else None
        )
        storage_key = document.storage_key if document else None
        original_filename = document.original_filename if document else ""
        profile_params = dict(profile.params) if profile else {}
        profile_id = profile.id if profile else None
        analysis.status = AnalysisStatus.EXTRACTING
        analysis.stage = STAGE_LABELS["extracting"]
        analysis.progress = 0.05
        analysis.attempt += 1
        analysis.started_at = datetime.now(UTC)
        analysis.heartbeat_at = datetime.now(UTC)
        await session.commit()

    try:
        # 1. Извлечение текста и немедленное удаление оригинала.
        if not storage_key:
            raise AnalysisFailed(
                "file_missing", "Исходный файл не найден. Загрузите документ повторно."
            )
        path = deps.settings.upload_tmp_dir / storage_key
        parsed = None
        try:
            parsed = parse_document(path)
        except Exception as error:
            raise AnalysisFailed(
                "parse_failed", "Файл не читается: он повреждён или защищён."
            ) from error
        finally:
            _purge_file(path)
            pages = {b.page_number for b in parsed.blocks if b.page_number} if parsed else set()
            async with sessionmaker() as session:
                await session.execute(
                    update(Document)
                    .where(Document.id == analysis.document_id)
                    .values(
                        storage_key=None, purged_at=datetime.now(UTC), page_count=len(pages) or None
                    )
                )
                await session.commit()
        parsed.filename = original_filename

        # 2. Тип документа (Ф-12).
        if not is_supported_employment_contract(parsed):
            raise AnalysisFailed(
                "not_employment_contract",
                "Документ не похож на трудовой договор. В первой версии проверяются только "
                "трудовые договоры.",
            )

        # 3. Снимок нормативки и поиск.
        settings = deps.settings
        retrieval_settings = RetrievalSettings(
            candidates=int(profile_params.get("candidates", settings.retrieval_candidates)),
            top_k=int(profile_params.get("top_k", settings.retrieval_top_k)),
            similarity_floor=float(
                profile_params.get("similarity_floor", settings.retrieval_similarity_floor)
            ),
            article_hints=dict(profile_params.get("article_hints", {})),
        )
        retriever = HybridRetriever(
            sessionmaker,
            CachedEmbedder(deps.embedder, sessionmaker),
            settings=retrieval_settings,
            reranker=deps.reranker,
        )
        try:
            await retriever.load(profile_id=profile_id, on_date=date.today())
        except KnowledgeBaseEmpty as error:
            raise AnalysisFailed("knowledge_base_empty", error.message) from error

        async with sessionmaker() as session:
            active_versions = [
                str(v)
                for v in await session.scalars(
                    select(RegulationVersion.id).where(
                        RegulationVersion.status == RegulationVersionStatus.ACTIVE
                    )
                )
            ]
        snapshot = {
            "regulation_versions": active_versions,
            "regulation_chunks": retriever.size,
            "profile_id": str(profile_id) if profile_id else None,
            "retrieval": {
                "candidates": retrieval_settings.candidates,
                "top_k": retrieval_settings.top_k,
                "similarity_floor": retrieval_settings.similarity_floor,
                "channels": sorted(retrieval_settings.channels),
            },
            "prompts": {
                "chunk_check": _prompt_hash(
                    llm_prompts.SYSTEM_PROMPT, llm_prompts.JSON_REPAIR_PROMPT
                ),
                "required_terms": _prompt_hash(
                    llm_prompts.REQUIRED_TERMS_SYSTEM_PROMPT,
                    llm_prompts.REQUIRED_TERMS_REPAIR_PROMPT,
                ),
            },
        }
        await _set(
            sessionmaker,
            analysis_id,
            status=AnalysisStatus.ANALYZING,
            stage=STAGE_LABELS["analyzing"],
            progress=0.1,
            heartbeat_at=datetime.now(UTC),
            llm_provider=getattr(deps.llm, "provider", "mock"),
            llm_model=getattr(deps.llm, "model_name", ""),
            embedding_model=deps.embedder.model_name,
            reranker=deps.reranker.name,
            snapshot=snapshot,
        )

        # 4. Проверка.
        async def progress(done: int, total: int) -> None:
            await _set(
                sessionmaker,
                analysis_id,
                chunks_total=total,
                chunks_done=done,
                progress=round(0.1 + 0.85 * done / max(total, 1), 3),
                stage=f"{STAGE_LABELS['analyzing']}: {done} из {total}",
                heartbeat_at=datetime.now(UTC),
            )

        analyzer = ContractAnalyzer(
            retriever,
            deps.llm,
            top_k=retrieval_settings.top_k,
            max_parallel=settings.llm_max_parallel,
            required_articles=tuple(profile_params.get("required_articles", ("57", "100"))),
        )
        call_log, token = start_call_log()
        try:
            report = await analyzer.analyze_document(parsed, progress=progress)
        finally:
            stop_call_log(token)

        # 5. Сохранение.
        await _set(sessionmaker, analysis_id, stage=STAGE_LABELS["saving"], progress=0.97)
        await _persist(sessionmaker, analysis_id, report, retriever, call_log.records)
    except AnalysisFailed as failure:
        await _set(
            sessionmaker,
            analysis_id,
            status=AnalysisStatus.FAILED,
            stage="Ошибка обработки",
            error_code=failure.code,
            error_message=failure.message,
            finished_at=datetime.now(UTC),
        )
        logger.info("Проверка %s: %s", analysis_id, failure.code)
    except Exception as error:
        logger.exception("Проверка %s упала", analysis_id)
        await _set(
            sessionmaker,
            analysis_id,
            status=AnalysisStatus.FAILED,
            stage="Ошибка обработки",
            error_code="internal_error",
            error_message=(
                "Внутренняя ошибка при обработке документа. Повторите попытку позже "
                f"({type(error).__name__})."
            ),
            finished_at=datetime.now(UTC),
        )


def _clause_of(text: str) -> str | None:
    match = CLAUSE_PATTERN.match(text)
    return match.group("id") if match else None


async def _persist(
    sessionmaker,
    analysis_id: uuid.UUID,
    report: AnalysisReport,
    retriever: HybridRetriever,
    call_records,
) -> None:
    by_key = {chunk.chunk_id: chunk for chunk in retriever.chunks}
    blocks = {block.block_id: block for block in report.blocks}
    chunks_by_key = {chunk.chunk_id: chunk for chunk in report.chunks}

    async with sessionmaker() as session:
        analysis = await session.get(Analysis, analysis_id)
        if analysis is None or analysis.status is AnalysisStatus.CANCELLED:
            return
        analysis.document_blocks = [
            {
                "block_id": block.block_id,
                "text": block.text,
                "page": block.page_number,
                "clause": _clause_of(block.text),
            }
            for block in report.blocks
        ]

        chunk_rows: dict[str, AnalysisChunk] = {}
        for ordinal, chunk in enumerate(report.chunks):
            row = AnalysisChunk(
                analysis_id=analysis_id,
                chunk_key=chunk.chunk_id,
                ordinal=ordinal,
                text=chunk.text,
                char_length=len(chunk.text),
                block_ids=chunk.block_ids,
                page_numbers=chunk.page_numbers,
            )
            session.add(row)
            chunk_rows[chunk.chunk_id] = row
        await session.flush()

        counts = {"critical": 0, "recommended": 0, "info": 0, "technical_errors": 0}
        for result in report.results:
            store = (
                is_reportable(result)
                or result.status == CheckStatus.ERROR
                or (
                    result.status == CheckStatus.NOT_APPLICABLE
                    and result.validation_notes
                    and result.origin.startswith("llm")
                )
            )
            if not store:
                continue
            regulation = by_key.get(result.regulation_chunk_id or "")
            article = (regulation.article if regulation else None) or article_from_source(
                result.source
            )
            category = categorize(result)
            published = is_reportable(result)
            if result.status == CheckStatus.ERROR:
                counts["technical_errors"] += 1
            elif published:
                counts[category.value] += 1
            chunk = chunks_by_key.get(result.chunk_id)
            highlights = [
                {"block_id": s.block_id, "start": s.start, "end": s.end, "page": s.page}
                for s in (locate_quote(result.contract_quote, chunk, blocks) if published else [])
            ]
            finding = Finding(
                analysis_id=analysis_id,
                chunk_id=chunk_rows[result.chunk_id].id if result.chunk_id in chunk_rows else None,
                chunk_key=result.chunk_id,
                origin=FindingOrigin(result.origin),
                rule_id=result.rule_id,
                status=to_finding_status(result.status),
                category=category,
                article=article,
                source_label=finding_title(result, article),
                source_edition=regulation.edition_date or "" if regulation else "",
                contract_quote=result.contract_quote,
                law_quote=result.law_quote,
                comment=result.comment,
                recommendation=result.recommendation,
                highlights=highlights,
                retrieval_score=result.retrieval_score,
                is_published=published,
                validation_notes=result.validation_notes,
                dedup_key=hashlib.sha1("|".join(dedup_key(result)).encode()).hexdigest()
                if published
                else uuid.uuid4().hex,
            )
            session.add(finding)
            if regulation is not None and regulation.db_id and published:
                await session.flush()
                session.add(
                    FindingCitation(
                        finding_id=finding.id, regulation_chunk_id=uuid.UUID(regulation.db_id)
                    )
                )

        for chunk_key, items in report.retrievals.items():
            row = chunk_rows.get(chunk_key)
            if row is None:
                continue
            for item in items:
                if not item.regulation.db_id:
                    continue
                trace = item.trace
                session.add(
                    Retrieval(
                        analysis_id=analysis_id,
                        chunk_id=row.id,
                        regulation_chunk_id=uuid.UUID(item.regulation.db_id),
                        rank=int(trace.get("rank", 0)),
                        channels=list(trace.get("channels", [])),
                        vector_score=trace.get("vector_score"),
                        lexical_score=trace.get("lexical_score"),
                        fused_score=trace.get("fused_score"),
                        rerank_score=trace.get("rerank_score"),
                        was_sent_to_llm=True,
                    )
                )

        for record in call_records:
            row = chunk_rows.get(record.chunk_key or "")
            session.add(
                LLMCall(
                    analysis_id=analysis_id,
                    chunk_id=row.id if row else None,
                    purpose=record.purpose,
                    provider=record.provider,
                    model=record.model,
                    attempt=record.attempt,
                    used_json_schema=record.used_json_schema,
                    prompt_tokens=record.prompt_tokens,
                    completion_tokens=record.completion_tokens,
                    latency_ms=record.latency_ms,
                    http_status=record.http_status,
                    outcome=record.outcome,
                    error_message=record.error_message,
                )
            )

        llm_chunk_errors = counts["technical_errors"]
        analysis.summary = {**counts, "chunks_total": report.chunks_total}
        analysis.chunks_total = report.chunks_total
        analysis.chunks_done = report.chunks_total
        analysis.is_partial = llm_chunk_errors > 0
        analysis.status = AnalysisStatus.COMPLETED
        analysis.stage = STAGE_LABELS["done"]
        analysis.progress = 1.0
        analysis.finished_at = datetime.now(UTC)
        await session.commit()


# ============================================================ сторож


async def recover_stale(
    sessionmaker, *, stale_after: timedelta = timedelta(minutes=5), max_attempts: int = 3
) -> list[uuid.UUID]:
    """Находит проверки, у которых умер воркер. Возвращает id для повторной постановки."""
    threshold = datetime.now(UTC) - stale_after
    requeue: list[uuid.UUID] = []
    async with sessionmaker() as session:
        stale = list(
            await session.scalars(
                select(Analysis).where(
                    Analysis.status.in_([AnalysisStatus.EXTRACTING, AnalysisStatus.ANALYZING]),
                    Analysis.heartbeat_at < threshold,
                )
            )
        )
        for analysis in stale:
            document = await session.get(Document, analysis.document_id)
            if document and document.storage_key and analysis.attempt < max_attempts:
                analysis.status = AnalysisStatus.QUEUED
                analysis.stage = STAGE_LABELS["queued"]
                requeue.append(analysis.id)
            else:
                analysis.status = AnalysisStatus.FAILED
                analysis.stage = "Ошибка обработки"
                analysis.error_code = "worker_lost"
                analysis.error_message = (
                    "Обработка прервана из-за перезапуска сервиса. Загрузите документ повторно."
                )
                analysis.finished_at = datetime.now(UTC)
        await session.commit()
    return requeue
