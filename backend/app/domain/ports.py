"""Порты домена: интерфейсы, которые реализуют адаптеры вне domain.

domain не импортирует ни FastAPI, ни SQL, ни HTTP-клиенты.
"""

from __future__ import annotations

from typing import Protocol

from .models import RegulationChunk


class ArticleLookup(Protocol):
    """Прямая выборка активных нормативных фрагментов по номеру статьи."""

    def find_by_article(self, article: str) -> list[RegulationChunk]: ...
