"""Служебные команды: python -m app.cli <команда>.

В Docker:  docker compose run --rm api python -m app.cli <команда>
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.core.config import get_settings
from app.core.logging import setup_logging


async def _seed() -> None:
    from app.core.db import get_engine, get_sessionmaker
    from app.core.seed import seed

    async with get_sessionmaker()() as session:
        await seed(session)
    await get_engine().dispose()
    print("Начальные данные на месте.")


def _not_implemented(name: str) -> None:
    print(f"Команда «{name}» ещё не реализована (см. docs/CONTRACTS.md, зона агента A).")
    sys.exit(2)


def main(argv: list[str] | None = None) -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="Создать организацию, сид-админа, типы документов, профиль")
    sub.add_parser("check-gigachat", help="Проверить оба ключа GigaChat (LLM и эмбеддинги)")
    p_import = sub.add_parser("import-kb", help="Импортировать нормативку из JSON-файлов")
    p_import.add_argument("path", nargs="?", default=str(settings.regulations_dir))
    sub.add_parser("reindex", help="Пересчитать эмбеддинги активных версий нормативки")
    p_eval = sub.add_parser("evaluate", help="Оценка точности/полноты на размеченных договорах")
    p_eval.add_argument("--rules-only", action="store_true")
    sub.add_parser("evaluate-retrieval", help="Оценка поиска: recall@k, MRR по каналам")

    args = parser.parse_args(argv)
    if args.command == "seed":
        asyncio.run(_seed())
    else:
        _not_implemented(args.command)


if __name__ == "__main__":
    main()
