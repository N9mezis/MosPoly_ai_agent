from __future__ import annotations

from typing import Protocol

import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray:
        """Return normalized vectors with shape (len(texts), dimensions)."""


class HashingEmbedder:
    """Offline baseline. Useful for smoke tests, but not truly semantic."""

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


class SentenceTransformerEmbedder:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        vectors = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


def create_embedder(provider: str, model_name: str) -> Embedder:
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "sentence_transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"Неизвестный провайдер embeddings: {provider}")
