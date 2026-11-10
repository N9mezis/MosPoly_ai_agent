from __future__ import annotations

from app.knowledge.text_source import chunk_paragraphs
from app.knowledge.tk_parser import Line, merge_baselines, parse_code, to_source_json

MARGIN = 57.0
INDENT = 84.0


def body(text: str, *, indent: bool = True, y: float = 0.0) -> Line:
    return Line(text, INDENT if indent else MARGIN, False, 1, y)


def header(text: str, y: float = 0.0) -> Line:
    return Line(text, MARGIN, True, 1, y)


def blank() -> Line:
    return Line("", MARGIN, False, 1, 0.0)


def lines_fixture() -> list[Line]:
    return [
        header("Глава 11. ЗАКЛЮЧЕНИЕ ТРУДОВОГО ДОГОВОРА"),
        blank(),
        header("Статья 70. Испытание при приеме на работу"),
        blank(),
        body("(в ред. Федерального закона от 30.06.2006 N 90-ФЗ)", indent=False),
        blank(),
        body("При заключении трудового договора в нем по соглашению сторон может быть"),
        body("предусмотрено условие об испытании.", indent=False),
        body("Часть вторая утратила силу. - Федеральный закон от 01.01.2020 N 1-ФЗ."),
        body("Испытание при приеме на работу не устанавливается для:"),
        body("беременных женщин;"),
        body("лиц, не достигших возраста восемнадцати лет;"),
        body("(в ред. Федерального закона от 02.07.2013 N 185-ФЗ)", indent=False),
        body(
            "Срок испытания не может превышать трех месяцев. (часть введена Федеральным "
            "законом от 01.01.2020 N 1-ФЗ)"
        ),
        blank(),
        header("Статья 71. Утратила силу. - Федеральный закон от 01.01.2020 N 1-ФЗ."),
        blank(),
        header("Статья 72. Изменение"),
        body("Изменение определенных сторонами условий допускается по соглашению сторон."),
    ]


def test_parses_articles_parts_and_repealed_numbering() -> None:
    code = parse_code(lines_fixture(), preamble="(в ред. от 31.07.2025 N 306-ФЗ)")
    by_number = {article.number: article for article in code.articles}

    article = by_number["70"]
    assert article.title == "Испытание при приеме на работу"
    assert article.chapter.startswith("Глава 11")
    assert [part.number for part in article.parts] == [1, 3, 4]
    assert article.parts[0].text.endswith("условие об испытании.")
    assert article.parts[1].text.splitlines() == [
        "Испытание при приеме на работу не устанавливается для:",
        "беременных женщин;",
        "лиц, не достигших возраста восемнадцати лет;",
    ]
    assert article.parts[2].text == "Срок испытания не может превышать трех месяцев."
    assert by_number["71"].repealed
    assert code.edition_date.isoformat() == "2025-07-31"


def test_source_json_skips_repealed_and_filters_articles() -> None:
    code = parse_code(lines_fixture())
    data = to_source_json(code)
    assert {chunk["article"] for chunk in data["chunks"]} == {"70", "72"}
    assert data["chunks"][0]["chunk_id"] == "tk_rf_art_70_p1"
    assert not any("в ред." in chunk["text"] for chunk in data["chunks"])
    only = to_source_json(code, articles={"72"})
    assert [chunk["article"] for chunk in only["chunks"]] == ["72"]


def test_justified_fragments_are_merged_into_one_line() -> None:
    fragments = [
        Line("Ежегодный", INDENT, False, 1, 100.0),
        Line("основной", 200.0, False, 1, 100.4),
        Line("отпуск", 300.0, False, 1, 100.2),
        Line("предоставляется работникам.", MARGIN, False, 1, 114.0),
    ]
    merged = merge_baselines(fragments)
    assert [line.text for line in merged] == [
        "Ежегодный основной отпуск",
        "предоставляется работникам.",
    ]
    assert merged[0].x0 == INDENT


def test_free_text_chunks_overlap_by_paragraph() -> None:
    paragraphs = ["а" * 600, "б" * 600, "в" * 600]
    chunks = chunk_paragraphs(paragraphs, target=1000)
    assert len(chunks) == 3
    assert chunks[1].startswith("а" * 600)
