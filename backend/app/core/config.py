"""Единая конфигурация приложения. Все секреты — только из окружения / .env (НФ-03)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- приложение ---
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    max_upload_mb: int = 10
    upload_tmp_dir: Path = Path("/tmp/tk-checker-uploads")
    repo_root: Path = Path(__file__).resolve().parents[3]

    # --- инфраструктура ---
    database_url: str = "postgresql+asyncpg://tk:tk@localhost:5432/tk"
    redis_url: str = "redis://localhost:6379/0"

    # --- auth (реализация — агент B) ---
    jwt_secret: SecretStr = SecretStr("change-me-in-env")
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 14
    # В режиме разработки запросы выполняются от имени dev-пользователя.
    auth_dev_mode: bool = True
    seed_admin_email: str = "admin@example.com"
    seed_admin_password: SecretStr = SecretStr("admin12345")
    seed_org_name: str = "Демо-организация"

    # --- LLM ---
    llm_provider: Literal["mock", "gigachat", "openai_compatible"] = "mock"
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.01
    llm_max_output_tokens: int = 900
    llm_max_parallel: int = 5
    # openai_compatible
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: SecretStr = SecretStr("")

    # --- GigaChat: общие параметры ---
    gigachat_base_url: str = "https://api.giga.chat/v1"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    gigachat_verify_ssl: bool = True
    gigachat_ca_bundle_file: Path | None = None

    # --- GigaChat: учётные данные проекта (Client ID + Client Secret из личного кабинета) ---
    # Authorization key = base64("client_id:client_secret") собирается автоматически.
    # Принимаются и имена с опечаткой GIGACHET_*.
    gigachat_client_id: str = Field(
        "", validation_alias=AliasChoices("gigachat_client_id", "gigachet_client_id")
    )
    gigachat_client_secret: SecretStr = Field(
        SecretStr(""),
        validation_alias=AliasChoices("gigachat_client_secret", "gigachet_client_secret"),
    )

    # --- GigaChat: LLM ---
    # Готовый authorization key (если задан, важнее client_id/secret).
    gigachat_llm_credentials: SecretStr = SecretStr("")
    gigachat_llm_scope: str = "GIGACHAT_API_PERS"
    gigachat_llm_model: str = "GigaChat-2"

    # --- GigaChat: эмбеддинги (по умолчанию — те же учётные данные, можно отдельный проект) ---
    gigachat_embed_credentials: SecretStr = SecretStr("")
    gigachat_embed_client_id: str = ""
    gigachat_embed_client_secret: SecretStr = SecretStr("")
    gigachat_embed_scope: str = "GIGACHAT_API_PERS"
    gigachat_embed_model: str = "Embeddings"

    # --- эмбеддинги и поиск ---
    embedding_provider: Literal["hashing", "gigachat", "openai_compatible"] = "hashing"
    # openai_compatible (Cloud.ru Foundation Models и т. п.)
    embedding_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    embedding_api_key: SecretStr = SecretStr("")
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimensions: int | None = None
    # Инструкция для запросов instruction-aware моделей (Qwen3-Embedding); пусто — без неё.
    embedding_query_instruction: str = (
        "Найди нормы Трудового кодекса РФ, применимые к этому пункту трудового договора"
    )
    embedding_batch_size: int = 16
    retrieval_candidates: int = 12
    retrieval_top_k: int = 4
    retrieval_similarity_floor: float = 0.0

    # --- реранкер ---
    reranker: Literal["none", "gigachat", "http"] = "none"
    gigachat_rerank_model: str = "GigaChat-2"
    rerank_http_url: str = ""
    rerank_http_api_key: SecretStr = SecretStr("")
    rerank_http_model: str = ""
    rerank_http_format: Literal["tei", "cohere"] = "tei"

    # --- данные ---
    regulations_dir: Path = Field(default=Path("data/regulations"))

    @field_validator("gigachat_ca_bundle_file", mode="before")
    @classmethod
    def empty_ca_bundle_is_none(cls, value):
        if value in (None, ""):
            return None
        return value

    @staticmethod
    def _authorization_key(credentials: SecretStr, client_id: str, secret: SecretStr) -> str:
        if credentials.get_secret_value():
            return credentials.get_secret_value().strip()
        if client_id and secret.get_secret_value():
            raw = f"{client_id.strip()}:{secret.get_secret_value().strip()}".encode()
            return base64.b64encode(raw).decode("ascii")
        return ""

    def gigachat_llm_key(self) -> str:
        """Authorization key для LLM: GIGACHAT_LLM_CREDENTIALS или CLIENT_ID + CLIENT_SECRET."""
        return self._authorization_key(
            self.gigachat_llm_credentials, self.gigachat_client_id, self.gigachat_client_secret
        )

    def gigachat_embed_key(self) -> str:
        """Authorization key для эмбеддингов: свой, если задан, иначе общий с LLM."""
        own = self._authorization_key(
            self.gigachat_embed_credentials,
            self.gigachat_embed_client_id,
            self.gigachat_embed_client_secret,
        )
        return own or self.gigachat_llm_key()

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @model_validator(mode="after")
    def validate_auth_settings(self) -> Settings:
        secret = self.jwt_secret.get_secret_value()
        if not self.auth_dev_mode and (
            len(secret.encode()) < 32 or secret == "change-me-please-long-random-string"
        ):
            raise ValueError("Для AUTH_DEV_MODE=false задайте случайный JWT_SECRET от 32 байт")
        return self

    def resolve_path(self, path: Path) -> Path:
        return path if path.is_absolute() else self.repo_root / path


@lru_cache
def get_settings() -> Settings:
    return Settings()
