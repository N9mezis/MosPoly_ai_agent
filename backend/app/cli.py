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
    path = path.resolve() if path.exists() else settings.resolve_path(path)
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


async def _check_gigachat(smoke: bool) -> None:
    from app.llm.factory import gigachat_http
    from app.llm.gigachat import GigaChatEmbedder

    settings = get_settings()
    ok = True
    checks = (
        (
            "LLM",
            settings.gigachat_llm_key(),
            settings.gigachat_llm_scope,
            settings.gigachat_llm_model,
        ),
        (
            "Эмбеддинги",
            settings.gigachat_embed_key(),
            settings.gigachat_embed_scope,
            settings.gigachat_embed_model,
        ),
    )
    for title, key, scope, model in checks:
        if not key:
            print(f"✗ {title}: не заданы GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET")
            ok = False
            continue
        http = gigachat_http(settings, credentials=key, scope=scope)
        try:
            models = await http.list_models()
        except Exception as error:
            print(f"✗ {title}: {error}")
            ok = False
            continue
        available = model in models
        print(
            f"{'✓' if available else '!'} {title}: ключ принят (scope {scope}), модель {model} "
            f"{'доступна' if available else 'не найдена в списке'}"
        )
        print(f"  доступные модели: {', '.join(models)}")
        if smoke and title == "Эмбеддинги":
            try:
                vector = (await GigaChatEmbedder(http, model=model).embed(["проверка связи"]))[0]
                print(f"  тестовый эмбеддинг: размерность {len(vector)}")
            except Exception as error:
                print(f"✗ эмбеддинг не получен: {error}")
                ok = False
    if not ok:
        sys.exit(1)


def _build_source(args) -> None:
    import json

    settings = get_settings()
    files = [Path(item) for item in args.files]
    missing = [str(item) for item in files if not item.exists()]
    if missing:
        print(f"Файлы не найдены: {', '.join(missing)}")
        sys.exit(1)

    if args.mode == "code":
        from app.knowledge.tk_parser import parse_code, read_pdf_lines, to_source_json

        if len(files) != 1 or files[0].suffix.lower() != ".pdf":
            print("Режим code принимает один PDF с текстом кодекса.")
            sys.exit(1)
        lines, dropped, preamble = read_pdf_lines(files[0])
        code = parse_code(lines, dropped_notes=dropped, preamble=preamble)
        selected = {a.strip() for a in args.articles.split(",") if a.strip()} or None
        data = to_source_json(
            code,
            source_id=args.source_id,
            source_title=args.title,
            **({"source_url": args.url} if args.url else {}),
            articles=selected,
        )
        active = [a for a in code.articles if not a.repealed]
        print(
            f"Статей: {len(active)} (утратили силу: {len(code.articles) - len(active)}), "
            f"частей: {len(data['chunks'])}, редакция: {code.edition_label}; "
            f"выброшено строк примечаний: {dropped}"
        )
        stamp = code.edition_date.isoformat() if code.edition_date else "undated"
    else:
        from app.knowledge.text_source import build_text_source

        data = build_text_source(
            files, source_id=args.source_id, source_title=args.title, source_url=args.url
        )
        print(f"Документов: {len(files)}, фрагментов: {len(data['chunks'])}")
        stamp = "text"

    out = (
        Path(args.out)
        if args.out
        else settings.resolve_path(settings.regulations_dir / f"{args.source_id}_{stamp}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Записано: {out}")
    print(f"Загрузка в базу: python -m app.cli import-kb {out}")


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Создать организацию, сид-админа, типы документов, профиль")
    p_check = sub.add_parser(
        "check-gigachat", help="Проверить доступ к GigaChat (LLM и эмбеддинги)"
    )
    p_check.add_argument("--smoke", action="store_true", help="Сделать один тестовый эмбеддинг")
    p_import = sub.add_parser(
        "import-kb", help="Загрузить, проиндексировать и активировать нормативку"
    )
    p_import.add_argument("path", nargs="?", default=str(settings.regulations_dir))
    p_import.add_argument(
        "--no-activate", action="store_true", help="Только загрузить и проиндексировать"
    )
    p_import.add_argument(
        "--if-empty", action="store_true", help="Только если активной нормативки ещё нет"
    )
    p_build = sub.add_parser(
        "build-source",
        help="Собрать JSON источника из PDF/DOCX/TXT (кодекс — по структуре, прочее — свободно)",
    )
    p_build.add_argument("files", nargs="+", help="Файлы-источники")
    p_build.add_argument(
        "--mode",
        choices=["code", "text"],
        default="code",
        help="code — кодекс по статьям и частям (PDF); text — свободная нарезка (разъяснения)",
    )
    p_build.add_argument("--source-id", default="tk_rf")
    p_build.add_argument("--title", default="Трудовой кодекс Российской Федерации")
    p_build.add_argument("--url", default=None)
    p_build.add_argument(
        "--articles", default="", help="Только эти статьи через запятую (по умолчанию — все)"
    )
    p_build.add_argument("--out", default=None, help="Куда записать JSON")
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
    elif args.command == "build-source":
        _build_source(args)
    elif args.command == "reindex":
        asyncio.run(_reindex())
    elif args.command == "check-gigachat":
        asyncio.run(_check_gigachat(args.smoke))
    elif args.command == "evaluate":
        from app.evals.runner import run_findings_eval

        asyncio.run(run_findings_eval(rules_only=args.rules_only, cases=args.case))
    elif args.command == "evaluate-retrieval":
        from app.evals.retrieval import run_retrieval_eval

        asyncio.run(run_retrieval_eval(with_rerank=args.rerank))


if __name__ == "__main__":
    main()
