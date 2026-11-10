"""Чтение проверок для API и отчётов. `load_analysis_result` — точка входа для отчётов (агент B)."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    ANALYSIS_STATUS_LABELS,
    CATEGORY_LABELS,
    AnalysisListItem,
    AnalysisResult,
    AnalysisStatusOut,
    AnalysisSummary,
    DocumentBlock,
    FindingOut,
    Highlight,
    Page,
    RegulationRef,
    TechnicalIssue,
)
from app.core.errors import ConflictError, NotFoundError
from app.core.models import (
    Analysis,
    AnalysisStatus,
    Document,
    Finding,
    FindingCitation,
    FindingStatus,
    RegulationChunk,
    RegulationSource,
    RegulationVersion,
    User,
    UserRole,
)
from app.core.security import CurrentUser, can_read_analysis

from .postprocess import CATEGORY_ORDER


async def get_analysis_for_user(
    session: AsyncSession, analysis_id: uuid.UUID, user: CurrentUser
) -> Analysis:
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or not can_read_analysis(
        user, organization_id=analysis.organization_id, created_by=analysis.created_by
    ):
        raise NotFoundError("Проверка не найдена")
    return analysis


def status_out(analysis: Analysis) -> AnalysisStatusOut:
    return AnalysisStatusOut(
        id=analysis.id,
        status=analysis.status,
        status_label=ANALYSIS_STATUS_LABELS[analysis.status],
        stage=analysis.stage,
        progress=analysis.progress,
        error_code=analysis.error_code,
        error_message=analysis.error_message,
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        finished_at=analysis.finished_at,
    )


def _summary(analysis: Analysis) -> AnalysisSummary:
    data = analysis.summary or {}
    return AnalysisSummary(
        critical=data.get("critical", 0),
        recommended=data.get("recommended", 0),
        info=data.get("info", 0),
        technical_errors=data.get("technical_errors", 0),
        chunks_total=data.get("chunks_total", analysis.chunks_total),
    )


def _date(value) -> date | None:
    if value is None:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value))


async def load_analysis_result(
    session: AsyncSession, analysis_id: uuid.UUID, user: CurrentUser
) -> AnalysisResult:
    analysis = await get_analysis_for_user(session, analysis_id, user)
    if analysis.status is not AnalysisStatus.COMPLETED:
        raise ConflictError(
            "Проверка ещё не завершена"
            if analysis.status not in (AnalysisStatus.FAILED, AnalysisStatus.CANCELLED)
            else analysis.error_message or "Проверка завершилась ошибкой",
            code="analysis_not_completed",
            details={"status": analysis.status.value},
        )
    document = await session.get(Document, analysis.document_id)

    findings = list(
        await session.scalars(select(Finding).where(Finding.analysis_id == analysis_id))
    )
    citations = {
        finding_id: (chunk, version, source)
        for finding_id, chunk, version, source in await session.execute(
            select(FindingCitation.finding_id, RegulationChunk, RegulationVersion, RegulationSource)
            .join(RegulationChunk, RegulationChunk.id == FindingCitation.regulation_chunk_id)
            .join(RegulationVersion, RegulationVersion.id == RegulationChunk.version_id)
            .join(RegulationSource, RegulationSource.id == RegulationVersion.source_id)
            .where(FindingCitation.finding_id.in_([f.id for f in findings] or [uuid.uuid4()]))
        )
    }

    published: list[FindingOut] = []
    technical: list[TechnicalIssue] = []
    for finding in findings:
        if finding.status is FindingStatus.ERROR:
            technical.append(TechnicalIssue(chunk_key=finding.chunk_key, message=finding.comment))
            continue
        if not finding.is_published:
            continue
        cited = citations.get(finding.id)
        if cited:
            chunk, version, source = cited
            regulation = RegulationRef(
                source_title=source.title,
                article=chunk.article,
                part=chunk.part,
                edition_date=version.edition_date,
                effective_from=version.effective_from,
                effective_to=version.effective_to,
                url=source.source_url,
            )
        else:
            regulation = RegulationRef(
                source_title="Трудовой кодекс Российской Федерации",
                article=finding.article,
                edition_date=_date(finding.source_edition or None),
            )
        published.append(
            FindingOut(
                id=finding.id,
                chunk_key=finding.chunk_key,
                category=finding.category,
                category_label=CATEGORY_LABELS[finding.category],
                status=finding.status,
                origin=finding.origin,
                title=finding.source_label,
                contract_quote=finding.contract_quote,
                regulation=regulation,
                law_quote=finding.law_quote,
                explanation=finding.comment,
                recommendation=finding.recommendation,
                highlights=[Highlight(**item) for item in finding.highlights],
            )
        )

    def position(item: FindingOut) -> tuple:
        first = item.highlights[0] if item.highlights else None
        block_order = next(
            (
                i
                for i, b in enumerate(analysis.document_blocks)
                if first and b["block_id"] == first.block_id
            ),
            10_000,
        )
        return (CATEGORY_ORDER[item.category], block_order, item.chunk_key)

    published.sort(key=position)
    return AnalysisResult(
        id=analysis.id,
        status=analysis.status,
        filename=document.original_filename if document else "",
        document_type_id=analysis.document_type_id,
        created_at=analysis.created_at,
        finished_at=analysis.finished_at,
        is_partial=analysis.is_partial,
        summary=_summary(analysis),
        blocks=[DocumentBlock(**block) for block in analysis.document_blocks],
        findings=published,
        technical_issues=technical,
    )


async def list_history(
    session: AsyncSession,
    user: CurrentUser,
    *,
    status: AnalysisStatus | None,
    page: int,
    page_size: int,
) -> Page[AnalysisListItem]:
    query = (
        select(Analysis, Document.original_filename, User.full_name)
        .join(Document, Document.id == Analysis.document_id)
        .outerjoin(User, User.id == Analysis.created_by)
    )
    if user.role is UserRole.SERVICE_ADMIN:
        pass
    elif user.role is UserRole.ORG_ADMIN:
        query = query.where(Analysis.organization_id == user.organization_id)
    else:
        query = query.where(
            Analysis.organization_id == user.organization_id, Analysis.created_by == user.id
        )
    if status is not None:
        query = query.where(Analysis.status == status)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.execute(
        query.order_by(Analysis.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    items = [
        AnalysisListItem(
            id=analysis.id,
            filename=filename,
            document_type_id=analysis.document_type_id,
            status=analysis.status,
            status_label=ANALYSIS_STATUS_LABELS[analysis.status],
            summary=_summary(analysis),
            created_by_name=full_name or "",
            created_at=analysis.created_at,
            finished_at=analysis.finished_at,
        )
        for analysis, filename, full_name in rows
    ]
    return Page(items=items, total=int(total or 0), page=page, page_size=page_size)


__all__ = [
    "get_analysis_for_user",
    "list_history",
    "load_analysis_result",
    "status_out",
]
