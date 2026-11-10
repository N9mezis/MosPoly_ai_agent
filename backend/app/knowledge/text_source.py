"""Свободная нарезка неструктурированных материалов (разъяснения Роструда, письма Минтруда,
обзоры практики) для базы знаний.

Такие фрагменты служат контекстом для LLM. Поле `article` у них не заполняется: основанием
замечания остаётся норма кодекса. Упомянутые статьи попадают в заголовок фрагмента и
помогают полнотекстовому поиску.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

ARTICLE_MENTION = re.compile(r"(?:ст\.|стать[яиеюй]\w*)\s*(\d{1,3}(?:\.\d{1,2})?)", re.IGNORECASE)


def read_paragraphs(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix == ".docx":
        from docx import Document

        return [p.text.strip() for p in Document(str(path)).paragraphs if p.text.strip()]
    if suffix == ".pdf":
        import pymupdf

        text = "\n".join(page.get_text() for page in pymupdf.open(str(path)))
    else:
        text = path.read_text(encoding="utf-8")
    # Абзац — блок, отделённый пустой строкой, либо строка, закончившая предложение.
    paragraphs: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            if current:
                paragraphs.append(" ".join(current))
                current = []
            continue
        current.append(line)
        if line.endswith((".", "!", "?", ":")) and len(" ".join(current)) > 200:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return [" ".join(p.split()) for p in paragraphs if p.strip()]


def chunk_paragraphs(paragraphs: list[str], *, target: int = 1000, overlap: int = 1) -> list[str]:
    """Собирает абзацы в фрагменты ~target символов; соседние фрагменты перекрываются абзацем."""
    chunks: list[str] = []
    window: list[str] = []
    size = 0
    for paragraph in paragraphs:
        if window and size + len(paragraph) > target:
            chunks.append("\n".join(window))
            window = window[-overlap:] if overlap else []
            size = sum(len(p) for p in window)
        window.append(paragraph)
        size += len(paragraph)
    if window and (not chunks or "\n".join(window) != chunks[-1]):
        chunks.append("\n".join(window))
    return chunks


def build_text_source(
    files: list[Path],
    *,
    source_id: str,
    source_title: str,
    source_url: str | None = None,
    edition_date: date | None = None,
    target: int = 1000,
) -> dict:
    chunks = []
    for file in files:
        pieces = chunk_paragraphs(read_paragraphs(file), target=target)
        for index, text in enumerate(pieces, start=1):
            mentioned = sorted(
                set(ARTICLE_MENTION.findall(text)), key=lambda a: float(a.split(".")[0])
            )
            title = file.stem.replace("_", " ")
            if mentioned:
                title += f" (ст. {', '.join(mentioned[:6])} ТК РФ)"
            chunks.append(
                {
                    "chunk_id": f"{source_id}_{re.sub(r'[^A-Za-z0-9]+', '_', file.stem)[:40]}_{index}",
                    "article": None,
                    "title": title,
                    "text": text,
                }
            )
    return {
        "source_id": source_id,
        "label": f"{len(files)} документ(ов)",
        "source_title": source_title,
        "source_url": source_url,
        "edition_date": edition_date.isoformat() if edition_date else None,
        "effective_from": None,
        "effective_to": None,
        "chunks": chunks,
    }
