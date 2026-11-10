"""Реранкер кандидатов поиска. Порт с тремя адаптерами (`RERANKER = none | gigachat | http`).

- none     — порядок RRF (по умолчанию: при маленькой базе реранкер не нужен);
- gigachat — listwise-реранкинг одним вызовом LLM на пункт (тот же ключ, что у LLM);
- http     — внешний сервис с API `/rerank` (Jina / Cohere / TEI-совместимый).

Выбор делается по метрикам `python -m app.cli evaluate-retrieval`.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

RERANK_SYSTEM_PROMPT = """Ты помогаешь юристу подобрать нормы Трудового кодекса РФ к пункту трудового договора.
Оцени, насколько каждый нормативный фрагмент нужен, чтобы проверить законность пункта.
Шкала: 3 — норма прямо регулирует условие пункта; 2 — тесно связана; 1 — тема та же,
но для проверки не нужна; 0 — не относится. Оцени каждый фрагмент из списка.
Верни только JSON {"scores":[{"id":<номер>,"relevance":<0-3>}]}."""

RERANK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "scores": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "relevance": {"type": "integer", "enum": [0, 1, 2, 3]},
                    },
                    "required": ["id", "relevance"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["scores"],
        "additionalProperties": False,
    },
    "strict": True,
}


class Reranker(Protocol):
    name: str

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        """Скор на каждый документ (больше — релевантнее) или None, если порядок не менять."""


class NoReranker:
    name = "none"

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        return None


class JsonCompleter(Protocol):
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_format: dict | None,
        *,
        purpose: str,
        max_tokens: int | None = None,
    ) -> str: ...


class LLMListwiseReranker:
    """Listwise-реранкинг через GigaChat. При любой ошибке — мягкий откат к порядку RRF."""

    name = "gigachat"

    def __init__(self, llm: JsonCompleter, *, snippet_chars: int = 400) -> None:
        self._llm = llm
        self._snippet_chars = snippet_chars

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        if len(documents) < 2:
            return None
        listing = "\n\n".join(
            f"[{index}] {text[: self._snippet_chars]}" for index, text in enumerate(documents)
        )
        messages = [
            {"role": "system", "content": RERANK_SYSTEM_PROMPT},
            {"role": "user", "content": f"[ПУНКТ ДОГОВОРА]\n{query}\n\n[ФРАГМЕНТЫ]\n{listing}"},
        ]
        try:
            content = await self._llm.complete_json(
                messages, RERANK_RESPONSE_FORMAT, purpose="rerank", max_tokens=400
            )
            payload = json.loads(content[content.find("{") : content.rfind("}") + 1])
            scores = [0.0] * len(documents)
            for item in payload.get("scores", []):
                index = int(item["id"])
                if 0 <= index < len(documents):
                    scores[index] = float(item["relevance"])
            return scores
        except Exception as error:  # реранкер не должен ронять проверку
            logger.warning(
                "LLM-реранкер не сработал (%s), используем порядок RRF", type(error).__name__
            )
            return None


class HttpReranker:
    """Внешний реранкер: POST {url} {model, query, documents, top_n} → results[{index, score}]."""

    name = "http"

    def __init__(
        self,
        url: str,
        *,
        api_key: str = "",
        model: str = "",
        timeout_seconds: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not url:
            raise ValueError("RERANKER=http, но не задан RERANK_HTTP_URL")
        self._url = url
        self._api_key = api_key
        self._model = model
        self._timeout = timeout_seconds
        self._transport = transport

    async def rerank(self, query: str, documents: list[str]) -> list[float] | None:
        if len(documents) < 2:
            return None
        body: dict = {"query": query, "documents": documents, "top_n": len(documents)}
        if self._model:
            body["model"] = self._model
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(self._url, json=body, headers=headers)
                response.raise_for_status()
                data = response.json()
            items = data.get("results", data if isinstance(data, list) else [])
            scores = [0.0] * len(documents)
            for item in items:
                score = item.get("relevance_score", item.get("score", 0.0))
                scores[int(item["index"])] = float(score)
            return scores
        except Exception as error:
            logger.warning(
                "HTTP-реранкер не сработал (%s), используем порядок RRF", type(error).__name__
            )
            return None
