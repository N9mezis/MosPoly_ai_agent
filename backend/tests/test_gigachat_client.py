import asyncio
import json
import uuid
from urllib.parse import parse_qs

import httpx

from app.domain.models import (
    CheckStatus,
    ContractChunk,
    RegulationChunk,
    RetrievedRegulation,
)
from app.llm.client import GigaChatLLMClient


def test_gigachat_authenticates_and_reuses_access_token() -> None:
    calls = {"auth": 0, "chat": 0, "models": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/oauth":
            calls["auth"] += 1
            assert request.headers["Authorization"] == "Basic encoded-credentials"
            uuid.UUID(request.headers["RqUID"], version=4)
            assert parse_qs(request.content.decode()) == {"scope": ["GIGACHAT_API_PERS"]}
            return httpx.Response(200, json={"access_token": "access-token", "expires_at": 0})

        if request.url.path == "/v1/chat/completions":
            calls["chat"] += 1
            assert request.headers["Authorization"] == "Bearer access-token"
            payload = json.loads(request.content)
            assert payload["model"] == "GigaChat-2"
            assert payload["max_tokens"] == 900
            assert payload["response_format"]["type"] == "json_schema"
            if calls["chat"] == 3:
                assert "полноту трудового договора" in payload["messages"][0]["content"]
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "findings": [
                                                {
                                                    "chunk_id": "3.1",
                                                    "status": "warning",
                                                    "source": "ТК РФ, статья 57",
                                                    "contract_quote": "Оплата труда определяется работодателем",
                                                    "law_quote": "Обязательными являются условия оплаты труда",
                                                    "comment": "Не указан размер оклада",
                                                }
                                            ]
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "chunk_id": "5.2",
                                        "status": "warning",
                                        "source": "ТК РФ, статья 57",
                                        "contract_quote": "Оплата труда определяется работодателем",
                                        "law_quote": "Обязательными являются условия оплаты труда",
                                        "comment": "Не указан размер оклада",
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            )

        if request.url.path == "/v1/models":
            calls["models"] += 1
            assert request.headers["Authorization"] == "Bearer access-token"
            return httpx.Response(
                200,
                json={"data": [{"id": "GigaChat-2"}, {"id": "GigaChat-2-Pro"}]},
            )

        raise AssertionError(f"Unexpected URL: {request.url}")

    client = GigaChatLLMClient(
        credentials="encoded-credentials",
        transport=httpx.MockTransport(handler),
    )
    chunk = ContractChunk(
        chunk_id="5.2",
        text="Оплата труда определяется работодателем",
    )
    regulations = [
        RetrievedRegulation(
            regulation=RegulationChunk(
                chunk_id="tk-57",
                source_id="tk",
                source_title="ТК РФ",
                article="57",
                text="Обязательными являются условия оплаты труда",
            ),
            similarity_score=0.8,
        )
    ]

    async def run_checks():
        first = await client.check_chunk(chunk, regulations)
        second = await client.check_chunk(chunk, regulations)
        required = await client.check_required_terms([chunk], regulations)
        models = await client.check_connection()
        return first, second, required, models

    first, second, required, models = asyncio.run(run_checks())

    assert first[0].status == CheckStatus.WARNING
    assert second[0].status == CheckStatus.WARNING
    assert required is not None
    assert required[0].chunk_id == "3.1"
    assert models == ["GigaChat-2", "GigaChat-2-Pro"]
    assert calls == {"auth": 1, "chat": 3, "models": 1}


def test_gigachat_retries_once_when_first_answer_is_not_json() -> None:
    calls = {"auth": 0, "chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/oauth":
            calls["auth"] += 1
            return httpx.Response(200, json={"access_token": "access-token"})

        if request.url.path == "/v1/chat/completions":
            calls["chat"] += 1
            payload = json.loads(request.content)
            if calls["chat"] == 1:
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "невалидный ответ"}}]},
                )
            assert payload["messages"][-1]["role"] == "user"
            assert "валидный JSON" in payload["messages"][-1]["content"]
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "chunk_id": "5.2",
                                        "findings": [
                                            {
                                                "status": "warning",
                                                "source": "ТК РФ, статья 57",
                                                "contract_quote": "Условия оплаты труда",
                                                "law_quote": "",
                                                "comment": "Нужно уточнить размер оклада",
                                            },
                                            {
                                                "status": "warning",
                                                "source": "ТК РФ, статья 57",
                                                "contract_quote": "Условия оплаты труда",
                                                "law_quote": "",
                                                "comment": "Нужно уточнить доплаты",
                                            },
                                        ],
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = GigaChatLLMClient(
        credentials="encoded-credentials",
        transport=httpx.MockTransport(handler),
    )
    chunk = ContractChunk(chunk_id="5.2", text="Условия оплаты труда")
    regulations = [
        RetrievedRegulation(
            regulation=RegulationChunk(
                chunk_id="tk-57",
                source_id="tk",
                source_title="ТК РФ",
                article="57",
                text="Обязательными являются условия оплаты труда",
            ),
            similarity_score=0.8,
        )
    ]

    result = asyncio.run(client.check_chunk(chunk, regulations))

    assert len(result) == 2
    assert all(item.status == CheckStatus.WARNING for item in result)
    assert calls == {"auth": 1, "chat": 2}


def test_gigachat_falls_back_when_json_schema_is_not_supported() -> None:
    calls = {"auth": 0, "chat": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/oauth":
            calls["auth"] += 1
            return httpx.Response(200, json={"access_token": "access-token"})
        if request.url.path == "/v1/chat/completions":
            calls["chat"] += 1
            payload = json.loads(request.content)
            if calls["chat"] == 1:
                assert "response_format" in payload
                return httpx.Response(400, json={"message": "unsupported response_format"})
            assert "response_format" not in payload
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {"message": {"content": json.dumps({"chunk_id": "1.1", "findings": []})}}
                    ]
                },
            )
        raise AssertionError(f"Unexpected URL: {request.url}")

    client = GigaChatLLMClient(
        credentials="encoded-credentials",
        transport=httpx.MockTransport(handler),
    )
    chunk = ContractChunk(chunk_id="1.1", text="Место работы — Москва")
    regulations = [
        RetrievedRegulation(
            regulation=RegulationChunk(
                chunk_id="tk-57",
                source_id="tk",
                source_title="ТК РФ",
                article="57",
                text="Обязательным условием является место работы",
            ),
            similarity_score=0.8,
        )
    ]

    result = asyncio.run(client.check_chunk(chunk, regulations))

    assert result == []
    assert calls == {"auth": 1, "chat": 2}
