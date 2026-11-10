"""Транспорт GigaChat: OAuth-токен, TLS с сертификатом НУЦ, повторы, журнал вызовов.

LLM и эмбеддер используют РАЗНЫЕ ключи: создаётся по одному экземпляру
`GigaChatHTTP` на ключ, у каждого свой кеш токена.
"""

from __future__ import annotations

import asyncio
import logging
import random
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .calllog import record_call

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.giga.chat/v1"
DEFAULT_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"


class GigaChatError(RuntimeError):
    """Техническая ошибка обращения к GigaChat (после всех повторов)."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def build_ssl_context(verify_ssl: bool, ca_bundle_file: Path | None) -> bool | ssl.SSLContext:
    if not verify_ssl:
        return False
    if ca_bundle_file:
        context = ssl.create_default_context()
        # Системные корни + корневой сертификат НУЦ Минцифры.
        context.load_verify_locations(cafile=str(ca_bundle_file))
        return context
    return True


class GigaChatAuth:
    """Получение и кеширование access-токена по authorization key."""

    TOKEN_TTL_SECONDS = 29 * 60

    def __init__(
        self,
        credentials: str,
        *,
        scope: str = "GIGACHAT_API_PERS",
        auth_url: str = DEFAULT_AUTH_URL,
    ) -> None:
        if not credentials:
            raise ValueError("Не задан ключ авторизации GigaChat")
        self._credentials = credentials.strip()
        self.scope = scope
        self.auth_url = auth_url
        self._token: str | None = None
        self._valid_until = 0.0
        self._lock = asyncio.Lock()

    @property
    def authorization_header(self) -> str:
        if self._credentials.lower().startswith("basic "):
            return self._credentials
        return f"Basic {self._credentials}"

    def invalidate(self) -> None:
        self._token = None
        self._valid_until = 0.0

    def _cached(self) -> str | None:
        if self._token and time.monotonic() < self._valid_until:
            return self._token
        return None

    async def get_token(self, client: httpx.AsyncClient, *, force: bool = False) -> str:
        if not force and (token := self._cached()):
            return token
        async with self._lock:
            if not force and (token := self._cached()):
                return token
            response = await client.post(
                self.auth_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "RqUID": str(uuid.uuid4()),
                    "Authorization": self.authorization_header,
                },
                data={"scope": self.scope},
            )
            if response.status_code >= 400:
                raise GigaChatError(
                    f"GigaChat отклонил ключ авторизации (HTTP {response.status_code})",
                    status_code=response.status_code,
                )
            token = str(response.json().get("access_token", ""))
            if not token:
                raise GigaChatError("GigaChat не вернул access_token")
            self._token = token
            self._valid_until = time.monotonic() + self.TOKEN_TTL_SECONDS
            return token


class GigaChatHTTP:
    """HTTP-клиент GigaChat для одного ключа.

    Повторы: 401 → обновить токен и повторить; 429 → экспоненциальная задержка
    с jitter (до `max_rate_limit_retries`); таймаут/5xx → один повтор (НФ-02).
    """

    def __init__(
        self,
        auth: GigaChatAuth,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 60.0,
        verify: bool | ssl.SSLContext = True,
        transport: httpx.AsyncBaseTransport | None = None,
        max_rate_limit_retries: int = 4,
        provider: str = "gigachat",
    ) -> None:
        self.auth = auth
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._verify = verify
        self._transport = transport
        self._max_rate_limit_retries = max_rate_limit_retries
        self.provider = provider

    def _new_client(self) -> httpx.AsyncClient:
        # Клиент на запрос: не привязан к event loop (воркер, API и тесты живут в разных).
        return httpx.AsyncClient(
            timeout=self._timeout, verify=self._verify, transport=self._transport
        )

    async def aclose(self) -> None:  # совместимость: ресурсов между вызовами не держим
        return None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        purpose: str = "",
        model: str = "",
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempt = 0
        transient_retries = 0
        rate_retries = 0
        refreshed = False
        while True:
            attempt += 1
            started = time.monotonic()
            try:
                async with self._new_client() as client:
                    token = await self.auth.get_token(client)
                    response = await client.request(
                        method,
                        url,
                        json=json,
                        headers={"Accept": "application/json", "Authorization": f"Bearer {token}"},
                    )
            except (httpx.TimeoutException, httpx.TransportError) as error:
                latency = int((time.monotonic() - started) * 1000)
                outcome = "timeout" if isinstance(error, httpx.TimeoutException) else "error"
                record_call(
                    purpose,
                    self.provider,
                    model,
                    attempt,
                    latency,
                    None,
                    outcome,
                    type(error).__name__,
                )
                if transient_retries < 1:
                    transient_retries += 1
                    continue
                raise GigaChatError(f"GigaChat недоступен: {type(error).__name__}") from error

            latency = int((time.monotonic() - started) * 1000)
            status = response.status_code
            if status == 401 and not refreshed:
                refreshed = True
                self.auth.invalidate()
                continue
            if status == 429 and rate_retries < self._max_rate_limit_retries:
                record_call(purpose, self.provider, model, attempt, latency, status, "rate_limited")
                delay = min(30.0, 2**rate_retries) + random.uniform(0, 0.5)
                rate_retries += 1
                logger.warning("GigaChat: 429, повтор через %.1f с", delay)
                await asyncio.sleep(delay)
                continue
            if status >= 500 and transient_retries < 1:
                record_call(purpose, self.provider, model, attempt, latency, status, "error")
                transient_retries += 1
                continue
            return response

    async def list_models(self) -> list[str]:
        response = await self.request("GET", "models", purpose="check")
        if response.status_code >= 400:
            raise GigaChatError(
                f"Список моделей: HTTP {response.status_code}", status_code=response.status_code
            )
        data = response.json()
        models: list[str] = []
        for item in data.get("data", data.get("models", [])):
            if isinstance(item, str):
                models.append(item)
            elif isinstance(item, dict) and (model_id := item.get("id") or item.get("name")):
                models.append(str(model_id))
        return models


class GigaChatEmbedder:
    """Эмбеддинги GigaChat (`POST /embeddings`), батчами."""

    def __init__(self, http: GigaChatHTTP, *, model: str = "Embeddings", batch_size: int = 16):
        self._http = http
        self.model_name = model
        self._batch_size = max(1, batch_size)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self._batch_size):
            batch = texts[start : start + self._batch_size]
            started = time.monotonic()
            response = await self._http.request(
                "POST",
                "embeddings",
                json={"model": self.model_name, "input": batch},
                purpose="embed",
                model=self.model_name,
            )
            latency = int((time.monotonic() - started) * 1000)
            if response.status_code >= 400:
                record_call(
                    "embed",
                    self._http.provider,
                    self.model_name,
                    1,
                    latency,
                    response.status_code,
                    "error",
                )
                raise GigaChatError(
                    f"Эмбеддинги GigaChat: HTTP {response.status_code}",
                    status_code=response.status_code,
                )
            data = response.json()
            usage = data.get("usage") or {}
            record_call(
                "embed",
                self._http.provider,
                self.model_name,
                1,
                latency,
                200,
                "ok",
                prompt_tokens=usage.get("prompt_tokens"),
            )
            items = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors.extend([list(map(float, item["embedding"])) for item in items])
        if len(vectors) != len(texts):
            raise GigaChatError("GigaChat вернул неполный набор эмбеддингов")
        return vectors

    async def aclose(self) -> None:
        await self._http.aclose()
