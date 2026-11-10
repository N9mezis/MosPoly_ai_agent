"""Приём файла: проверка допустимости (Ф-01) и временное хранение до обработки (НФ-04).

Исходник лежит в общем томе uploads (api и worker) и удаляется воркером после
извлечения текста; в БД остаётся только служебная информация.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile

from app.core.errors import AppError

from .parser import parse_document

ALLOWED_SUFFIXES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
}
_MAGIC = {".docx": b"PK\x03\x04", ".pdf": b"%PDF"}


class DocumentRejected(AppError):
    status_code = 422
    code = "document_rejected"


@dataclass(slots=True)
class StoredUpload:
    storage_key: str
    path: Path
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    page_count: int | None


async def store_upload(file: UploadFile, *, upload_dir: Path, max_bytes: int) -> StoredUpload:
    filename = Path(file.filename or "").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise DocumentRejected(
            "Неподдерживаемый формат файла. Загрузите договор в формате DOCX или PDF.",
            code="unsupported_format",
        )

    data = await file.read(max_bytes + 1)
    if not data:
        raise DocumentRejected("Файл пустой. Загрузите заполненный договор.", code="empty_file")
    if len(data) > max_bytes:
        raise DocumentRejected(
            f"Файл слишком большой. Максимальный размер — {max_bytes // (1024 * 1024)} МБ.",
            code="file_too_large",
        )
    if not data.startswith(_MAGIC[suffix]):
        raise DocumentRejected(
            "Файл повреждён или его содержимое не соответствует расширению.",
            code="corrupted_file",
        )

    upload_dir.mkdir(parents=True, exist_ok=True)
    storage_key = f"{uuid.uuid4().hex}{suffix}"
    path = upload_dir / storage_key
    path.write_bytes(data)

    try:
        parsed = parse_document(path)
    except Exception as error:
        path.unlink(missing_ok=True)
        raise DocumentRejected(
            "Не удалось прочитать файл: он повреждён или защищён паролем.",
            code="corrupted_file",
        ) from error

    text_length = sum(len(block.text) for block in parsed.blocks)
    if text_length == 0:
        path.unlink(missing_ok=True)
        raise DocumentRejected(
            "В файле не найден текст. Возможно, это скан: распознавание пока не поддерживается.",
            code="no_text_layer",
        )

    pages = {block.page_number for block in parsed.blocks if block.page_number}
    return StoredUpload(
        storage_key=storage_key,
        path=path,
        filename=filename,
        mime_type=ALLOWED_SUFFIXES[suffix],
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=len(pages) or None,
    )
