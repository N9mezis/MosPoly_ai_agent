from __future__ import annotations

from .models import CheckStatus, ChunkCheckResult

STATUS_LABELS = {
    CheckStatus.VIOLATION: "Нарушение",
    CheckStatus.WARNING: "Предупреждение",
    CheckStatus.OK: "Проверено",
    CheckStatus.NOT_APPLICABLE: "Не применимо",
    CheckStatus.ERROR: "Ошибка обработки",
}


def build_markdown_report(filename: str, results: list[ChunkCheckResult]) -> str:
    visible = [
        result
        for result in results
        if result.status
        in {
            CheckStatus.VIOLATION,
            CheckStatus.WARNING,
            CheckStatus.ERROR,
        }
    ]
    lines = [f"# Отчёт по договору {filename}", ""]
    if not visible:
        lines.extend(
            [
                "Потенциальные нарушения и неоднозначные формулировки не обнаружены.",
                "",
                "Результат MVP не является юридическим заключением.",
            ]
        )
        return "\n".join(lines)

    for result in visible:
        if result.status == CheckStatus.ERROR:
            lines.extend(
                [
                    f"## {STATUS_LABELS[result.status]} в пункте {result.chunk_id}",
                    "",
                    f"**Комментарий:** {result.comment or 'пункт не проверен'}",
                    "",
                ]
            )
            continue
        lines.extend(
            [
                f"## {STATUS_LABELS[result.status]} в пункте {result.chunk_id}",
                "",
                f"**Основание:** {result.source or 'не указано'}",
                "",
                f"**Комментарий:** {result.comment or 'нет комментария'}",
            ]
        )
        if result.contract_quote:
            lines.extend(["", f"> {result.contract_quote}"])
        if result.law_quote:
            lines.extend(["", f"Нормативный фрагмент: «{result.law_quote}»"])
        lines.append("")

    lines.append("Результат MVP не является юридическим заключением.")
    return "\n".join(lines)
