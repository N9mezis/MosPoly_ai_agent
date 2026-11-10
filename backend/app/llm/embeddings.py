"""Эмбеддеры. Настоящие эмбеддинги — GigaChat (`app/llm/gigachat.py`), здесь офлайн-вариант."""

from __future__ import annotations

from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer


class Embedder(Protocol):
    """Синхронный эмбеддер (используется in-memory базой знаний в тестах)."""

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return normalized vectors with shape (len(texts), dimensions)."""


class AsyncEmbedder(Protocol):
    """Асинхронный эмбеддер для конвейера и индексации нормативки."""

    model_name: str

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbedder:
    """Офлайн-baseline на символьных n-граммах. Годится для тестов, но не семантический."""

    def __init__(self, dimensions: int = 4096) -> None:
        self._vectorizer = HashingVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            n_features=dimensions,
            alternate_sign=False,
            norm="l2",
            lowercase=True,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, self._vectorizer.n_features), dtype=np.float32)
        return self._vectorizer.transform(texts).toarray().astype(np.float32)


class AsyncHashingEmbedder:
    """Асинхронная обёртка над HashingEmbedder для режима без ключей."""

    def __init__(self, dimensions: int = 1024) -> None:
        self._inner = HashingEmbedder(dimensions=dimensions)
        self.model_name = f"hashing-{dimensions}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return self._inner.encode(texts).tolist()
