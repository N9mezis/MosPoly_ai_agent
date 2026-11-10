from __future__ import annotations

import re

from .anonymizer import anonymize_text
from .models import ContractChunk, ParsedDocument, TextBlock

CLAUSE_PATTERN = re.compile(r"^\s*(?P<id>\d+(?:\.\d+)+)[.)]?\s+")
SECTION_PATTERN = re.compile(r"^\s*(?:раздел|глава)\s+(?P<id>[IVXLC\d]+)", re.IGNORECASE)


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        if end < len(text):
            sentence_end = max(text.rfind(". ", start, end), text.rfind("; ", start, end))
            if sentence_end > start + max_chars // 2:
                end = sentence_end + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap_chars, start + 1)
    return [piece for piece in pieces if piece]


def _chunk_from_blocks(
    chunk_id: str,
    blocks: list[TextBlock],
    max_chars: int,
    overlap_chars: int,
) -> list[ContractChunk]:
    text = anonymize_text("\n".join(block.text for block in blocks))
    parts = _split_long_text(text, max_chars=max_chars, overlap_chars=overlap_chars)
    page_numbers = sorted({block.page_number for block in blocks if block.page_number is not None})
    return [
        ContractChunk(
            chunk_id=chunk_id if len(parts) == 1 else f"{chunk_id}-{index}",
            text=part,
            block_ids=[block.block_id for block in blocks],
            page_numbers=page_numbers,
        )
        for index, part in enumerate(parts, start=1)
    ]


def chunk_document(
    document: ParsedDocument,
    max_chars: int = 4000,
    overlap_chars: int = 300,
) -> list[ContractChunk]:
    chunks: list[ContractChunk] = []
    current_blocks: list[TextBlock] = []
    current_id = "intro"
    generated_id = 1

    def flush() -> None:
        nonlocal current_blocks, current_id
        if current_blocks:
            chunks.extend(
                _chunk_from_blocks(
                    current_id,
                    current_blocks,
                    max_chars=max_chars,
                    overlap_chars=overlap_chars,
                )
            )
            current_blocks = []

    for block in document.blocks:
        clause_match = CLAUSE_PATTERN.match(block.text)
        section_match = SECTION_PATTERN.match(block.text)
        if clause_match or section_match:
            flush()
            current_id = (clause_match or section_match).group("id")
        elif (
            current_blocks
            and sum(len(item.text) for item in current_blocks) + len(block.text) > max_chars
        ):
            flush()
            current_id = f"chunk-{generated_id}"
            generated_id += 1
        current_blocks.append(block)

    flush()
    return chunks
