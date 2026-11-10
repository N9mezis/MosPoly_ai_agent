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


class OpenAICompatibleEmbedder:
    """Эмбеддинги через OpenAI-совместимый `POST {base_url}/embeddings`
    (Cloud.ru Foundation Models и т. п.), батчами, с повтором при 429/5xx.

    Для instruction-aware моделей (Qwen3-Embedding) запросы можно снабжать инструкцией:
    документы (нормы) векторизуются как есть, а пункт договора — как
    «Instruct: …\nQuery: …».
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        batch_size: int = 32,
        query_instruction: str = "",
        dimensions: int | None = None,
        timeout_seconds: float = 60.0,
        provider: str = "openai_compatible",
        transport=None,
    ) -> None:
        if not base_url or not api_key or not model:
            raise ValueError(
                "Для EMBEDDING_PROVIDER=openai_compatible нужны EMBEDDING_BASE_URL, "
                "EMBEDDING_API_KEY и EMBEDDING_MODEL"
            )
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._api_key = api_key
        self.model_name = model
        self._batch_size = max(1, batch_size)
        self._instruction = query_instruction
        self._dimensions = dimensions
        self._timeout = timeout_seconds
        self._provider = provider
        self._transport = transport

    async def _post(self, batch: list[str]) -> list[list[float]]:
        import asyncio
        import random
        import time

        import httpx

        from .calllog import record_call

        body: dict = {"model": self.model_name, "input": batch}
        if self._dimensions:
            body["dimensions"] = self._dimensions
        for attempt in range(1, 5):
            started = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                    response = await c.post(
                        self._url, json=body, headers={"Authorization": f"Bearer {self._api_key}"}
                    )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                record_call(
                    "embed",
                    self._provider,
                    self.model_name,
                    attempt,
                    None,
                    None,
                    "timeout",
                    type(error).__name__,
                )
                if attempt >= 2:
                    raise RuntimeError(
                        f"Сервис эмбеддингов недоступен: {type(error).__name__}"
                    ) from error
                continue
            latency = int((time.monotonic() - started) * 1000)
            if response.status_code == 429 or response.status_code >= 500:
                record_call(
                    "embed",
                    self._provider,
                    self.model_name,
                    attempt,
                    latency,
                    response.status_code,
                    "rate_limited" if response.status_code == 429 else "error",
                )
                await asyncio.sleep(min(20.0, 2**attempt) + random.uniform(0, 0.5))
                continue
            if response.status_code >= 400:
                record_call(
                    "embed",
                    self._provider,
                    self.model_name,
                    attempt,
                    latency,
                    response.status_code,
                    "error",
                )
                hint = " (недостаточно средств на счёте)" if response.status_code == 402 else ""
                raise RuntimeError(f"Эмбеддинги: HTTP {response.status_code}{hint}")
            data = response.json()
            usage = data.get("usage") or {}
            record_call(
                "embed",
                self._provider,
                self.model_name,
                attempt,
                latency,
                200,
                "ok",
                prompt_tokens=usage.get("prompt_tokens"),
            )
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            return [list(map(float, item["embedding"])) for item in items]
        raise RuntimeError("Эмбеддинги: превышено число повторов")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            vectors.extend(await self._post(texts[start : start + self._batch_size]))
        if len(vectors) != len(texts):
            raise RuntimeError("Сервис вернул неполный набор эмбеддингов")
        return vectors

    def query_text(self, text: str) -> str:
        if not self._instruction:
            return text
        return f"Instruct: {self._instruction}\nQuery: {text}"

    async def embed_query(self, text: str) -> list[float]:
        return (await self.embed([self.query_text(text)]))[0]
