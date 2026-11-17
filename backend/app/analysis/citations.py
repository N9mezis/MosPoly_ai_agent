"""Read frozen citations and compare their text with the active source versions."""

from collections import defaultdict

from sqlalchemy import or_, select

from app.api.v1.schemas import RegulationRef
from app.core.models import (
    Finding,
    FindingCitation,
    RegulationChunk,
    RegulationSource,
    RegulationVersion,
    RegulationVersionStatus,
)


def _normalized(text: str) -> str:
    return " ".join(text.split())


async def citation_refs(session, analysis_ids):
    if not analysis_ids:
        return {}
    archived = (
        await session.execute(
            select(
                Finding.id,
                Finding.analysis_id,
                RegulationSource.id,
                RegulationSource.title,
                RegulationSource.source_url,
                RegulationVersion,
                RegulationChunk.chunk_key,
                RegulationChunk.article,
                RegulationChunk.part,
                RegulationChunk.text,
            )
            .select_from(Finding)
            .join(FindingCitation, FindingCitation.finding_id == Finding.id)
            .join(RegulationChunk, RegulationChunk.id == FindingCitation.regulation_chunk_id)
            .join(RegulationVersion, RegulationVersion.id == RegulationChunk.version_id)
            .join(RegulationSource, RegulationSource.id == RegulationVersion.source_id)
            .where(Finding.analysis_id.in_(analysis_ids), Finding.is_published.is_(True))
            .order_by(FindingCitation.regulation_chunk_id)
        )
    ).all()
    if not archived:
        return {}
    versions = {
        version.source_id: version
        for version in await session.scalars(
            select(RegulationVersion).where(
                RegulationVersion.source_id.in_({row[2] for row in archived}),
                RegulationVersion.status == RegulationVersionStatus.ACTIVE,
            )
        )
    }
    by_key = {}
    by_article = defaultdict(list)
    for version_id, key, article, part, text in await session.execute(
        select(
            RegulationChunk.version_id,
            RegulationChunk.chunk_key,
            RegulationChunk.article,
            RegulationChunk.part,
            RegulationChunk.text,
        ).where(
            RegulationChunk.version_id.in_([v.id for v in versions.values()]),
            or_(
                RegulationChunk.chunk_key.in_({row[6] for row in archived}),
                RegulationChunk.article.in_({row[7] for row in archived if row[7] is not None}),
            ),
        )
    ):
        by_key[(version_id, key, article, part)] = text
        if article is not None:
            by_article[(version_id, article, part)].append(text)

    result = {}
    for finding_id, aid, source_id, title, url, version, key, article, part, text in archived:
        active = versions.get(source_id)
        status = "unknown"
        if active and active.id == version.id:
            status = "unchanged"
        elif active:
            exact = by_key.get((active.id, key, article, part))
            peers = by_article[(active.id, article, part)]
            if exact is not None:
                status = "unchanged" if _normalized(exact) == _normalized(text) else "changed"
            elif any(_normalized(peer) == _normalized(text) for peer in peers):
                status = "unchanged"
            elif article is not None and not peers:
                status = "not_in_active"
            elif len(peers) == 1:
                status = "changed"
        # The current result DTO has one citation per finding. Keep a stable choice.
        result.setdefault(
            finding_id,
            (
                aid,
                RegulationRef(
                    source_title=title,
                    article=article,
                    part=part,
                    edition_date=version.edition_date,
                    effective_from=version.effective_from,
                    effective_to=version.effective_to,
                    url=url,
                    version_id=version.id,
                    full_text=text,
                    update_status=status,
                    active_edition_date=active.edition_date if active else None,
                ),
            ),
        )
    return result
