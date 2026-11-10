from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class CheckStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    VIOLATION = "violation"
    NOT_APPLICABLE = "not_applicable"
    ERROR = "error"


class TextBlock(BaseModel):
    block_id: str
    text: str
    page_number: int | None = None


class ParsedDocument(BaseModel):
    filename: str
    blocks: list[TextBlock]


class ContractChunk(BaseModel):
    chunk_id: str
    text: str
    block_ids: list[str] = Field(default_factory=list)
    page_numbers: list[int] = Field(default_factory=list)


class RegulationChunk(BaseModel):
    chunk_id: str
    source_id: str
    source_title: str
    article: str | None = None
    part: str | None = None
    title: str = ""
    text: str
    db_id: str | None = None
    source_url: str | None = None
    edition_date: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None

    @property
    def citation(self) -> str:
        if self.article:
            return f"{self.source_title}, статья {self.article}"
        return self.source_title


class RetrievedRegulation(BaseModel):
    regulation: RegulationChunk
    similarity_score: float
    # Диагностика поиска: ранги и скоры каналов (dense/lexical/hints), rrf, rerank.
    trace: dict = Field(default_factory=dict)


class LLMChunkResult(BaseModel):
    chunk_id: str
    status: CheckStatus
    source: str = ""
    contract_quote: str = ""
    law_quote: str = ""
    comment: str = ""
    recommendation: str = ""

    @field_validator("source", "contract_quote", "law_quote", "comment", "recommendation")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class ChunkCheckResult(LLMChunkResult):
    retrieval_score: float | None = None
    validation_notes: list[str] = Field(default_factory=list)
    # Происхождение: rule | rule_required | llm_chunk | llm_document
    origin: str = "llm_chunk"
    rule_id: str | None = None
    # Нормативный фрагмент, которым подтверждена цитата нормы (chunk_id RegulationChunk).
    regulation_chunk_id: str | None = None


class AnalysisReport(BaseModel):
    filename: str
    supported_document: bool
    message: str
    chunks_total: int = 0
    results: list[ChunkCheckResult] = Field(default_factory=list)
    markdown: str = ""
    # Для сохранения в БД (заполняется конвейером): обезличенные блоки и пункты,
    # а также поисковая выдача по каждому пункту.
    blocks: list[TextBlock] = Field(default_factory=list)
    chunks: list[ContractChunk] = Field(default_factory=list)
    retrievals: dict[str, list[RetrievedRegulation]] = Field(default_factory=dict)
