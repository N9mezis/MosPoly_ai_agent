from __future__ import annotations

from pydantic import BaseModel, Field


class DocumentTypeDefinition(BaseModel):
    id: str
    title: str
    description: str
    scope: str
    allowed_extensions: list[str] = Field(default_factory=lambda: ["docx", "pdf"])
    enabled: bool = False


DOCUMENT_TYPES = (
    DocumentTypeDefinition(
        id="employment-contract",
        title="Трудовой договор",
        description=(
            "Проверка условий трудового договора: оплата труда, рабочее время, "
            "отпуск, испытательный срок и обязательные условия."
        ),
        scope="Выбранные нормы Трудового кодекса Российской Федерации",
        enabled=True,
    ),
    DocumentTypeDefinition(
        id="nda",
        title="Соглашение о конфиденциальности (NDA)",
        description=("Проверка предмета конфиденциальности, исключений, срока и ответственности."),
        scope="Профиль проверки и нормативная база ещё не подготовлены",
    ),
    DocumentTypeDefinition(
        id="service-contract",
        title="Договор оказания услуг",
        description=("Проверка предмета, порядка приёмки, оплаты, ответственности и расторжения."),
        scope="Профиль проверки и нормативная база ещё не подготовлены",
    ),
)


def list_document_types() -> list[DocumentTypeDefinition]:
    return list(DOCUMENT_TYPES)


def get_document_type(document_type_id: str) -> DocumentTypeDefinition | None:
    return next(
        (item for item in DOCUMENT_TYPES if item.id == document_type_id),
        None,
    )
