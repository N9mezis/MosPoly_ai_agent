"""Формирование отчётов из опубликованного результата проверки."""

from collections.abc import Iterator
from html import escape
from io import BytesIO

from docx import Document

from app.api.v1.schemas import AnalysisResult, ReportFormat

TITLE = "Отчёт о проверке договора"


def _sections(result: AnalysisResult, document_type_title: str | None) -> Iterator[tuple[str, list[str]]]:
    completed = result.finished_at or result.created_at
    yield "", [
        f"Файл: {result.filename}",
        f"Дата проверки: {completed:%d.%m.%Y %H:%M %Z}".rstrip(),
        f"Тип документа: {document_type_title or result.document_type_id}",
        result.disclaimer,
    ]
    summary = result.summary
    lines = [
        f"Критические: {summary.critical}",
        f"Рекомендательные: {summary.recommended}",
        f"Информационные: {summary.info}",
        f"Технические сбои: {summary.technical_errors}",
    ]
    if result.is_partial:
        lines.append("Проверка частичная. Не все пункты удалось проверить.")
    yield "Сводка", lines
    if not result.findings:
        yield "Замечания", ["Замечаний нет."]
    for finding in result.findings:
        regulation = finding.regulation
        reference = [regulation.source_title]
        if regulation.article:
            reference.append(f"ст. {regulation.article}")
        if regulation.part:
            reference.append(f"ч. {regulation.part}")
        if regulation.edition_date:
            reference.append(f"редакция от {regulation.edition_date:%d.%m.%Y}")
        lines = [
            f"Пункт договора: {finding.chunk_key}",
            f"Цитата из договора: {finding.contract_quote}",
            f"Источник: {', '.join(reference)}",
            f"Цитата нормы: {finding.law_quote}",
            f"Пояснение: {finding.explanation}",
        ]
        if finding.recommendation:
            lines.append(f"Рекомендация: {finding.recommendation}")
        heading = " — ".join(filter(None, (finding.category_label, finding.title)))
        yield heading, lines
    if result.technical_issues:
        yield "Технические сбои", [
            f"{issue.chunk_key}: {issue.message}" for issue in result.technical_issues
        ]


def render_report(
    result: AnalysisResult, format: ReportFormat, document_type_title: str | None = None
) -> bytes:
    if format is ReportFormat.DOCX:
        document = Document()
        document.add_heading(TITLE, 0)
        for heading, lines in _sections(result, document_type_title):
            if heading:
                document.add_heading(heading, 1)
            for line in lines:
                document.add_paragraph(line)
        buffer = BytesIO()
        document.save(buffer)
        return buffer.getvalue()

    from weasyprint import HTML

    sections = []
    for heading, lines in _sections(result, document_type_title):
        if heading:
            sections.append(f"<h2>{escape(heading)}</h2>")
        sections.extend(f"<p>{escape(line)}</p>" for line in lines)
    return HTML(
        string=f"""<!doctype html>
<html lang="ru">
<head><meta charset="utf-8"><title>{TITLE}</title>
<style>
@page {{ size: A4; margin: 18mm; @bottom-right {{ content: counter(page); }} }}
body {{ font: 10.5pt/1.45 "DejaVu Sans", sans-serif; color: #202124; }}
h1 {{ font-size: 20pt; }}
h2 {{ font-size: 13pt; break-after: avoid; margin-top: 1.2em; }}
p {{ margin: 0.35em 0; overflow-wrap: anywhere; white-space: pre-wrap; }}
</style></head>
<body><h1>{TITLE}</h1>{''.join(sections)}</body></html>"""
    ).write_pdf()
