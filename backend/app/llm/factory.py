"""Сборка LLM-клиента, эмбеддера и реранкера из настроек.

LLM и эмбеддер GigaChat используют разные ключи (`GIGACHAT_LLM_*`, `GIGACHAT_EMBED_*`).
"""

from __future__ import annotations

from app.core.config import Settings

from .client import GigaChatLLMClient, LLMClient, MockLLMClient, OpenAICompatibleLLMClient
from .embeddings import AsyncEmbedder, AsyncHashingEmbedder
from .gigachat import GigaChatAuth, GigaChatEmbedder, GigaChatHTTP, build_ssl_context


def _ca_file(settings: Settings):
    if settings.gigachat_ca_bundle_file is None:
        return None
    return settings.resolve_path(settings.gigachat_ca_bundle_file)


def gigachat_http(settings: Settings, *, credentials: str, scope: str) -> GigaChatHTTP:
    return GigaChatHTTP(
        GigaChatAuth(credentials, scope=scope, auth_url=settings.gigachat_auth_url),
        base_url=settings.gigachat_base_url,
        timeout_seconds=settings.llm_timeout_seconds,
        verify=build_ssl_context(settings.gigachat_verify_ssl, _ca_file(settings)),
    )


def llm_http(settings: Settings) -> GigaChatHTTP:
    return gigachat_http(
        settings,
        credentials=settings.gigachat_llm_key(),
        scope=settings.gigachat_llm_scope,
    )


def build_llm_client(settings: Settings) -> LLMClient:
    if settings.llm_provider == "mock":
        return MockLLMClient()
    if settings.llm_provider == "openai_compatible":
        return OpenAICompatibleLLMClient(
            base_url=settings.llm_base_url,
            model=settings.llm_model,
            api_key=settings.llm_api_key.get_secret_value(),
            timeout_seconds=settings.llm_timeout_seconds,
            temperature=settings.llm_temperature,
            max_output_tokens=settings.llm_max_output_tokens,
        )
    if not settings.gigachat_llm_key():
        raise ValueError(
            "LLM_PROVIDER=gigachat, но не заданы GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET"
        )
    return GigaChatLLMClient(
        http=llm_http(settings),
        model=settings.gigachat_llm_model,
        temperature=settings.llm_temperature,
        max_output_tokens=settings.llm_max_output_tokens,
    )


def build_embedder(settings: Settings) -> AsyncEmbedder:
    if settings.embedding_provider == "hashing":
        return AsyncHashingEmbedder()
    credentials = settings.gigachat_embed_key()
    if not credentials:
        raise ValueError(
            "EMBEDDING_PROVIDER=gigachat, но не заданы GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET"
        )
    return GigaChatEmbedder(
        gigachat_http(settings, credentials=credentials, scope=settings.gigachat_embed_scope),
        model=settings.gigachat_embed_model,
        batch_size=settings.embedding_batch_size,
    )


def build_reranker(settings: Settings):
    from app.knowledge.rerank import HttpReranker, LLMListwiseReranker, NoReranker

    if settings.reranker == "none":
        return NoReranker()
    if settings.reranker == "http":
        return HttpReranker(
            settings.rerank_http_url,
            api_key=settings.rerank_http_api_key.get_secret_value(),
            model=settings.rerank_http_model,
            format=settings.rerank_http_format,
        )
    if not settings.gigachat_llm_key():
        raise ValueError("RERANKER=gigachat, но не заданы учётные данные GigaChat")
    return LLMListwiseReranker(
        GigaChatLLMClient(
            http=llm_http(settings),
            model=settings.gigachat_rerank_model,
            temperature=0.0,
        )
    )
