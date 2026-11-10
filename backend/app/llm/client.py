from __future__ import annotations

import asyncio
import json
import re
import ssl
import time
import uuid
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.domain.models import CheckStatus, ContractChunk, LLMChunkResult, RetrievedRegulation

SYSTEM_PROMPT = """Ты проверяешь отдельный пункт стандартного трудового договора РФ.
Используй только переданные нормативные фрагменты. Не применяй знания, которых нет в контексте.

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
{"decision":"violation_found|no_violation","chunk_id":"ID","findings":[{"status":"...","source":"...","contract_quote":"...","law_quote":"...","comment":"..."}]}
Если замечаний нет, верни пустой массив findings. Не добавляй другие поля и Markdown."""

JSON_REPAIR_PROMPT = """Предыдущий ответ не удалось разобрать.
Повтори ответ и верни только один валидный JSON-объект без Markdown и пояснений.
Используй верхнеуровневые поля decision, chunk_id и findings. decision равен
violation_found, если findings не пуст, иначе no_violation. Каждый элемент findings должен
содержать status, source, contract_quote, law_quote и comment.
Корректно экранируй кавычки и переводы строк внутри строковых значений."""

REQUIRED_TERMS_SYSTEM_PROMPT = """Ты проверяешь полноту трудового договора РФ целиком.
Используй только переданный текст договора и нормативные фрагменты. Проверь четыре условия:
место работы, трудовую функцию, конкретный размер оклада и режим рабочего времени.
Верни замечание только если условие отсутствует или сформулировано неоднозначно.
Не требуй повторения условия в каждом пункте. Для найденной проблемы укажи ID наиболее
подходящего пункта и точную цитату. Если условие полностью отсутствует, используй
chunk_id "document" и пустую contract_quote. Статус замечания — warning.
Верни только JSON {"findings":[{"chunk_id":"...","status":"warning","source":"...",
"contract_quote":"...","law_quote":"...","comment":"..."}]}. Если проблем нет,
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
    """Direct GigaChat REST client with cached OAuth access tokens."""

    TOKEN_TTL_SECONDS = 29 * 60

    def __init__(
        self,
        credentials: str,
        scope: str = "GIGACHAT_API_PERS",
        model: str = "GigaChat-2",
        base_url: str = "https://api.giga.chat/v1",
        auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
        timeout_seconds: float = 60.0,
        temperature: float = 0.01,
        max_output_tokens: int = 900,
        verify_ssl: bool = True,
        ca_bundle_file: Path | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not credentials:
            raise ValueError("Для GigaChat нужен GIGACHAT_CREDENTIALS")
        self._credentials = credentials
        self._scope = scope
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._chat_url = f"{self._base_url}/chat/completions"
        self._models_url = f"{self._base_url}/models"
        self._auth_url = auth_url
        self._timeout = timeout_seconds
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._transport = transport
        self._verify = self._build_ssl_context(verify_ssl, ca_bundle_file)
        self._access_token: str | None = None
        self._token_valid_until = 0.0
        self._token_lock = asyncio.Lock()
        self._supports_json_schema: bool | None = None

    @staticmethod
    def _build_ssl_context(
        verify_ssl: bool,
        ca_bundle_file: Path | None,
    ) -> bool | ssl.SSLContext:
        if not verify_ssl:
            return False
        if ca_bundle_file:
            return ssl.create_default_context(cafile=str(ca_bundle_file))
        return True

    @property
    def _authorization_header(self) -> str:
        value = self._credentials.strip()
        if value.lower().startswith("basic "):
            return value
        return f"Basic {value}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self._timeout,
            verify=self._verify,
            transport=self._transport,
        )

    async def _request_access_token(self) -> str:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "RqUID": str(uuid.uuid4()),
            "Authorization": self._authorization_header,
        }
        async with self._client() as client:
            response = await client.post(
                self._auth_url,
                headers=headers,
                data={"scope": self._scope},
            )
            response.raise_for_status()
            data = response.json()
        token = str(data.get("access_token", ""))
        if not token:
            raise ValueError("GigaChat не вернул access_token")
        self._access_token = token
        self._token_valid_until = time.monotonic() + self.TOKEN_TTL_SECONDS
        return token

    async def _get_access_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._access_token and time.monotonic() < self._token_valid_until:
            return self._access_token
        async with self._token_lock:
            if (
                not force_refresh
                and self._access_token
                and time.monotonic() < self._token_valid_until
            ):
                return self._access_token
            return await self._request_access_token()

    async def _send_chat(self, payload: dict, force_refresh: bool = False) -> httpx.Response:
        token = await self._get_access_token(force_refresh=force_refresh)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        async with self._client() as client:
            return await client.post(self._chat_url, headers=headers, json=payload)

    async def _chat_content(self, payload: dict) -> str:
        request_payload = dict(payload)
        if self._supports_json_schema is False:
            request_payload.pop("response_format", None)
        response = await self._send_chat(request_payload)
        if response.status_code == 401:
            self._access_token = None
            self._token_valid_until = 0.0
            response = await self._send_chat(request_payload, force_refresh=True)
        if response.status_code in {400, 422} and "response_format" in request_payload:
            self._supports_json_schema = False
            request_payload.pop("response_format", None)
            response = await self._send_chat(request_payload)
        response.raise_for_status()
        if "response_format" in request_payload:
            self._supports_json_schema = True
        data = response.json()
        try:
            return str(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise LLMResponseFormatError("GigaChat вернул ответ без текста результата") from error

    async def check_connection(self) -> list[str]:
        token = await self._get_access_token()
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
        }
        async with self._client() as client:
            response = await client.get(self._models_url, headers=headers)
        if response.status_code == 401:
            self._access_token = None
            self._token_valid_until = 0.0
            token = await self._get_access_token(force_refresh=True)
            headers["Authorization"] = f"Bearer {token}"
            async with self._client() as client:
                response = await client.get(self._models_url, headers=headers)
        response.raise_for_status()
        data = response.json()
        raw_models = data.get("data", data.get("models", []))
        models: list[str] = []
        for item in raw_models:
            if isinstance(item, str):
                models.append(item)
            elif isinstance(item, dict):
                model_id = item.get("id") or item.get("name")
                if model_id:
                    models.append(str(model_id))
        return models

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
            "stream": False,
            "response_format": CHUNK_RESPONSE_FORMAT,
            "messages": messages,
        }
        content = await self._chat_content(payload)
        try:
            return _parse_results(content, chunk.chunk_id, use_decision=True)
        except LLMResponseFormatError:
            payload["messages"] = _repair_messages(messages, content)
            repaired_content = await self._chat_content(payload)
            try:
                return _parse_results(
                    repaired_content,
                    chunk.chunk_id,
                    use_decision=True,
                )
            except LLMResponseFormatError as error:
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
            {
                "role": "user",
                "content": _build_required_terms_prompt(chunks, regulations),
            },
        ]
        payload = {
            "model": self._model,
            "temperature": self._temperature,
            "max_tokens": self._max_output_tokens,
            "stream": False,
            "response_format": REQUIRED_TERMS_RESPONSE_FORMAT,
            "messages": messages,
        }
        content = await self._chat_content(payload)
        try:
            return _parse_results(content, "document", preserve_chunk_ids=True)
        except LLMResponseFormatError:
            payload["messages"] = _repair_messages(
                messages,
                content,
                REQUIRED_TERMS_REPAIR_PROMPT,
            )
            repaired_content = await self._chat_content(payload)
            try:
                return _parse_results(
                    repaired_content,
                    "document",
                    preserve_chunk_ids=True,
                )
            except LLMResponseFormatError as error:
                raise LLMResponseFormatError(
                    "GigaChat дважды вернул проверку полноты в некорректном формате"
                ) from error


def create_llm_client(
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout_seconds: float,
    temperature: float,
    max_output_tokens: int = 900,
    gigachat_credentials: str = "",
    gigachat_scope: str = "GIGACHAT_API_PERS",
    gigachat_model: str = "GigaChat-2",
    gigachat_base_url: str = "https://api.giga.chat/v1",
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth",
    gigachat_verify_ssl: bool = True,
    gigachat_ca_bundle_file: Path | None = None,
) -> LLMClient:
    if provider == "mock":
        return MockLLMClient()
    if provider == "openai_compatible":
        return OpenAICompatibleLLMClient(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
    if provider == "gigachat":
        return GigaChatLLMClient(
            credentials=gigachat_credentials,
            scope=gigachat_scope,
            model=gigachat_model,
            base_url=gigachat_base_url,
            auth_url=gigachat_auth_url,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            verify_ssl=gigachat_verify_ssl,
            ca_bundle_file=gigachat_ca_bundle_file,
        )
    raise ValueError(f"Неизвестный LLM_PROVIDER: {provider}")
