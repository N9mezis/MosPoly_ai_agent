from app.domain.anonymizer import anonymize_text


def test_anonymizes_common_personal_data() -> None:
    text = (
        "Email: ivan@example.com, телефон +7 (999) 123-45-67, "
        "паспорт 45 01 123456, СНИЛС 123-456-789 01, ИНН 123456789012."
    )

    result = anonymize_text(text)

    assert "[EMAIL]" in result
    assert "[PHONE]" in result
    assert "[PASSPORT]" in result
    assert "[SNILS]" in result
    assert "[INN]" in result
    assert "ivan@example.com" not in result


def test_anonymizes_names_in_any_case() -> None:
    text = (
        "в лице директора Громова Олега Петровича, и Федорова Максима Олеговича; "
        "подписал Иванов И.И., согласовала Мария Сергеевна Петрова."
    )
    result = anonymize_text(text)
    for name in ("Громова", "Федорова", "Иванов", "Петрова"):
        assert name not in result
    assert result.count("[PERSON]") == 4


def test_hides_residence_address_but_keeps_workplace() -> None:
    text = (
        "Место работы: г. Москва, ул. Промышленная, д. 7.\n"
        "Работник зарегистрирован по адресу: г. Тула, ул. Ленина, д. 1, кв. 2; паспорт 45 01 123456"
    )
    result = anonymize_text(text)
    assert "ул. Промышленная" in result
    assert "Ленина" not in result
    assert "[ADDRESS]" in result
    assert "[PASSPORT]" in result


def test_legal_text_is_not_mangled() -> None:
    text = "Трудовой кодекс Российской Федерации устанавливает Правила внутреннего трудового распорядка."
    assert anonymize_text(text) == text
