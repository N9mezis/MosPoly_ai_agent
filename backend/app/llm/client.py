from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.domain.models import CheckStatus, ContractChunk, LLMChunkResult, RetrievedRegulation
from app.llm.calllog import record_call
from app.llm.gigachat import (
    DEFAULT_AUTH_URL,
    DEFAULT_BASE_URL,
    GigaChatAuth,
    GigaChatError,
    GigaChatHTTP,
    build_ssl_context,
)

SYSTEM_PROMPT = """Ты проверяешь отдельный пункт стандартного трудового договора РФ.
Используй только переданные нормативные фрагменты. Не применяй знания, которых нет в контексте.
Персональные данные в тексте обезличены: метки [PERSON], [PASSPORT], [SNILS], [INN], [PHONE],
[EMAIL], [ADDRESS] заменяют реальные сведения, которые в договоре присутствуют. Не считай
метку отсутствием сведений и не делай по ней замечаний.

Добавляй finding только при прямом и однозначном противоречии между фразой договора
и переданной нормой. Статус finding всегда violation. Обязательны точная дословная
цитата из договора, точная дословная цитата из нормы, источник и объяснение.
Если пункт законен, просто тематически связан с нормой, содержит разрешённое условие,
не содержит сведений из другой части договора или данных недостаточно — верни пустой
массив findings. Не предлагай уточнения и не создавай предупреждения. Отсутствие
условия проверяется отдельно на уровне всего договора. Не считай отсутствие упоминания
в этом пункте прямым нарушением. Условную норму (например, для инвалида или работы в
филиале) применяй только при прямо указанном условии её применимости. Не требуй включать
в договор процедурную обязанность работодателя, если норма прямо не называет её
обязательным условием трудового договора.

Один пункт может содержать несколько независимых проблем. Верни только компактный JSON:
{"decision":"violation_found|no_violation","chunk_id":"ID","findings":[{"status":"...","source":"...","contract_quote":"...","law_quote":"...","comment":"...","recommendation":"..."}]}
В recommendation кратко предложи законную формулировку пункта (одно-два предложения).
Если замечаний нет, верни пустой массив findings. Не добавляй другие поля и Markdown."""

JSON_REPAIR_PROMPT = """Предыдущий ответ не удалось разобрать.
Повтори ответ и верни только один валидный JSON-объект без Markdown и пояснений.
Используй верхнеуровневые поля decision, chunk_id и findings. decision равен
violation_found, если findings не пуст, иначе no_violation. Каждый элемент findings должен
содержать status, source, contract_quote, law_quote и comment.
Корректно экранируй кавычки и переводы строк внутри строковых значений."""

REQUIRED_TERMS_SYSTEM_PROMPT = """Ты проверяешь полноту трудового договора РФ целиком.
Используй только переданный текст договора и нормативные фрагменты.
Персональные данные в тексте обезличены: метки [PERSON], [PASSPORT], [SNILS], [INN], [PHONE],
[EMAIL], [ADDRESS] заменяют реальные сведения, которые в договоре присутствуют. Не считай
метку отсутствием сведений и не делай по ней замечаний.
Проверь четыре условия:
место работы, трудовую функцию, конкретный размер оклада и режим рабочего времени.
Верни замечание только если условие отсутствует или сформулировано неоднозначно.
Не требуй повторения условия в каждом пункте. Для найденной проблемы укажи ID наиболее
подходящего пункта и точную цитату. Если условие полностью отсутствует, используй
chunk_id "document" и пустую contract_quote. Статус замечания — warning.
Верни только JSON {"findings":[{"chunk_id":"...","status":"warning","source":"...",
"contract_quote":"...","law_quote":"...","comment":"...","recommendation":"..."}]}. В recommendation
предложи, какую формулировку добавить в договор. Если проблем нет,
верни пустой массив findings."""

REQUIRED_TERMS_REPAIR_PROMPT = """Предыдущий ответ не удалось разобрать.
Верни только валидный JSON с единственным верхнеуровневым полем findings.
Каждый элемент findings должен содержать chunk_id, status, source, contract_quote,
law_quote и comment. Не добавляй Markdown или пояснения."""

FINDING_PROPERTIES = {
    "status": {"type": "string", "enum": ["violation"]},
    "source": {"type": "string"},
    "contract_quote": {"type": "string"},
    "law_quote": {"type": "string"},
    "comment": {"type": "string"},
    "recommendation": {"type": "string"},
}

CHUNK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["violation_found", "no_violation"],
            },
            "chunk_id": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": FINDING_PROPERTIES,
                    "required": list(FINDING_PROPERTIES),
                    "additionalProperties": False,
                },
            },
        },
        "required": ["decision", "chunk_id", "findings"],
        "additionalProperties": False,
    },
    "strict": True,
}

REQUIRED_TERMS_RESPONSE_FORMAT = {
    "type": "json_schema",
    "schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "chunk_id": {"type": "string"},
                        **{
                            **FINDING_PROPERTIES,
                            "status": {"type": "string", "enum": ["warning"]},
                        },
                    },
                    "required": ["chunk_id", *FINDING_PROPERTIES],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["findings"],
        "additionalProperties": False,
    },
    "strict": True,
}


class LLMResponseFormatError(ValueError):
    """The model failed to return a result matching the expected JSON schema."""


class LLMClient(Protocol):
    async def check_chunk(
        self,
        chunk: ContractChunk,
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult]:
        """Check one contract chunk against retrieved regulations."""

    async def check_required_terms(
        self,
        chunks: list[ContractChunk],
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult] | None:
        """Check document-wide required terms, or return None for an offline client."""


def _build_user_prompt(
    chunk: ContractChunk,
    regulations: list[RetrievedRegulation],
) -> str:
    regulation_context = "\n\n".join(
        (f"[НОРМА {index}]\nИсточник: {item.regulation.citation}\nТекст: {item.regulation.text}")
        for index, item in enumerate(regulations, start=1)
    )
    return (
        f"[ПУНКТ ДОГОВОРА]\n"
        f"ID: {chunk.chunk_id}\n"
        f"Текст: {chunk.text}\n\n"
        f"[НОРМАТИВНЫЕ ФРАГМЕНТЫ]\n{regulation_context}"
    )


def _build_required_terms_prompt(
    chunks: list[ContractChunk],
    regulations: list[RetrievedRegulation],
) -> str:
    contract_context = "\n\n".join(f"[ПУНКТ {chunk.chunk_id}]\n{chunk.text}" for chunk in chunks)
    regulation_context = "\n\n".join(
        (f"[НОРМА {index}]\nИсточник: {item.regulation.citation}\nТекст: {item.regulation.text}")
        for index, item in enumerate(regulations, start=1)
    )
    return f"[ДОГОВОР]\n{contract_context}\n\n[НОРМАТИВНЫЕ ФРАГМЕНТЫ]\n{regulation_context}"


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as error:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("LLM не вернула JSON") from error
        return json.loads(cleaned[start : end + 1])


def _parse_results(
    content: str,
    chunk_id: str,
    *,
    preserve_chunk_ids: bool = False,
    use_decision: bool = False,
) -> list[LLMChunkResult]:
    try:
        payload = _extract_json(content)
        if not isinstance(payload, dict):
            raise ValueError("Верхний уровень ответа должен быть объектом")
        raw_findings = payload.get("findings")
        if raw_findings is None:
            # Backward compatibility with providers that still return one finding.
            raw_findings = [payload]
        if not isinstance(raw_findings, list):
            raise ValueError("Поле findings должно быть массивом")
        if use_decision:
            decision = payload.get("decision")
            # Providers without JSON-schema support may omit the new field; retain
            # compatibility while still enforcing it whenever it is returned.
            if decision == "no_violation":
                return []
            if decision == "violation_found" and not raw_findings:
                raise ValueError("decision=violation_found требует хотя бы один finding")
            if decision not in {None, "no_violation", "violation_found"}:
                raise ValueError("Неизвестное значение decision")
        results: list[LLMChunkResult] = []
        for raw_finding in raw_findings:
            if not isinstance(raw_finding, dict):
                raise ValueError("Элемент findings должен быть объектом")
            if raw_finding.get("status") == CheckStatus.ERROR:
                raise ValueError("Статус error зарезервирован для внутренних ошибок")
            results.append(
                LLMChunkResult.model_validate(
                    {
                        **raw_finding,
                        "chunk_id": (
                            raw_finding.get("chunk_id", chunk_id)
                            if preserve_chunk_ids
                            else chunk_id
                        ),
                    }
                )
            )
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError, KeyError) as error:
        raise LLMResponseFormatError(
            "Ответ LLM не соответствует ожидаемому JSON-формату"
        ) from error
    return results


def _repair_messages(
    messages: list[dict[str, str]],
    content: str,
    prompt: str = JSON_REPAIR_PROMPT,
) -> list[dict[str, str]]:
    return [
        *messages,
        {"role": "assistant", "content": content},
        {"role": "user", "content": prompt},
    ]


class MockLLMClient:
    async def check_chunk(
        self,
        chunk: ContractChunk,
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult]:
        source = regulations[0].regulation.citation if regulations else ""
        return [
            LLMChunkResult(
                chunk_id=chunk.chunk_id,
                status=CheckStatus.NOT_APPLICABLE,
                source=source,
                comment="Mock-режим: проверка через LLM не выполнялась.",
            )
        ]

    async def check_required_terms(
        self,
        chunks: list[ContractChunk],
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult] | None:
        return None


class OpenAICompatibleLLMClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str,
        timeout_seconds: float = 60.0,
        temperature: float = 0.0,
        max_output_tokens: int = 900,
    ) -> None:
        if not base_url or not model or not api_key:
            raise ValueError("Для LLM нужны LLM_BASE_URL, LLM_MODEL и LLM_API_KEY")
        self._url = f"{base_url.rstrip('/')}/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

    async def check_chunk(
        self,
        chunk: ContractChunk,
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk, regulations)},
        ]
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
        content = data["choices"][0]["message"]["content"]
        try:
            return _parse_results(content, chunk.chunk_id, use_decision=True)
        except LLMResponseFormatError:
            payload["messages"] = _repair_messages(messages, content)
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
            repaired_content = data["choices"][0]["message"]["content"]
            try:
                return _parse_results(
                    repaired_content,
                    chunk.chunk_id,
                    use_decision=True,
                )
            except LLMResponseFormatError as error:
                raise LLMResponseFormatError(
                    "LLM дважды вернула ответ в некорректном JSON-формате"
                ) from error

    async def check_required_terms(
        self,
        chunks: list[ContractChunk],
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult] | None:
        messages = [
            {"role": "system", "content": REQUIRED_TERMS_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_required_terms_prompt(chunks, regulations),
            },
        ]
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "messages": messages,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=payload, headers=headers)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        try:
            return _parse_results(content, "document", preserve_chunk_ids=True)
        except LLMResponseFormatError:
            payload["messages"] = _repair_messages(
                messages,
                content,
                REQUIRED_TERMS_REPAIR_PROMPT,
            )
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(self._url, json=payload, headers=headers)
                response.raise_for_status()
                repaired_content = response.json()["choices"][0]["message"]["content"]
            try:
                return _parse_results(
                    repaired_content,
                    "document",
                    preserve_chunk_ids=True,
                )
            except LLMResponseFormatError as error:
                raise LLMResponseFormatError(
                    "LLM дважды вернула проверку полноты в некорректном формате"
                ) from error


class GigaChatLLMClient:
    """Клиент GigaChat Chat Completions поверх `GigaChatHTTP` (свой ключ и кеш токена)."""

    def __init__(
        self,
        credentials: str = "",
        scope: str = "GIGACHAT_API_PERS",
        model: str = "GigaChat-2",
        base_url: str = DEFAULT_BASE_URL,
        auth_url: str = DEFAULT_AUTH_URL,
        timeout_seconds: float = 60.0,
        temperature: float = 0.01,
        max_output_tokens: int = 900,
        verify_ssl: bool = True,
        ca_bundle_file: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        http: GigaChatHTTP | None = None,
    ) -> None:
        if http is None:
            if not credentials:
                raise ValueError("Для GigaChat нужен GIGACHAT_LLM_CREDENTIALS")
            http = GigaChatHTTP(
                GigaChatAuth(credentials, scope=scope, auth_url=auth_url),
                base_url=base_url,
                timeout_seconds=timeout_seconds,
                verify=build_ssl_context(verify_ssl, ca_bundle_file),
                transport=transport,
            )
        self._http = http
        self.model_name = model
        self.provider = "gigachat"
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._supports_json_schema: bool | None = None

    async def _post_chat(self, payload: dict, purpose: str) -> httpx.Response:
        return await self._http.request(
            "POST", "chat/completions", json=payload, purpose=purpose, model=self.model_name
        )

    async def _chat_content(self, payload: dict, purpose: str) -> str:
        request_payload = dict(payload)
        if self._supports_json_schema is False:
            request_payload.pop("response_format", None)
        started = time.monotonic()
        response = await self._post_chat(request_payload, purpose)
        if response.status_code in {400, 422} and "response_format" in request_payload:
            self._supports_json_schema = False
            request_payload.pop("response_format", None)
            response = await self._post_chat(request_payload, purpose)
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            record_call(
                purpose,
                self.provider,
                self.model_name,
                1,
                latency,
                response.status_code,
                "error",
                f"HTTP {response.status_code}",
            )
            raise GigaChatError(
                f"GigaChat вернул HTTP {response.status_code}", status_code=response.status_code
            )
        used_schema = "response_format" in request_payload
        if used_schema:
            self._supports_json_schema = True
        data = response.json()
        usage = data.get("usage") or {}
        record_call(
            purpose,
            self.provider,
            self.model_name,
            1,
            latency,
            response.status_code,
            "ok",
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            used_json_schema=used_schema,
        )
        try:
            content = str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as error:
            raise LLMResponseFormatError("GigaChat вернул ответ без текста результата") from error
        if not content.strip() and used_schema:
            # На длинном контексте GigaChat в режиме json_schema иногда отдаёт пустой ответ
            # (finish_reason=stop). Повторяем этот запрос без схемы: формат держит промпт,
            # а разбор и валидацию делает _parse_results.
            fallback = dict(request_payload)
            fallback.pop("response_format", None)
            return await self._chat_content_plain(fallback, purpose)
        return content

    async def _chat_content_plain(self, payload: dict, purpose: str) -> str:
        started = time.monotonic()
        response = await self._post_chat(payload, purpose)
        latency = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            record_call(
                purpose,
                self.provider,
                self.model_name,
                2,
                latency,
                response.status_code,
                "error",
                f"HTTP {response.status_code}",
            )
            raise GigaChatError(
                f"GigaChat вернул HTTP {response.status_code}", status_code=response.status_code
            )
        data = response.json()
        usage = data.get("usage") or {}
        record_call(
            purpose,
            self.provider,
            self.model_name,
            2,
            latency,
            response.status_code,
            "ok_without_schema",
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )
        try:
            return str(data["choices"][0]["message"]["content"] or "")
        except (KeyError, IndexError, TypeError) as error:
            raise LLMResponseFormatError("GigaChat вернул ответ без текста результата") from error

    async def complete_json(
        self,
        messages: list[dict[str, str]],
        response_format: dict | None,
        *,
        purpose: str,
        max_tokens: int | None = None,
    ) -> str:
        """Общий вызов для вспомогательных задач (например, реранкера)."""
        payload: dict = {
            "model": self.model_name,
            "temperature": self._temperature,
            "max_tokens": max_tokens or self._max_output_tokens,
            "stream": False,
            "messages": messages,
        }
        if response_format:
            payload["response_format"] = response_format
        return await self._chat_content(payload, purpose)

    async def check_connection(self) -> list[str]:
        return await self._http.list_models()

    async def check_chunk(
        self,
        chunk: ContractChunk,
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult]:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(chunk, regulations)},
        ]
        payload = {
            "model": self.model_name,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
            "response_format": CHUNK_RESPONSE_FORMAT,
            "messages": messages,
        }
        content = await self._chat_content(payload, "chunk_check")
        try:
            return _parse_results(content, chunk.chunk_id, use_decision=True)
        except LLMResponseFormatError:
            record_call("chunk_check", self.provider, self.model_name, 1, None, 200, "schema_error")
            payload["messages"] = _repair_messages(messages, content)
            repaired_content = await self._chat_content(payload, "chunk_check")
            try:
                return _parse_results(repaired_content, chunk.chunk_id, use_decision=True)
            except LLMResponseFormatError as error:
                record_call(
                    "chunk_check", self.provider, self.model_name, 2, None, 200, "schema_error"
                )
                raise LLMResponseFormatError(
                    "GigaChat дважды вернул ответ в некорректном JSON-формате"
                ) from error

    async def check_required_terms(
        self,
        chunks: list[ContractChunk],
        regulations: list[RetrievedRegulation],
    ) -> list[LLMChunkResult] | None:
        messages = [
            {"role": "system", "content": REQUIRED_TERMS_SYSTEM_PROMPT},
            {"role": "user", "content": _build_required_terms_prompt(chunks, regulations)},
        ]
        payload = {
            "model": self.model_name,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
            "response_format": REQUIRED_TERMS_RESPONSE_FORMAT,
            "messages": messages,
        }
        content = await self._chat_content(payload, "required_terms")
        try:
            return _parse_results(content, "document", preserve_chunk_ids=True)
        except LLMResponseFormatError:
            record_call(
                "required_terms", self.provider, self.model_name, 1, None, 200, "schema_error"
            )
            payload["messages"] = _repair_messages(messages, content, REQUIRED_TERMS_REPAIR_PROMPT)
            repaired_content = await self._chat_content(payload, "required_terms")
            try:
                return _parse_results(repaired_content, "document", preserve_chunk_ids=True)
            except LLMResponseFormatError as error:
                raise LLMResponseFormatError(
                    "GigaChat дважды вернул проверку полноты в некорректном формате"
                ) from error
