"""`python -m app.cli evaluate` — точность и полнота замечаний на размеченных договорах.

Использует активную нормативку из БД и текущие настройки LLM/эмбеддингов/реранкера.
`--rules-only` — без обращения к LLM (mock), квота не тратится.
Результаты: evals/results[-rules]/*.md, summary.json и строка в eval_runs.
"""

from __future__ import annotations

import subprocess

from sqlalchemy import select

from app.analysis.analyzer import ContractAnalyzer
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.models import CheckProfile, EvalRun
from app.knowledge.embedding_cache import CachedEmbedder
from app.knowledge.retrieval import HybridRetriever, RetrievalSettings
from app.llm.calllog import start_call_log, stop_call_log
from app.llm.client import MockLLMClient
from app.llm.factory import build_embedder, build_llm_client, build_reranker

from .evaluation import load_dataset, run_evaluation


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        ).stdout.strip()
    except Exception:
        return ""


async def build_retriever(sessionmaker, settings, *, with_reranker: bool = True):
    async with sessionmaker() as session:
        profile = await session.scalar(
            select(CheckProfile).where(
                CheckProfile.document_type_id == "employment-contract", CheckProfile.is_active
            )
        )
    params = dict(profile.params) if profile else {}
    retrieval_settings = RetrievalSettings.from_params(params, settings)
    retriever = HybridRetriever(
        sessionmaker,
        CachedEmbedder(build_embedder(settings), sessionmaker),
        settings=retrieval_settings,
        reranker=build_reranker(settings) if with_reranker else None,
    )
    await retriever.load(profile_id=profile.id if profile else None)
    return retriever, params


async def run_findings_eval(*, rules_only: bool, cases: list[str]) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    retriever, params = await build_retriever(sessionmaker, settings)
    llm = MockLLMClient() if rules_only else build_llm_client(settings)
    analyzer = ContractAnalyzer(
        retriever,
        llm,
        top_k=retriever.settings.top_k,
        max_parallel=settings.llm_max_parallel,
        required_articles=tuple(params.get("required_articles", ("57", "100"))),
    )
    output = settings.resolve_path(
        __import__("pathlib").Path("evals/results-rules" if rules_only else "evals/results")
    )
    dataset = load_dataset(
        settings.resolve_path(__import__("pathlib").Path("evals/demo_cases.json"))
    )
    log, token = start_call_log()
    try:
        summary = await run_evaluation(
            analyzer,
            dataset,
            settings.resolve_path(__import__("pathlib").Path("data/contracts")),
            output,
            set(cases) or None,
        )
    finally:
        stop_call_log(token)

    tokens = sum((r.prompt_tokens or 0) + (r.completion_tokens or 0) for r in log.records)
    metrics = {
        "precision": summary.precision,
        "recall": summary.recall,
        "matched": summary.matched_findings,
        "expected": summary.expected_findings,
        "detected": summary.detected_findings,
        "processing_errors": summary.processing_errors,
        "llm_calls": len(log.records),
        "tokens": tokens,
    }
    async with sessionmaker() as session:
        session.add(
            EvalRun(
                kind="findings",
                dataset="demo_cases",
                mode="rules_only" if rules_only else "full",
                config={
                    "llm_provider": "mock" if rules_only else settings.llm_provider,
                    "llm_model": getattr(llm, "model_name", ""),
                    "embedding_model": retriever._embedder.model_name,
                    "reranker": settings.reranker,
                    "cases": summary.cases_total,
                },
                metrics=metrics,
                git_commit=git_commit(),
            )
        )
        await session.commit()

    def fmt(value):
        return "—" if value is None else f"{value:.3f}"

    print(f"Договоров: {summary.cases_total}")
    print(
        f"Ожидалось замечаний: {summary.expected_findings}, выдано: {summary.detected_findings}, "
        f"совпало: {summary.matched_findings}"
    )
    print(f"Precision: {fmt(summary.precision)}   Recall: {fmt(summary.recall)}")
    print(
        f"Технических ошибок: {summary.processing_errors}; вызовов LLM: {len(log.records)}, "
        f"токенов: {tokens}"
    )
    print(f"Отчёты: {output}")
