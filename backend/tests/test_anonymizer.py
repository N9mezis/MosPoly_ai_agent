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
