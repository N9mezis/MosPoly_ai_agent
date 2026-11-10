from __future__ import annotations

import pytest

from tests.paths import REPO_ROOT

pytestmark = pytest.mark.db

CONTRACT = (
    REPO_ROOT / "data" / "contracts" / "problematic" / "problematic_01_multiple_violations.docx"
)


def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_me_in_dev_mode(client):
    body = client.get("/api/v1/auth/me").json()
    assert body["role"] == "service_admin"
    assert "regulations:manage" in body["permissions"]


def test_document_types(client):
    ids = [item["id"] for item in client.get("/api/v1/document-types").json()]
    assert "employment-contract" in ids


def test_upload_valid_docx(client):
    with CONTRACT.open("rb") as file:
        response = client.post("/api/v1/documents", files={"file": (CONTRACT.name, file)})
    assert response.status_code == 201
    assert response.json()["filename"] == CONTRACT.name


@pytest.mark.parametrize(
    ("name", "content", "code"),
    [
        ("contract.txt", b"hello", "unsupported_format"),
        ("contract.pdf", b"", "empty_file"),
        ("contract.docx", b"PK\x03\x04garbage", "corrupted_file"),
        ("contract.pdf", b"not a pdf", "corrupted_file"),
    ],
)
def test_upload_rejected(client, name, content, code):
    response = client.post("/api/v1/documents", files={"file": (name, content)})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == code
    assert error["message"]


def test_error_format_for_unimplemented(client):
    response = client.post("/api/v1/auth/token", json={"email": "a@b.c", "password": "x"})
    assert response.status_code in (200, 401, 501)
    if response.status_code != 200:
        assert set(response.json()["error"]) == {"code", "message", "details"}


def test_fixture_result_matches_contract():
    """Фикстура для разработки отчётов/фронта соблюдает порядок категорий (Ф-10)."""
    from app.api.v1.fixtures import fixture_result

    categories = [finding.category.value for finding in fixture_result().findings]
    order = {"critical": 0, "recommended": 1, "info": 2}
    assert categories == sorted(categories, key=order.__getitem__)


def test_unknown_analysis_is_404(client):
    response = client.get("/api/v1/analyses/00000000-0000-4000-8000-00000000ffff")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
