"""Начальная схема БД (все таблицы, см. app/core/models.py)

Revision ID: 0001
Revises:
Create Date: 2026-11-10 20:10:58.122083
"""

from __future__ import annotations

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.create_table(
        "document_types",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("scope", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "allowed_extensions",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{docx,pdf}'"),
            nullable=False,
        ),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_types")),
    )
    op.create_table(
        "embedding_cache",
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("text_sha256", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("model", "text_sha256", name=op.f("pk_embedding_cache")),
    )
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("dataset", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "config", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "metrics", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("git_commit", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_runs")),
    )
    op.create_table(
        "organizations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("inn", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_table(
        "prompt_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_template", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "json_schema",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("temperature", sa.Float(), server_default="0.01", nullable=False),
        sa.Column("max_tokens", sa.Integer(), server_default="900", nullable=False),
        sa.Column("notes", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_versions")),
        sa.UniqueConstraint("name", "version", name=op.f("uq_prompt_versions_name")),
    )
    op.create_table(
        "regulation_sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regulation_sources")),
    )
    op.create_table(
        "check_profiles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_type_id", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "prompt_versions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "params", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_check_profiles_document_type_id_document_types"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_check_profiles")),
        sa.UniqueConstraint(
            "document_type_id", "version", name=op.f("uq_check_profiles_document_type_id")
        ),
    )
    op.create_index(
        "ux_profile_active",
        "check_profiles",
        ["document_type_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("full_name", sa.Text(), nullable=False),
        sa.Column(
            "role",
            sa.Enum("user", "org_admin", "kb_expert", "service_admin", name="user_role"),
            server_default="user",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_users_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_organization_id"), "users", ["organization_id"], unique=False)
    op.create_index(
        "ux_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=True),
        sa.Column("actor_user_id", sa.UUID(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column(
            "payload", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("ip_address", postgresql.INET(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], name=op.f("fk_audit_log_actor_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_audit_log_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index(
        "ix_audit_created", "audit_log", [sa.literal_column("created_at DESC")], unique=False
    )
    op.create_index("ix_audit_entity", "audit_log", ["entity_type", "entity_id"], unique=False)
    op.create_table(
        "documents",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("original_filename", sa.Text(), nullable=False),
        sa.Column("mime_type", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("storage_key", sa.Text(), nullable=True),
        sa.Column("purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_documents_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_documents_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(
        "ix_documents_org",
        "documents",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_table(
        "profile_sources",
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["check_profiles.id"],
            name=op.f("fk_profile_sources_profile_id_check_profiles"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["regulation_sources.id"],
            name=op.f("fk_profile_sources_source_id_regulation_sources"),
        ),
        sa.PrimaryKeyConstraint("profile_id", "source_id", name=op.f("pk_profile_sources")),
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "regulation_versions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), server_default="", nullable=False),
        sa.Column("edition_date", sa.Date(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "indexing",
                "ready",
                "active",
                "archived",
                "failed",
                name="regulation_version_status",
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("embedding_model", sa.Text(), server_default="", nullable=False),
        sa.Column("chunks_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("uploaded_by", sa.UUID(), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
            name=op.f("ck_regulation_versions_effective_range"),
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["regulation_sources.id"],
            name=op.f("fk_regulation_versions_source_id_regulation_sources"),
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"], ["users.id"], name=op.f("fk_regulation_versions_uploaded_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regulation_versions")),
        sa.UniqueConstraint("source_id", "content_hash", name="ux_regver_hash"),
    )
    op.create_index(
        "ux_regver_active",
        "regulation_versions",
        ["source_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "analyses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("document_type_id", sa.Text(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "extracting",
                "analyzing",
                "completed",
                "failed",
                "cancelled",
                name="analysis_status",
            ),
            server_default="queued",
            nullable=False,
        ),
        sa.Column("stage", sa.Text(), server_default="", nullable=False),
        sa.Column("progress", sa.Float(), server_default="0", nullable=False),
        sa.Column("chunks_total", sa.Integer(), server_default="0", nullable=False),
        sa.Column("chunks_done", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_partial", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("llm_provider", sa.Text(), server_default="", nullable=False),
        sa.Column("llm_model", sa.Text(), server_default="", nullable=False),
        sa.Column("embedding_model", sa.Text(), server_default="", nullable=False),
        sa.Column("reranker", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "snapshot", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column(
            "document_blocks",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "summary", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=True),
        sa.Column("worker_id", sa.Text(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_analyses_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_analyses_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["document_type_id"],
            ["document_types.id"],
            name=op.f("fk_analyses_document_type_id_document_types"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_analyses_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["check_profiles.id"],
            name=op.f("fk_analyses_profile_id_check_profiles"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analyses")),
    )
    op.create_index(
        "ix_analyses_active_status",
        "analyses",
        ["status"],
        unique=False,
        postgresql_where=sa.text("status IN ('queued', 'extracting', 'analyzing')"),
    )
    op.create_index(
        "ix_analyses_org",
        "analyses",
        ["organization_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_analyses_owner",
        "analyses",
        ["created_by", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        "ux_analyses_idempotency",
        "analyses",
        ["organization_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_table(
        "regulation_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("version_id", sa.UUID(), nullable=False),
        sa.Column("chunk_key", sa.Text(), nullable=False),
        sa.Column("article", sa.Text(), nullable=True),
        sa.Column("part", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), server_default="", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(), nullable=True),
        sa.Column(
            "fts",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('russian', coalesce(title, '') || ' ' || text)", persisted=True
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["regulation_versions.id"],
            name=op.f("fk_regulation_chunks_version_id_regulation_versions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regulation_chunks")),
        sa.UniqueConstraint(
            "version_id", "chunk_key", name=op.f("uq_regulation_chunks_version_id")
        ),
    )
    op.create_index(
        "ix_regchunk_fts", "regulation_chunks", ["fts"], unique=False, postgresql_using="gin"
    )
    op.create_index(
        op.f("ix_regulation_chunks_article"), "regulation_chunks", ["article"], unique=False
    )
    op.create_table(
        "analysis_chunks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("chunk_key", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_length", sa.Integer(), nullable=False),
        sa.Column("block_ids", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column(
            "page_numbers", postgresql.ARRAY(sa.Integer()), server_default="{}", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_analysis_chunks_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_analysis_chunks")),
        sa.UniqueConstraint(
            "analysis_id", "chunk_key", name=op.f("uq_analysis_chunks_analysis_id")
        ),
    )
    op.create_index(
        "ix_chunks_analysis", "analysis_chunks", ["analysis_id", "ordinal"], unique=False
    )
    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.UUID(), nullable=False),
        sa.Column("case_key", sa.Text(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=True),
        sa.Column(
            "details", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_eval_case_results_analysis_id_analyses"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["eval_runs.id"],
            name=op.f("fk_eval_case_results_run_id_eval_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_eval_case_results")),
    )
    op.create_index(
        op.f("ix_eval_case_results_run_id"), "eval_case_results", ["run_id"], unique=False
    )
    op.create_table(
        "findings",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("chunk_key", sa.Text(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum("rule", "rule_required", "llm_chunk", "llm_document", name="finding_origin"),
            nullable=False,
        ),
        sa.Column("rule_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum("ok", "warning", "violation", "not_applicable", "error", name="finding_status"),
            nullable=False,
        ),
        sa.Column(
            "category",
            sa.Enum("critical", "recommended", "info", name="finding_category"),
            server_default="info",
            nullable=False,
        ),
        sa.Column("article", sa.Text(), nullable=True),
        sa.Column("source_label", sa.Text(), server_default="", nullable=False),
        sa.Column("source_edition", sa.Text(), server_default="", nullable=False),
        sa.Column("contract_quote", sa.Text(), server_default="", nullable=False),
        sa.Column("law_quote", sa.Text(), server_default="", nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=False),
        sa.Column("recommendation", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "highlights",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("retrieval_score", sa.Float(), nullable=True),
        sa.Column("is_published", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "validation_notes", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False
        ),
        sa.Column("dedup_key", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status <> 'violation' OR (contract_quote <> '' AND law_quote <> '')",
            name=op.f("ck_findings_violation_has_quotes"),
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_findings_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["analysis_chunks.id"],
            name=op.f("fk_findings_chunk_id_analysis_chunks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
    )
    op.create_index(op.f("ix_findings_analysis_id"), "findings", ["analysis_id"], unique=False)
    op.create_index(
        "ix_findings_article",
        "findings",
        ["article", "status"],
        unique=False,
        postgresql_where=sa.text("is_published"),
    )
    op.create_index(
        "ux_findings_dedup",
        "findings",
        ["analysis_id", "dedup_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('violation', 'warning')"),
    )
    op.create_table(
        "llm_calls",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=True),
        sa.Column("chunk_id", sa.UUID(), nullable=True),
        sa.Column("prompt_version_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "used_json_schema", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error_message", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_llm_calls_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["analysis_chunks.id"],
            name=op.f("fk_llm_calls_chunk_id_analysis_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["prompt_version_id"],
            ["prompt_versions.id"],
            name=op.f("fk_llm_calls_prompt_version_id_prompt_versions"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_analysis_id"), "llm_calls", ["analysis_id"], unique=False)
    op.create_index(
        "ix_llmcalls_created", "llm_calls", [sa.literal_column("created_at DESC")], unique=False
    )
    op.create_table(
        "retrievals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("analysis_id", sa.UUID(), nullable=False),
        sa.Column("chunk_id", sa.UUID(), nullable=False),
        sa.Column("regulation_chunk_id", sa.UUID(), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("channels", postgresql.ARRAY(sa.Text()), server_default="{}", nullable=False),
        sa.Column("vector_score", sa.Float(), nullable=True),
        sa.Column("lexical_score", sa.Float(), nullable=True),
        sa.Column("fused_score", sa.Float(), nullable=True),
        sa.Column("rerank_score", sa.Float(), nullable=True),
        sa.Column("was_sent_to_llm", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(
            ["analysis_id"],
            ["analyses.id"],
            name=op.f("fk_retrievals_analysis_id_analyses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["analysis_chunks.id"],
            name=op.f("fk_retrievals_chunk_id_analysis_chunks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["regulation_chunk_id"],
            ["regulation_chunks.id"],
            name=op.f("fk_retrievals_regulation_chunk_id_regulation_chunks"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_retrievals")),
    )
    op.create_index(op.f("ix_retrievals_analysis_id"), "retrievals", ["analysis_id"], unique=False)
    op.create_table(
        "finding_citations",
        sa.Column("finding_id", sa.UUID(), nullable=False),
        sa.Column("regulation_chunk_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_finding_citations_finding_id_findings"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["regulation_chunk_id"],
            ["regulation_chunks.id"],
            name=op.f("fk_finding_citations_regulation_chunk_id_regulation_chunks"),
        ),
        sa.PrimaryKeyConstraint(
            "finding_id", "regulation_chunk_id", name=op.f("pk_finding_citations")
        ),
    )


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("finding_citations")
    op.drop_index(op.f("ix_retrievals_analysis_id"), table_name="retrievals")
    op.drop_table("retrievals")
    op.drop_index("ix_llmcalls_created", table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_analysis_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(
        "ux_findings_dedup",
        table_name="findings",
        postgresql_where=sa.text("status IN ('violation', 'warning')"),
    )
    op.drop_index(
        "ix_findings_article", table_name="findings", postgresql_where=sa.text("is_published")
    )
    op.drop_index(op.f("ix_findings_analysis_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index(op.f("ix_eval_case_results_run_id"), table_name="eval_case_results")
    op.drop_table("eval_case_results")
    op.drop_index("ix_chunks_analysis", table_name="analysis_chunks")
    op.drop_table("analysis_chunks")
    op.drop_index(op.f("ix_regulation_chunks_article"), table_name="regulation_chunks")
    op.drop_index("ix_regchunk_fts", table_name="regulation_chunks", postgresql_using="gin")
    op.drop_table("regulation_chunks")
    op.drop_index(
        "ux_analyses_idempotency",
        table_name="analyses",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index("ix_analyses_owner", table_name="analyses")
    op.drop_index("ix_analyses_org", table_name="analyses")
    op.drop_index(
        "ix_analyses_active_status",
        table_name="analyses",
        postgresql_where=sa.text("status IN ('queued', 'extracting', 'analyzing')"),
    )
    op.drop_table("analyses")
    op.drop_index(
        "ux_regver_active",
        table_name="regulation_versions",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_table("regulation_versions")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("profile_sources")
    op.drop_index("ix_documents_org", table_name="documents")
    op.drop_table("documents")
    op.drop_index("ix_audit_entity", table_name="audit_log")
    op.drop_index("ix_audit_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ux_users_email_lower", table_name="users")
    op.drop_index(op.f("ix_users_organization_id"), table_name="users")
    op.drop_table("users")
    op.drop_index(
        "ux_profile_active", table_name="check_profiles", postgresql_where=sa.text("is_active")
    )
    op.drop_table("check_profiles")
    op.drop_table("regulation_sources")
    op.drop_table("prompt_versions")
    op.drop_table("organizations")
    op.drop_table("eval_runs")
    op.drop_table("embedding_cache")
    op.drop_table("document_types")
    for enum_name in (
        "user_role",
        "regulation_version_status",
        "analysis_status",
        "finding_status",
        "finding_category",
        "finding_origin",
    ):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
