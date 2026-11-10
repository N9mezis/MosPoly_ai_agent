from app.domain.chunker import chunk_document
from app.domain.models import ParsedDocument, TextBlock


def test_chunks_numbered_contract_clauses() -> None:
    document = ParsedDocument(
        filename="contract.docx",
        blocks=[
            TextBlock(block_id="p1", text="ТРУДОВОЙ ДОГОВОР"),
            TextBlock(block_id="p2", text="1.1 Работодатель принимает Работника."),
            TextBlock(block_id="p3", text="Дополнительное описание трудовой функции."),
            TextBlock(block_id="p4", text="2.1 Оклад составляет 80000 рублей."),
        ],
    )

    chunks = chunk_document(document)

    assert [chunk.chunk_id for chunk in chunks] == ["intro", "1.1", "2.1"]
    assert "Дополнительное описание" in chunks[1].text


def test_anonymizes_during_chunking() -> None:
    document = ParsedDocument(
        filename="contract.docx",
        blocks=[TextBlock(block_id="p1", text="1.1 Телефон +7 999 123-45-67")],
    )

    chunks = chunk_document(document)

    assert "[PHONE]" in chunks[0].text
