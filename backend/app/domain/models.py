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
    text: str
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


class LLMChunkResult(BaseModel):
    chunk_id: str
    status: CheckStatus
    source: str = ""
    contract_quote: str = ""
    law_quote: str = ""
    comment: str = ""

    @field_validator("source", "contract_quote", "law_quote", "comment")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return " ".join(value.split())


class ChunkCheckResult(LLMChunkResult):
    retrieval_score: float | None = None
    validation_notes: list[str] = Field(default_factory=list)


class AnalysisReport(BaseModel):
    filename: str
    supported_document: bool
    message: str
    chunks_total: int = 0
    results: list[ChunkCheckResult] = Field(default_factory=list)
    markdown: str = ""
