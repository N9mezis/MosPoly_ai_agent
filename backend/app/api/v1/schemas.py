"""DTO API v1 — контракт между бэкендом и фронтендом.

ОБЩИЙ ФАЙЛ двух команд: изменения только аддитивные (новые поля с умолчаниями,
новые модели), отдельным маленьким PR. Удаление и переименование полей — только
по договорённости. См. docs/CONTRACTS.md.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.core.models import (
    AnalysisStatus,
    FindingCategory,
    FindingOrigin,
    FindingStatus,
    RegulationVersionStatus,
    UserRole,
)

T = TypeVar("T")

DISCLAIMER = (
    "Результат проверки носит рекомендательный характер и не является юридическим "
    "заключением. Спорные случаи требуют оценки специалиста."
)

CATEGORY_LABELS: dict[FindingCategory, str] = {
    FindingCategory.CRITICAL: "Критическая",
    FindingCategory.RECOMMENDED: "Рекомендательная",
    FindingCategory.INFO: "Информационная",
}

ANALYSIS_STATUS_LABELS: dict[AnalysisStatus, str] = {
    AnalysisStatus.QUEUED: "Ожидает обработки",
    AnalysisStatus.EXTRACTING: "Извлечение текста",
    AnalysisStatus.ANALYZING: "Выполняется",
    AnalysisStatus.COMPLETED: "Завершена",
    AnalysisStatus.FAILED: "Ошибка обработки",
    AnalysisStatus.CANCELLED: "Отменена",
}


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, use_enum_values=False)


# ============================================================ общие


class ErrorBody(ApiModel):
    code: str = Field(examples=["unsupported_document"])
    message: str = Field(examples=["Поддерживаются только файлы DOCX и PDF"])
    details: dict = Field(default_factory=dict)


class ErrorResponse(ApiModel):
    """Единый формат любой ошибки API."""

    error: ErrorBody


class Page(ApiModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ============================================================ auth / пользователи (агент B)


class LoginRequest(ApiModel):
    email: str = Field(examples=["admin@example.com"])
    password: str = Field(examples=["admin12345"])


class RefreshRequest(ApiModel):
    refresh_token: str


class TokenPair(ApiModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Срок жизни access-токена, секунды")


class OrganizationOut(ApiModel):
    id: uuid.UUID
    name: str
    inn: str | None = None
    is_active: bool = True
    created_at: datetime


class OrganizationCreate(ApiModel):
    name: str
    inn: str | None = None


class UserOut(ApiModel):
    id: uuid.UUID
    organization_id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool = True
    created_at: datetime


class UserCreate(ApiModel):
    email: str
    full_name: str
    password: str = Field(min_length=8)
    role: UserRole = UserRole.USER
    organization_id: uuid.UUID | None = Field(
        default=None, description="Только для service_admin; иначе — организация создателя"
    )


class UserUpdate(ApiModel):
    full_name: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class MeOut(UserOut):
    organization: OrganizationOut
    permissions: list[str] = Field(
        default_factory=list,
        description="Список разрешений для UI: analyses:create, analyses:read_org, "
        "users:manage, regulations:manage, organizations:manage",
    )


# ============================================================ типы документов


class DocumentTypeOut(ApiModel):
    id: str = Field(examples=["employment-contract"])
    title: str
    description: str
    scope: str
    allowed_extensions: list[str]
    is_enabled: bool


# ============================================================ документы и проверки


class DocumentUploaded(ApiModel):
    """Результат загрузки: файл принят и прошёл проверку допустимости."""

    document_id: uuid.UUID
    filename: str
    size_bytes: int
    page_count: int | None = None


class AnalysisCreate(ApiModel):
    document_id: uuid.UUID
    document_type_id: str = "employment-contract"


class AnalysisCreated(ApiModel):
    analysis_id: uuid.UUID
    status: AnalysisStatus


class AnalysisStatusOut(ApiModel):
    id: uuid.UUID
    status: AnalysisStatus
    status_label: str
    stage: str = Field("", description="Текущий этап на русском, для показа пользователю")
    progress: float = Field(0.0, ge=0, le=1)
    error_code: str | None = None
    error_message: str = ""
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AnalysisSummary(ApiModel):
    critical: int = 0
    recommended: int = 0
    info: int = 0
    technical_errors: int = 0
    chunks_total: int = 0


class AnalysisListItem(ApiModel):
    id: uuid.UUID
    filename: str
    document_type_id: str
    status: AnalysisStatus
    status_label: str
    summary: AnalysisSummary
    created_by_name: str = ""
    created_at: datetime
    finished_at: datetime | None = None


class DocumentBlock(ApiModel):
    """Абзац исходного документа (обезличенный) — основа отображения и подсветки."""

    block_id: str = Field(examples=["p12"])
    text: str
    page: int | None = None
    clause: str | None = Field(None, description="Номер пункта, если блок его начинает: '3.2'")


class Highlight(ApiModel):
    """Фрагмент для подсветки: символы [start, end) в тексте блока block_id."""

    block_id: str
    start: int
    end: int
    page: int | None = None


class RegulationRef(ApiModel):
    source_title: str = Field(examples=["Трудовой кодекс Российской Федерации"])
    article: str | None = Field(None, examples=["136"])
    part: str | None = None
    edition_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    url: str | None = None


class FindingOut(ApiModel):
    id: uuid.UUID
    chunk_key: str = Field(examples=["3.2"], description="Номер пункта договора или 'document'")
    category: FindingCategory
    category_label: str = Field(examples=["Критическая"])
    status: FindingStatus
    origin: FindingOrigin
    title: str = Field("", description="Короткий заголовок замечания")
    contract_quote: str
    regulation: RegulationRef
    law_quote: str
    explanation: str
    recommendation: str = ""
    highlights: list[Highlight] = Field(default_factory=list)


class TechnicalIssue(ApiModel):
    """Технический сбой при проверке пункта. Отделён от юридических замечаний."""

    chunk_key: str
    message: str


class AnalysisResult(ApiModel):
    id: uuid.UUID
    status: AnalysisStatus
    filename: str
    document_type_id: str
    created_at: datetime
    finished_at: datetime | None = None
    is_partial: bool = Field(False, description="Проверены не все пункты (сбой модели)")
    summary: AnalysisSummary
    blocks: list[DocumentBlock]
    findings: list[FindingOut] = Field(description="Отсортированы: критические первыми")
    technical_issues: list[TechnicalIssue] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class ReportFormat(str, Enum):
    PDF = "pdf"
    DOCX = "docx"


# ============================================================ нормативная база


class RegulationVersionOut(ApiModel):
    id: uuid.UUID
    source_id: str
    label: str = ""
    status: RegulationVersionStatus
    edition_date: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    chunks_count: int = 0
    embedding_model: str = ""
    error_message: str = ""
    uploaded_by_name: str = ""
    activated_at: datetime | None = None
    created_at: datetime


class RegulationSourceOut(ApiModel):
    id: str
    title: str
    source_url: str | None = None
    active_version_id: uuid.UUID | None = None
    versions: list[RegulationVersionOut] = Field(default_factory=list)


class RegulationChunkOut(ApiModel):
    id: uuid.UUID
    chunk_key: str
    article: str | None = None
    part: str | None = None
    title: str = ""
    text: str


# ============================================================ служебное


class HealthOut(ApiModel):
    status: Literal["ok"] = "ok"


class ReadyOut(ApiModel):
    status: Literal["ok", "degraded"]
    database: bool
    redis: bool
    llm_provider: str
    embedding_provider: str
    reranker: str
