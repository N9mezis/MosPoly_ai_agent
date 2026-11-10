"""Общие хелперы роутеров."""

from __future__ import annotations

from fastapi import Response

from app.core.errors import AppError


def mark_stub(response: Response) -> None:
    """Помечает ответ-заглушку: данные из фикстур, а не из конвейера."""
    response.headers["X-Stub"] = "true"


class NotImplementedYet(AppError):
    status_code = 501
    code = "not_implemented"

    def __init__(self, owner: str) -> None:
        super().__init__(f"Эндпоинт ещё не реализован (зона агента {owner}).")
