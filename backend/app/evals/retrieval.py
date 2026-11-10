"""`python -m app.cli evaluate-retrieval` — качество поиска норм (Ф-04: нужная статья в top-3 ≥ 85 %).

Для каждого ожидаемого замечания из evals/demo_cases.json берётся пункт договора
(`chunk_id`) и проверяется, на какой позиции поиск выдаёт нужную статью.
Сравниваются конфигурации каналов: dense / lexical / hints / dense+lexical / hybrid
(и hybrid+rerank с флагом --rerank).
"""

from __future__ import annotations

from pathlib import Path

from app.analysis.analyzer import anonymize_document
from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.models import EvalRun
from app.documents.parser import parse_document
from app.domain.chunker import chunk_document

from .evaluation import load_dataset
from .runner import build_retriever, git_commit

CONFIGS: list[tuple[str, frozenset[str], bool]] = [
    ("dense", frozenset({"dense"}), False),
    ("lexical", frozenset({"lexical"}), False),
    ("hints", frozenset({"hints"}), False),
    ("dense+lexical", frozenset({"dense", "lexical"}), False),
    ("hybrid", frozenset({"dense", "lexical", "hints"}), False),
]


def _queries(settings) -> list[tuple[str, str, str, str]]:
    """(case, текст пункта, ожидаемая статья) для всех замечаний с конкретным пунктом."""
    dataset = load_dataset(settings.resolve_path(Path("evals/demo_cases.json")))
    contracts = settings.resolve_path(Path("data/contracts"))
    items: list[tuple[str, str, str, str]] = []
    for case in dataset.cases:
        expected = [e for e in case.expected_findings if e.chunk_id != "document" and e.article]
        if not expected:
            continue
        document = anonymize_document(parse_document(contracts / case.path))
        document_text = "\n".join(block.text for block in document.blocks)
        chunks = {chunk.chunk_id: chunk for chunk in chunk_document(document)}
        for item in expected:
            chunk = chunks.get(item.chunk_id)
            if chunk is not None:
                items.append((case.path, chunk.text, item.article, document_text))
    return items


async def run_retrieval_eval(*, with_rerank: bool) -> None:
    settings = get_settings()
    sessionmaker = get_sessionmaker()
    retriever, params = await build_retriever(sessionmaker, settings, with_reranker=with_rerank)
    # Эти статьи подаются в проверку прямой выборкой по номеру (ТЗ, п. 5), поиск для них не нужен.
    direct = set(params.get("required_articles", ["57", "100"]))
    queries = _queries(settings)
    if not queries:
        print("В разметке нет замечаний с конкретными пунктами.")
        return
    configs = list(CONFIGS)
    if with_rerank:
        configs.append(("hybrid+rerank", frozenset({"dense", "lexical", "hints"}), True))

    print(
        f"Запросов: {len(queries)}; фрагментов нормативки: {retriever.size}; "
        f"эмбеддинги: {retriever._embedder.model_name}"
    )
    searched = sum(1 for q in queries if q[2] not in direct)
    print(f"Из них по статьям, которые ищутся поиском (не {', '.join(sorted(direct))}): {searched}")
    print(
        f"{'конфигурация':<16} {'recall@1':>9} {'recall@3':>9} {'recall@5':>9} {'MRR':>7}"
        f" {'recall@3*':>10}"
    )
    async with sessionmaker() as session:
        for name, channels, rerank in configs:
            hits = {1: 0, 3: 0, 5: 0}
            searched_hits = 0
            reciprocal = 0.0
            misses: list[str] = []
            for case, text, article, document_text in queries:
                retriever.set_document_context(document_text)
                results = await retriever.search(
                    text, top_k=10, channels=channels, use_reranker=rerank
                )
                articles = [item.regulation.article for item in results]
                rank = next((i for i, a in enumerate(articles, start=1) if a == article), None)
                if rank:
                    reciprocal += 1 / rank
                    for k in hits:
                        if rank <= k:
                            hits[k] += 1
                if rank and rank <= 3 and article not in direct:
                    searched_hits += 1
                if not rank or rank > 3:
                    misses.append(f"{Path(case).stem}: ст. {article} → {articles[:3]}")
            total = len(queries)
            metrics = {f"recall@{k}": hits[k] / total for k in hits} | {"mrr": reciprocal / total}
            metrics["recall@3_searched"] = searched_hits / searched if searched else None
            print(
                f"{name:<16} {metrics['recall@1']:>9.3f} {metrics['recall@3']:>9.3f} "
                f"{metrics['recall@5']:>9.3f} {metrics['mrr']:>7.3f}"
                f" {metrics['recall@3_searched'] or 0:>10.3f}"
            )
            session.add(
                EvalRun(
                    kind="retrieval",
                    dataset="demo_cases",
                    mode=name,
                    config={
                        "embedding_model": retriever._embedder.model_name,
                        "reranker": settings.reranker if rerank else "none",
                        "regulation_chunks": retriever.size,
                        "queries": total,
                    },
                    metrics=metrics | {"misses": misses[:20]},
                    git_commit=git_commit(),
                )
            )
        await session.commit()
    print(
        "Порог Ф-04: recall@3 ≥ 0.85. recall@3* — без статей прямой выборки. "
        "Промахи — в eval_runs.metrics.misses."
    )
