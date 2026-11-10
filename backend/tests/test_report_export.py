import uuid
from io import BytesIO
from urllib.parse import unquote

import pytest
from docx import Document
from pypdf import PdfReader

from app.api.v1.fixtures import fixture_result
from app.api.v1.schemas import ReportFormat
from app.core.models import UserRole
from app.core.security import CurrentUser, get_current_user
from app.reports.export import TITLE, render_report
from tests.test_pipeline_db import PROBLEMATIC, SpyLLM, _run, _upload_and_start


def _read_text(content: bytes, format: ReportFormat) -> str:
    if format is ReportFormat.DOCX:
        return "\n".join(p.text for p in Document(BytesIO(content)).paragraphs)
    return "\n".join(page.extract_text() for page in PdfReader(BytesIO(content)).pages)


@pytest.mark.parametrize("format", list(ReportFormat))
def test_report_contains_russian_text_and_findings(format):
    result = fixture_result()
    text = _read_text(render_report(result, format), format)
    assert TITLE in text
    assert "Сводка" in text
    assert "Цитата нормы" in text
    assert "Рекомендация" in text
    assert "Технические сбои" in text
    assert text.index("Критическая") < text.index("Рекомендательная")
    assert "юридическим заключением" in " ".join(text.split())


@pytest.mark.db
def test_download_real_result_and_check_access(client, monkeypatch):
    analysis_id = _upload_and_start(client, monkeypatch, PROBLEMATIC)
    url = f"/api/v1/analyses/{analysis_id}/report"
    assert client.get(url).status_code == 409
    _run(analysis_id, SpyLLM())

    for format, media_type in (
        (ReportFormat.PDF, "application/pdf"),
        (ReportFormat.DOCX, "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ):
        response = client.get(url, params={"format": format.value})
        assert response.status_code == 200
        assert response.headers["content-type"] == media_type
        assert f"filename*=UTF-8''Отчёт о проверке.{format.value}" in unquote(
            response.headers["content-disposition"]
        )
        assert PROBLEMATIC.name in _read_text(response.content, format)

    outsider = CurrentUser(uuid.uuid4(), uuid.uuid4(), UserRole.USER, "out@example.com", "Out")
    monkeypatch.setitem(client.app.dependency_overrides, get_current_user, lambda: outsider)
    assert client.get(url).status_code == 404
