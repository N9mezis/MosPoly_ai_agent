from app.domain.classifier import is_supported_employment_contract
from app.domain.models import ParsedDocument, TextBlock


def test_accepts_standard_employment_contract() -> None:
    document = ParsedDocument(
        filename="contract.docx",
        blocks=[
            TextBlock(block_id="p1", text="Трудовой договор"),
            TextBlock(block_id="p2", text="1.1 Работодатель принимает Работника."),
            TextBlock(block_id="p3", text="2.1 Место работы и трудовая функция."),
            TextBlock(block_id="p4", text="3.1 Оплата труда."),
        ],
    )

    assert is_supported_employment_contract(document)


def test_rejects_unrelated_document() -> None:
    document = ParsedDocument(
        filename="invoice.pdf",
        blocks=[TextBlock(block_id="p1", text="Счёт на оплату оборудования")],
    )

    assert not is_supported_employment_contract(document)
