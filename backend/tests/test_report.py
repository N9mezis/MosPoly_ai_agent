from app.domain.models import CheckStatus, ChunkCheckResult
from app.domain.report_md import build_markdown_report


def test_report_hides_ok_and_not_applicable_results() -> None:
    results = [
        ChunkCheckResult(chunk_id="1.1", status=CheckStatus.OK),
        ChunkCheckResult(chunk_id="1.2", status=CheckStatus.NOT_APPLICABLE),
        ChunkCheckResult(
            chunk_id="2.1",
            status=CheckStatus.WARNING,
            source="ТК РФ, статья 57",
            comment="Условие сформулировано неоднозначно.",
        ),
    ]

    report = build_markdown_report("contract.docx", results)

    assert "пункте 2.1" in report
    assert "пункте 1.1" not in report
    assert "пункте 1.2" not in report


def test_report_marks_processing_error_without_legal_basis() -> None:
    report = build_markdown_report(
        "contract.docx",
        [
            ChunkCheckResult(
                chunk_id="5.2",
                status=CheckStatus.ERROR,
                comment="Пункт не проверен из-за технической ошибки LLM.",
            )
        ],
    )

    assert "Ошибка обработки в пункте 5.2" in report
    assert "Пункт не проверен" in report
    assert "Основание" not in report
