"""Структурная нарезка кодекса (ТК РФ) из PDF: раздел → глава → статья → часть.

Ориентирован на PDF-выгрузки справочных систем (КонсультантПлюс и т. п.):
- абзац начинается строкой с отступом первой строки;
- заголовки «Раздел / Глава / Статья» набраны жирным шрифтом;
- служебные примечания справочной системы набраны отдельным цветом и выбрасываются
  (это не текст закона и не объект свободного использования);
- редакционные пометки «(в ред. …)», «(часть … введена …)» выбрасываются;
- нумерация частей ведётся с учётом утративших силу частей, чтобы совпадать с официальной.

Часть = абзац, начинающийся с прописной буквы после завершённого предложения;
перечисления (строчная буква, «1)», «а)») остаются внутри своей части.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

# Номера вида 22.1, 312.9 и 341.1-1 (статьи, вставленные между вставленными).
ARTICLE_HEADER = re.compile(r"^Статья\s+(?P<num>\d+(?:\.\d+)*(?:-\d+)?)\.\s*(?P<title>.*)$")
CHAPTER_HEADER = re.compile(r"^Глава\s+(?P<num>\d+(?:\.\d+)*)\.\s*(?P<title>.*)$")
SECTION_HEADER = re.compile(r"^Раздел\s+(?P<num>[IVXLC]+(?:\.\d+)?)\.?\s*(?P<title>.*)$")
EDITORIAL_NOTE = re.compile(
    r"^\((?:в\s+ред\.|введен|утратил|часть|абзац|пункт|п\.|подпункт|пп\.|наименование|"
    r"статья|глава|раздел|примечание|см\.|исключен|позиция)[^)]*.*\)\.?$",
    re.IGNORECASE | re.DOTALL,
)
NOTE_START = re.compile(
    r"^\((?:в\s+ред\.|введен|утратил|часть\s+\S+\s+(?:в\s+ред|введен|утратил)|"
    r"абзац|пункт|п\.\s*\d|подпункт|наименование|статья\s+\S+\s+(?:в\s+ред|введен))",
    re.IGNORECASE,
)
REPEALED = re.compile(r"утратил[аио]?\s+силу|исключен[аоы]?\s*\.", re.IGNORECASE)
TRAILING_NOTE = re.compile(
    r"\s*\((?:часть|абзац|пункт|подпункт|в\s+ред\.|введен)[^()]*\)\.?\s*$", re.IGNORECASE
)
SIGNATURE = re.compile(r"^(?:Президент|Российской Федерации|Москва, Кремль)", re.IGNORECASE)
LIST_START = re.compile(r"^(?:[а-яё]|\d+(?:\.\d+)?\)|[а-я]\))")
EDITION_DATE = re.compile(r"от\s+(\d{2})\.(\d{2})\.(\d{4})\s+N\s+\d+-ФЗ")

INDENT_THRESHOLD = 12.0  # pt: насколько первая строка абзаца правее левого поля


@dataclass(slots=True)
class Line:
    text: str
    x0: float
    bold: bool
    page: int
    y0: float = 0.0


@dataclass(slots=True)
class Part:
    number: int
    text: str


@dataclass(slots=True)
class Article:
    number: str
    title: str
    chapter: str = ""
    section: str = ""
    repealed: bool = False
    parts: list[Part] = field(default_factory=list)


@dataclass(slots=True)
class ParsedCode:
    articles: list[Article]
    edition_date: date | None
    edition_label: str
    dropped_notes: int = 0


def _norm(text: str) -> str:
    return " ".join(text.replace(" ", " ").replace("­", "").split())


def read_pdf_lines(path: Path) -> tuple[list[Line], int, str]:
    """Строки PDF с x0 и признаком жирного шрифта (цветные примечания выброшены),
    число выброшенных строк и сырой текст первых страниц (для даты редакции)."""
    import pymupdf  # опциональная зависимость инструмента импорта

    document = pymupdf.open(str(path))
    char_by_color: dict[int, int] = {}
    pages = []
    for page in document:
        page_dict = page.get_text("dict")
        pages.append(page_dict)
        for block in page_dict["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    char_by_color[span["color"]] = char_by_color.get(span["color"], 0) + len(
                        span["text"]
                    )
    # Основной текст — чёрный (0); ссылки — синие (255); всё прочее цветное — примечания.
    note_colors = {color for color in char_by_color if color not in (0, 255)}

    lines: list[Line] = []
    dropped = 0
    for page_number, page_dict in enumerate(pages, start=1):
        for block in page_dict["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    lines.append(Line("", line["bbox"][0], False, page_number, line["bbox"][1]))
                    continue
                kept = [s for s in spans if s["color"] not in note_colors]
                has_note = len(kept) < len(spans)
                # В примечаниях справочной системы ссылки синие: строка из примечания
                # и ссылок — тоже примечание.
                if has_note and all(s["color"] == 255 for s in kept):
                    kept = []
                if not kept:
                    dropped += 1
                    continue
                text = "".join(s["text"] for s in kept)
                bold = all("Bold" in s["font"] for s in kept)
                lines.append(Line(text, kept[0]["bbox"][0], bold, page_number, line["bbox"][1]))
    preamble = " ".join(document[i].get_text() for i in range(min(3, len(document))))
    return merge_baselines(lines), dropped, preamble


def merge_baselines(lines: list[Line], tolerance: float = 2.5) -> list[Line]:
    """Строки текста, выровненного по ширине, PyMuPDF отдаёт кусками с одной базовой
    линией. Склеиваем их обратно, иначе каждое слово выглядит как новый абзац."""
    merged: list[Line] = []
    for line in lines:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and line.text.strip()
            and previous.text.strip()
            and previous.page == line.page
            and abs(previous.y0 - line.y0) <= tolerance
        ):
            previous.text = f"{previous.text.rstrip()} {line.text.lstrip()}"
            previous.bold = previous.bold and line.bold
            previous.x0 = min(previous.x0, line.x0)
            continue
        merged.append(Line(line.text, line.x0, line.bold, line.page, line.y0))
    return merged


def _paragraphs(lines: list[Line]) -> list[tuple[str, bool]]:
    """Склеивает строки в абзацы: новый абзац — отступ, пустая строка или смена шрифта."""
    if not lines:
        return []
    margin = min(line.x0 for line in lines if line.text.strip())
    paragraphs: list[tuple[str, bool]] = []
    current: list[str] = []
    current_bold = False

    def flush() -> None:
        nonlocal current
        text = _norm(" ".join(current))
        if text:
            paragraphs.append((text, current_bold))
        current = []

    for line in lines:
        text = line.text.strip()
        if not text:
            flush()
            continue
        starts_header = line.bold and bool(
            ARTICLE_HEADER.match(text)
            or CHAPTER_HEADER.match(text)
            or SECTION_HEADER.match(text)
            or text.startswith("Статья")
        )
        indented = line.x0 - margin > INDENT_THRESHOLD
        starts_note = bool(NOTE_START.match(text))
        if current and (indented or line.bold != current_bold or starts_header or starts_note):
            flush()
        if not current:
            current_bold = line.bold
        current.append(text)
    flush()
    return paragraphs


def parse_code(lines: list[Line], *, dropped_notes: int = 0, preamble: str = "") -> ParsedCode:
    paragraphs = _paragraphs(lines)
    preamble = _norm(preamble or " ".join(text for text, _ in paragraphs[:40]))
    dates = [date(int(y), int(m), int(d)) for d, m, y in EDITION_DATE.findall(preamble)]
    edition = max(dates) if dates else None

    articles: list[Article] = []
    section = chapter = ""
    article: Article | None = None
    part_number = 0
    open_part: list[str] = []
    last_text = ""

    def close_part() -> None:
        nonlocal open_part
        if article is not None and open_part:
            article.parts.append(Part(part_number, "\n".join(open_part)))
        open_part = []

    for text, bold in paragraphs:
        if bold:
            if match := ARTICLE_HEADER.match(text):
                close_part()
                title = match.group("title").strip()
                article = Article(
                    number=match.group("num"),
                    title=title,
                    chapter=chapter,
                    section=section,
                    repealed=bool(REPEALED.search(title)) and len(title) < 120,
                )
                articles.append(article)
                part_number = 0
                last_text = ""
                continue
            if match := CHAPTER_HEADER.match(text):
                close_part()
                chapter = f"Глава {match.group('num')}. {match.group('title').strip()}"
                article = None
                continue
            if match := SECTION_HEADER.match(text):
                close_part()
                section = f"Раздел {match.group('num')}. {match.group('title').strip()}"
                article = None
                continue
        if article is None or article.repealed:
            continue
        if EDITORIAL_NOTE.match(text):
            continue
        text = TRAILING_NOTE.sub("", text).strip()
        if not text:
            continue
        if not re.search(r"[а-яё]", text):
            # «ЧАСТЬ ВТОРАЯ», продолжение заглавия главы и т. п. — не текст статьи.
            if text.startswith("ЧАСТЬ"):
                close_part()
                article = None
            continue
        if SIGNATURE.match(text) and article.number == "424" and len(text) < 40:
            close_part()
            article = None
            continue
        if REPEALED.search(text) and re.match(r"^(?:Част[ьи]|Абзац|Пункт)", text):
            close_part()
            part_number += 1  # утратившая силу часть сохраняет место в нумерации
            last_text = text
            continue

        is_list_item = bool(LIST_START.match(text))
        continues_part = is_list_item or (last_text.endswith(":") and bool(open_part))
        if open_part and continues_part:
            open_part.append(text)
        else:
            close_part()
            part_number += 1
            open_part = [text]
        last_text = text
    close_part()

    label = f"Полный текст, ред. от {edition:%d.%m.%Y}" if edition else "Полный текст"
    return ParsedCode(
        articles=articles, edition_date=edition, edition_label=label, dropped_notes=dropped_notes
    )


def to_source_json(
    code: ParsedCode,
    *,
    source_id: str = "tk_rf",
    source_title: str = "Трудовой кодекс Российской Федерации",
    source_url: str = "http://pravo.gov.ru/proxy/ips/?docbody=&nd=102074279",
    articles: set[str] | None = None,
) -> dict:
    """Формат data/regulations/*.json (см. source.example.json)."""
    chunks = []
    for article in code.articles:
        if article.repealed or not article.parts:
            continue
        if articles and article.number not in articles:
            continue
        for part in article.parts:
            chunks.append(
                {
                    "chunk_id": f"{source_id}_art_{article.number}_p{part.number}",
                    "article": article.number,
                    "part": str(part.number),
                    "title": article.title,
                    "text": part.text,
                }
            )
    return {
        "source_id": source_id,
        "label": code.edition_label,
        "source_title": source_title,
        "source_url": source_url,
        "edition_date": code.edition_date.isoformat() if code.edition_date else None,
        "effective_from": None,
        "effective_to": None,
        "chunks": chunks,
    }
