"""Единая конфигурация приложения. Все секреты — только из окружения / .env (НФ-03)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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

    # --- GigaChat: ключ для LLM ---
    gigachat_llm_credentials: SecretStr = SecretStr("")
    gigachat_llm_scope: str = "GIGACHAT_API_PERS"
    gigachat_llm_model: str = "GigaChat-2"

    # --- GigaChat: отдельный ключ для эмбеддингов ---
    gigachat_embed_credentials: SecretStr = SecretStr("")
    gigachat_embed_scope: str = "GIGACHAT_API_PERS"
    gigachat_embed_model: str = "Embeddings"

    # --- эмбеддинги и поиск ---
    embedding_provider: Literal["hashing", "gigachat"] = "hashing"
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

    # --- данные ---
    regulations_dir: Path = Field(default=Path("data/regulations"))

    @field_validator("gigachat_ca_bundle_file", mode="before")
    @classmethod
    def empty_ca_bundle_is_none(cls, value):
        if value in (None, ""):
            return None
        return value

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
