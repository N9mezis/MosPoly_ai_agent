from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from pydantic import BaseModel, Field, field_validator

from app.domain.models import RegulationChunk, RetrievedRegulation
from app.llm.embeddings import Embedder


class RegulationSourceChunkFile(BaseModel):
    chunk_id: str | None = None
    article: str | None = None
    text: str

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Нормативный фрагмент не может быть пустым")
        return normalized


class RegulationSourceFile(BaseModel):
    source_id: str
    source_title: str
    source_url: str | None = None
    edition_date: str | None = None
    effective_from: str | None = None
    effective_to: str | None = None
    chunks: list[RegulationSourceChunkFile] = Field(min_length=1)

    @field_validator("source_id")
    @classmethod
    def source_id_must_be_safe(cls, value: str) -> str:
        if not value or not all(character.isalnum() or character in "_-" for character in value):
            raise ValueError("source_id может содержать только буквы, цифры, _ и -")
        return value

    @field_validator("source_title")
    @classmethod
    def source_title_must_not_be_empty(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Название источника не может быть пустым")
        return normalized


class KnowledgeBase:
    def __init__(self, chunks: list[RegulationChunk], embedder: Embedder) -> None:
        self._chunks = chunks
        self._embedder = embedder
        self._vectors = embedder.encode([chunk.text for chunk in chunks])

    @property
    def size(self) -> int:
        return len(self._chunks)

    def find_by_article(self, article: str) -> list[RegulationChunk]:
        """Return active normative chunks for an exact article number."""
        return [chunk for chunk in self._chunks if chunk.article == article]

    @classmethod
    def from_directory(cls, directory: Path, embedder: Embedder) -> KnowledgeBase:
        chunks: list[RegulationChunk] = []
        if directory.exists():
            for path in sorted(directory.glob("*.json")):
                if path.name.endswith(".example.json"):
                    continue
                source = RegulationSourceFile.model_validate_json(path.read_text(encoding="utf-8"))
                for index, raw_chunk in enumerate(source.chunks, start=1):
                    chunks.append(
                        RegulationChunk(
                            chunk_id=raw_chunk.chunk_id or f"{source.source_id}-{index}",
                            source_id=source.source_id,
                            source_title=source.source_title,
                            article=raw_chunk.article,
                            text=raw_chunk.text,
                            source_url=source.source_url,
                            edition_date=source.edition_date,
                            effective_from=source.effective_from,
                            effective_to=source.effective_to,
                        )
                    )
        return cls(chunks=chunks, embedder=embedder)

    def search(self, query: str, top_k: int = 3) -> list[RetrievedRegulation]:
        if not self._chunks or not query.strip() or top_k <= 0:
            return []
        query_vector = self._embedder.encode([query])[0]
        scores = self._vectors @ query_vector
        limit = min(top_k, len(self._chunks))
        best_indices = np.argsort(scores)[-limit:][::-1]
        return [
            RetrievedRegulation(
                regulation=self._chunks[int(index)],
                similarity_score=float(scores[int(index)]),
            )
            for index in best_indices
        ]


def write_source_template(path: Path) -> None:
    template = {
        "source_id": "tk_rf_example",
        "source_title": "Трудовой кодекс Российской Федерации",
        "source_url": "https://pravo.gov.ru/",
        "edition_date": "YYYY-MM-DD",
        "effective_from": "YYYY-MM-DD",
        "effective_to": None,
        "chunks": [
            {
                "chunk_id": "tk_rf_example_article_00_1",
                "article": "00",
                "text": "Вставьте сюда точный фрагмент нормы из официального источника.",
            }
        ],
    }
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
