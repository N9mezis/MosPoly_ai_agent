"""ORM-модели всей схемы БД (основа — документ «Архитектура системы и БД», раздел 5.3).

Все таблицы описаны здесь, чтобы начальная миграция содержала полную схему и у двух
команд не было конфликтов миграций на старте. Владение логикой по таблицам —
см. docs/CONTRACTS.md.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


# ============================================================ ПЕРЕЧИСЛЕНИЯ


class UserRole(str, enum.Enum):
    """Роли по ТЗ (Ф-15)."""

    USER = "user"  # запускает проверки, видит только свои
    ORG_ADMIN = "org_admin"  # пользователи и все проверки своей организации
    KB_EXPERT = "kb_expert"  # управление нормативной базой (влияет на всех)
    SERVICE_ADMIN = "service_admin"  # организации, глобальные настройки


class RegulationVersionStatus(str, enum.Enum):
    DRAFT = "draft"
    INDEXING = "indexing"
    READY = "ready"  # проиндексирована, можно активировать
    ACTIVE = "active"
    ARCHIVED = "archived"
    FAILED = "failed"


class AnalysisStatus(str, enum.Enum):
    QUEUED = "queued"
    EXTRACTING = "extracting"
    ANALYZING = "analyzing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class FindingStatus(str, enum.Enum):
    OK = "ok"
    WARNING = "warning"
    VIOLATION = "violation"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class FindingCategory(str, enum.Enum):
    """Категории замечаний по ТЗ (Ф-07)."""

    CRITICAL = "critical"  # «Критическая»
    RECOMMENDED = "recommended"  # «Рекомендательная»
    INFO = "info"  # «Информационная»


class FindingOrigin(str, enum.Enum):
    RULE = "rule"
    RULE_REQUIRED = "rule_required"
    LLM_CHUNK = "llm_chunk"
    LLM_DOCUMENT = "llm_document"


# ============================================================ ОРГАНИЗАЦИИ, ДОСТУП


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)
    inn: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = _created_at()


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        _enum(UserRole, "user_role"), nullable=False, server_default=UserRole.USER.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ux_users_email_lower", func.lower(email), unique=True),)


class RefreshToken(Base):
    """Выданные refresh-токены (для отзыва при выходе). Логика — агент B."""

    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


# ============================================================ ТИПЫ ДОКУМЕНТОВ И ПРОФИЛИ


class DocumentType(Base):
    __tablename__ = "document_types"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 'employment-contract'
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    scope: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    allowed_extensions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{docx,pdf}'")
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class PromptVersion(Base):
    __tablename__ = "prompt_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str] = mapped_column(Text, nullable=False)  # 'chunk_check'
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_template: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, server_default="0.01")
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, server_default="900")
    notes: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (UniqueConstraint("name", "version"),)


class CheckProfile(Base):
    """Профиль проверки типа документа: параметры поиска, пороги правил, промпты."""

    __tablename__ = "check_profiles"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_type_id: Mapped[str] = mapped_column(ForeignKey("document_types.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"chunk_check": "<prompt_version_id>", "required_terms": "...", "rerank": "..."}
    prompt_versions: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    # {"top_k": 4, "candidates": 12, "similarity_floor": 0.0,
    #  "rules": {"max_work_week_hours": 40, ...},
    #  "article_hints": {"отпуск": ["115"], ...}, "required_articles": ["57", "100"]}
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        UniqueConstraint("document_type_id", "version"),
        Index(
            "ux_profile_active",
            "document_type_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
    )


# ============================================================ НОРМАТИВНАЯ БАЗА


class RegulationSource(Base):
    __tablename__ = "regulation_sources"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # 'tk_rf'
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class ProfileSource(Base):
    __tablename__ = "profile_sources"

    profile_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("check_profiles.id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("regulation_sources.id"), primary_key=True)


class RegulationVersion(Base):
    __tablename__ = "regulation_versions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_id: Mapped[str] = mapped_column(ForeignKey("regulation_sources.id"), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    edition_date: Mapped[date | None] = mapped_column(Date)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[RegulationVersionStatus] = mapped_column(
        _enum(RegulationVersionStatus, "regulation_version_status"),
        nullable=False,
        server_default=RegulationVersionStatus.DRAFT.value,
    )
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    chunks_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name="effective_range",
        ),
        Index(
            "ux_regver_active",
            "source_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        UniqueConstraint("source_id", "content_hash", name="ux_regver_hash"),
    )


class RegulationChunk(Base):
    __tablename__ = "regulation_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulation_versions.id", ondelete="CASCADE"), nullable=False
    )
    chunk_key: Mapped[str] = mapped_column(Text, nullable=False)  # 'tk_rf_article_91_1'
    article: Mapped[str | None] = mapped_column(Text, index=True)
    part: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False, server_default="")  # заголовок статьи
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Размерность не фиксирована: зависит от модели эмбеддингов (см. regulation_versions).
    embedding: Mapped[list[float] | None] = mapped_column(Vector())
    fts: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('russian', coalesce(title, '') || ' ' || text)", persisted=True),
    )

    __table_args__ = (
        UniqueConstraint("version_id", "chunk_key"),
        Index("ix_regchunk_fts", "fts", postgresql_using="gin"),
    )


class EmbeddingCache(Base):
    """Кеш эмбеддингов: не тратим квоту на повторный расчёт одного и того же текста."""

    __tablename__ = "embedding_cache"

    model: Mapped[str] = mapped_column(Text, primary_key=True)
    text_sha256: Mapped[str] = mapped_column(Text, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    created_at: Mapped[datetime] = _created_at()


# ============================================================ ДОКУМЕНТЫ И АНАЛИЗЫ


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = _uuid_pk()
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    storage_key: Mapped[str | None] = mapped_column(Text)  # NULL после удаления оригинала
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_documents_org", "organization_id", text("created_at DESC")),)


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = _uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    document_type_id: Mapped[str] = mapped_column(ForeignKey("document_types.id"), nullable=False)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("check_profiles.id"))
    status: Mapped[AnalysisStatus] = mapped_column(
        _enum(AnalysisStatus, "analysis_status"),
        nullable=False,
        server_default=AnalysisStatus.QUEUED.value,
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    progress: Mapped[float] = mapped_column(Float, nullable=False, server_default="0")
    chunks_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    chunks_done: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_partial: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    # Снимок входа для воспроизводимости (НФТ-7): версии нормативки, промпты, модели.
    llm_provider: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    llm_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    reranker: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Структура документа (обезличенная) для подсветки в UI: [{block_id, text, page}]
    document_blocks: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    error_code: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(Text)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_analyses_org", "organization_id", text("created_at DESC")),
        Index("ix_analyses_owner", "created_by", text("created_at DESC")),
        Index(
            "ix_analyses_active_status",
            "status",
            postgresql_where=text("status IN ('queued', 'extracting', 'analyzing')"),
        ),
        Index(
            "ux_analyses_idempotency",
            "organization_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class AnalysisChunk(Base):
    __tablename__ = "analysis_chunks"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False
    )
    chunk_key: Mapped[str] = mapped_column(Text, nullable=False)  # '3.2', 'intro', 'document'
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)  # ТОЛЬКО обезличенный текст
    char_length: Mapped[int] = mapped_column(Integer, nullable=False)
    block_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    page_numbers: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("analysis_id", "chunk_key"),
        Index("ix_chunks_analysis", "analysis_id", "ordinal"),
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_chunks.id", ondelete="CASCADE")
    )
    chunk_key: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[FindingOrigin] = mapped_column(
        _enum(FindingOrigin, "finding_origin"), nullable=False
    )
    rule_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[FindingStatus] = mapped_column(
        _enum(FindingStatus, "finding_status"), nullable=False
    )
    category: Mapped[FindingCategory] = mapped_column(
        _enum(FindingCategory, "finding_category"),
        nullable=False,
        server_default=FindingCategory.INFO.value,
    )
    article: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    source_edition: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    contract_quote: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    law_quote: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    comment: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    # Расположение цитаты для подсветки: [{block_id, start, end, page}]
    highlights: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="[]")
    retrieval_score: Mapped[float | None] = mapped_column(Float)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    validation_notes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    dedup_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        # НФТ-5: нарушение без обеих цитат не может существовать даже при баге в коде.
        CheckConstraint(
            "status <> 'violation' OR (contract_quote <> '' AND law_quote <> '')",
            name="violation_has_quotes",
        ),
        Index(
            "ix_findings_article",
            "article",
            "status",
            postgresql_where=text("is_published"),
        ),
        Index(
            "ux_findings_dedup",
            "analysis_id",
            "dedup_key",
            unique=True,
            postgresql_where=text("status IN ('violation', 'warning')"),
        ),
    )


class FindingCitation(Base):
    __tablename__ = "finding_citations"

    finding_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True
    )
    regulation_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulation_chunks.id"), primary_key=True
    )


class Retrieval(Base):
    __tablename__ = "retrievals"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_chunks.id", ondelete="CASCADE"), nullable=False
    )
    regulation_chunk_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("regulation_chunks.id"), nullable=False
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    vector_score: Mapped[float | None] = mapped_column(Float)
    lexical_score: Mapped[float | None] = mapped_column(Float)
    fused_score: Mapped[float | None] = mapped_column(Float)
    rerank_score: Mapped[float | None] = mapped_column(Float)
    was_sent_to_llm: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )


# ============================================================ ЖУРНАЛ LLM


class LLMCall(Base):
    """Журнал обращений к модели. Тексты промптов и ответов НЕ хранятся (Ф-17)."""

    __tablename__ = "llm_calls"

    id: Mapped[uuid.UUID] = _uuid_pk()
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), index=True
    )
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analysis_chunks.id", ondelete="SET NULL")
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prompt_versions.id"))
    purpose: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # chunk_check|required_terms|rerank|embed
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    used_json_schema: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    http_status: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # ok|schema_error|timeout|rate_limited|error
    error_message: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (Index("ix_llmcalls_created", text("created_at DESC")),)


# ============================================================ ОЦЕНКА КАЧЕСТВА


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = _uuid_pk()
    kind: Mapped[str] = mapped_column(Text, nullable=False)  # 'findings' | 'retrieval'
    dataset: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # rules_only|full|dense|lexical|hybrid|...
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    git_commit: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = _created_at()


class EvalCaseResult(Base):
    __tablename__ = "eval_case_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_key: Mapped[str] = mapped_column(Text, nullable=False)
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL")
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")


# ============================================================ АУДИТ


class AuditLog(Base):
    """Журнал значимых действий без ПДн и секретов (Ф-17, НФ-12). Логика — агент B."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("organizations.id"))
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(Text, nullable=False)  # 'regulation.activate'
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    ip_address: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
        Index("ix_audit_created", text("created_at DESC")),
    )
