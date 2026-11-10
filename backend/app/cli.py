"""Служебные команды: python -m app.cli <команда>.

В Docker:  docker compose run --rm api python -m app.cli <команда>
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import setup_logging


async def _seed() -> None:
    from app.core.db import get_sessionmaker
    from app.core.seed import seed

    async with get_sessionmaker()() as session:
        await seed(session)
    print("Начальные данные на месте.")


async def _import_kb(path: Path, activate: bool, if_empty: bool = False) -> None:
    from app.core.db import get_sessionmaker
    from app.core.errors import ConflictError
    from app.knowledge import service
    from app.llm.factory import build_embedder

    settings = get_settings()
    path = settings.resolve_path(path)
    files = [path] if path.is_file() else sorted(path.glob("*.json"))
    files = [item for item in files if not item.name.endswith(".example.json")]
    if not files:
        print(f"JSON-файлы нормативки не найдены: {path}")
        sys.exit(1)
    sessionmaker = get_sessionmaker()
    if if_empty:
        async with sessionmaker() as session:
            if await service.active_versions_count(session):
                print("Нормативка уже загружена.")
                return
    try:
        embedder = build_embedder(settings)
    except ValueError as error:
        print(f"Нормативка не загружена: {error}")
        return
    for file in files:
        async with sessionmaker() as session:
            try:
                version = await service.create_version(session, file.read_bytes(), uploaded_by=None)
                await session.commit()
            except ConflictError as error:
                print(f"• {file.name}: уже загружено ({error.details.get('version_id')})")
                continue
        print(f"• {file.name}: версия {version.id}, фрагментов {version.chunks_count}, индексация…")
        version = await service.index_version(sessionmaker, version.id, embedder)
        print(f"  статус: {version.status.value}, модель: {version.embedding_model}")
        if activate and version.status.value == "ready":
            async with sessionmaker() as session:
                await service.activate_version(session, version.id)
                await session.commit()
            print("  активирована")


async def _reindex() -> None:
    from sqlalchemy import select

    from app.core.db import get_sessionmaker
    from app.core.models import RegulationVersion, RegulationVersionStatus
    from app.knowledge import service
    from app.llm.factory import build_embedder

    settings = get_settings()
    sessionmaker = get_sessionmaker()
    embedder = build_embedder(settings)
    async with sessionmaker() as session:
        ids = list(
            await session.scalars(
                select(RegulationVersion.id).where(
                    RegulationVersion.status.in_(
                        [RegulationVersionStatus.ACTIVE, RegulationVersionStatus.READY]
                    )
                )
            )
        )
    for version_id in ids:
        version = await service.index_version(sessionmaker, version_id, embedder)
        print(f"• {version_id}: {version.status.value}, модель {version.embedding_model}")


async def _check_gigachat() -> None:
    from app.llm.factory import gigachat_http

    settings = get_settings()
    ok = True
    for title, creds, scope, model in (
        (
            "LLM",
            settings.gigachat_llm_credentials,
            settings.gigachat_llm_scope,
            settings.gigachat_llm_model,
        ),
        (
            "Эмбеддинги",
            settings.gigachat_embed_credentials,
            settings.gigachat_embed_scope,
            settings.gigachat_embed_model,
        ),
    ):
        secret = creds.get_secret_value()
        if not secret:
            print(f"✗ {title}: ключ не задан")
            ok = False
            continue
        try:
            models = await gigachat_http(settings, credentials=secret, scope=scope).list_models()
        except Exception as error:
            print(f"✗ {title}: {error}")
            ok = False
            continue
        mark = "✓" if model in models else "!"
        print(
            f"{mark} {title}: ключ принят, модель {model} {'доступна' if model in models else 'не найдена в списке'}"
        )
        print(f"  доступные модели: {', '.join(models)}")
    if not ok:
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Создать организацию, сид-админа, типы документов, профиль")
    sub.add_parser("check-gigachat", help="Проверить оба ключа GigaChat (LLM и эмбеддинги)")
    p_import = sub.add_parser(
        "import-kb", help="Загрузить, проиндексировать и активировать нормативку"
    )
    p_import.add_argument("path", nargs="?", default=str(settings.regulations_dir))
    p_import.add_argument(
        "--no-activate", action="store_true", help="Только загрузить и проиндексировать"
    )
    sub.add_parser("reindex", help="Пересчитать эмбеддинги активных и готовых версий")
    p_eval = sub.add_parser("evaluate", help="Оценка точности/полноты на размеченных договорах")
    p_eval.add_argument("--rules-only", action="store_true")
    p_eval.add_argument("--case", action="append", default=[])
    p_retr = sub.add_parser("evaluate-retrieval", help="Оценка поиска: recall@k, MRR по каналам")
    p_retr.add_argument("--rerank", action="store_true", help="Добавить конфигурацию с реранкером")

    args = parser.parse_args(argv)
    if args.command == "seed":
        asyncio.run(_seed())
    elif args.command == "import-kb":
        asyncio.run(
            _import_kb(Path(args.path), activate=not args.no_activate, if_empty=args.if_empty)
        )
    elif args.command == "reindex":
        asyncio.run(_reindex())
    elif args.command == "check-gigachat":
        asyncio.run(_check_gigachat())
    elif args.command == "evaluate":
        from app.evals.runner import run_findings_eval

        asyncio.run(run_findings_eval(rules_only=args.rules_only, cases=args.case))
    elif args.command == "evaluate-retrieval":
        from app.evals.retrieval import run_retrieval_eval

        asyncio.run(run_retrieval_eval(with_rerank=args.rerank))


if __name__ == "__main__":
    main()
