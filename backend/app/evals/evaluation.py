from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.analysis.analyzer import ContractAnalyzer
from app.domain.models import AnalysisReport, CheckStatus, ChunkCheckResult

ARTICLE_PATTERN = re.compile(r"статья\s+(?P<article>\d+)", re.IGNORECASE)
VISIBLE_STATUSES = {CheckStatus.WARNING, CheckStatus.VIOLATION}


class ExpectedFinding(BaseModel):
    chunk_id: str
    article: str
    acceptable_statuses: list[CheckStatus]


class EvaluationCase(BaseModel):
    path: str
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)


class EvaluationDataset(BaseModel):
    cases: list[EvaluationCase]


class CaseEvaluation(BaseModel):
    path: str
    supported_document: bool
    expected_count: int
    detected_count: int
    matched_count: int
    missed: list[ExpectedFinding] = Field(default_factory=list)
    unexpected: list[ChunkCheckResult] = Field(default_factory=list)
    processing_errors: list[ChunkCheckResult] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    cases_total: int
    expected_findings: int
    detected_findings: int
    matched_findings: int
    processing_errors: int
    precision: float | None
    recall: float | None
    cases: list[CaseEvaluation]


def load_dataset(path: Path) -> EvaluationDataset:
    return EvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))


def _article_from_source(source: str) -> str | None:
    match = ARTICLE_PATTERN.search(source)
    return match.group("article") if match else None


def _matches(expected: ExpectedFinding, actual: ChunkCheckResult) -> bool:
    return (
        expected.chunk_id == actual.chunk_id
        and expected.article == _article_from_source(actual.source)
        and actual.status in expected.acceptable_statuses
    )


def evaluate_report(case: EvaluationCase, report: AnalysisReport) -> CaseEvaluation:
    visible = [result for result in report.results if result.status in VISIBLE_STATUSES]
    processing_errors = [result for result in report.results if result.status == CheckStatus.ERROR]
    unmatched_actual = list(visible)
    missed: list[ExpectedFinding] = []
    matched_count = 0

    for expected in case.expected_findings:
        match_index = next(
            (index for index, actual in enumerate(unmatched_actual) if _matches(expected, actual)),
            None,
        )
        if match_index is None:
            missed.append(expected)
            continue
        matched_count += 1
        unmatched_actual.pop(match_index)

    return CaseEvaluation(
        path=case.path,
        supported_document=report.supported_document,
        expected_count=len(case.expected_findings),
        detected_count=len(visible),
        matched_count=matched_count,
        missed=missed,
        unexpected=unmatched_actual,
        processing_errors=processing_errors,
    )


async def run_evaluation(
    analyzer: ContractAnalyzer,
    dataset: EvaluationDataset,
    contracts_dir: Path,
    output_dir: Path,
    selected_cases: set[str] | None = None,
) -> EvaluationSummary:
    output_dir.mkdir(parents=True, exist_ok=True)
    case_results: list[CaseEvaluation] = []

    for case in dataset.cases:
        if selected_cases and case.path not in selected_cases:
            continue
        contract_path = contracts_dir / Path(case.path)
        if not contract_path.exists():
            raise FileNotFoundError(f"Не найден тестовый договор: {contract_path}")
        report = await analyzer.analyze(contract_path)
        case_result = evaluate_report(case, report)
        case_results.append(case_result)

        report_name = case.path.replace("/", "__").replace("\\", "__")
        (output_dir / f"{Path(report_name).stem}.md").write_text(
            report.markdown,
            encoding="utf-8",
        )

    expected_total = sum(case.expected_count for case in case_results)
    detected_total = sum(case.detected_count for case in case_results)
    matched_total = sum(case.matched_count for case in case_results)
    processing_error_total = sum(len(case.processing_errors) for case in case_results)
    summary = EvaluationSummary(
        cases_total=len(case_results),
        expected_findings=expected_total,
        detected_findings=detected_total,
        matched_findings=matched_total,
        processing_errors=processing_error_total,
        precision=(matched_total / detected_total if detected_total else None),
        recall=(matched_total / expected_total if expected_total else None),
        cases=case_results,
    )
    (output_dir / "summary.json").write_text(
        json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary
