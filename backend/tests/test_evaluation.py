from app.domain.models import (
    AnalysisReport,
    CheckStatus,
    ChunkCheckResult,
)
from app.evals.evaluation import EvaluationCase, ExpectedFinding, evaluate_report


def test_calculates_matches_misses_and_unexpected_findings() -> None:
    case = EvaluationCase(
        path="contract.docx",
        expected_findings=[
            ExpectedFinding(
                chunk_id="3.2",
                article="136",
                acceptable_statuses=[CheckStatus.VIOLATION],
            ),
            ExpectedFinding(
                chunk_id="4.1",
                article="91",
                acceptable_statuses=[CheckStatus.VIOLATION],
            ),
        ],
    )
    report = AnalysisReport(
        filename="contract.docx",
        supported_document=True,
        message="Анализ завершён.",
        results=[
            ChunkCheckResult(
                chunk_id="3.2",
                status=CheckStatus.VIOLATION,
                source="ТК РФ, статья 136",
            ),
            ChunkCheckResult(
                chunk_id="9.1",
                status=CheckStatus.WARNING,
                source="ТК РФ, статья 57",
            ),
            ChunkCheckResult(
                chunk_id="2.1",
                status=CheckStatus.OK,
                source="ТК РФ, статья 57",
            ),
            ChunkCheckResult(
                chunk_id="5.2",
                status=CheckStatus.ERROR,
                comment="Пункт не проверен.",
            ),
        ],
    )

    result = evaluate_report(case, report)

    assert result.matched_count == 1
    assert result.detected_count == 2
    assert [item.chunk_id for item in result.missed] == ["4.1"]
    assert [item.chunk_id for item in result.unexpected] == ["9.1"]
    assert [item.chunk_id for item in result.processing_errors] == ["5.2"]
