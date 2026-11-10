from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import get_settings
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


def test_invalid_credentials_error_format(client):
    response = client.post("/api/v1/auth/token", json={"email": "a@b.c", "password": "x"})
    assert response.status_code == 401
    assert set(response.json()["error"]) == {"code", "message", "details"}


def test_auth_login_refresh_logout(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setenv("AUTH_DEV_MODE", "false")
    monkeypatch.setenv("JWT_SECRET", "test-secret-with-at-least-32-bytes")
    get_settings.cache_clear()
    try:
        assert client.get("/api/v1/auth/me").status_code == 401
        login = client.post(
            "/api/v1/auth/token",
            json={
                "email": settings.seed_admin_email,
                "password": settings.seed_admin_password.get_secret_value(),
            },
        )
        assert login.status_code == 200
        pair = login.json()
        me = client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {pair['access_token']}"}
        )
        assert me.status_code == 200
        assert me.json()["role"] == "service_admin"

        refresh_url = "/api/v1/auth/refresh"
        old_token = {"refresh_token": pair["refresh_token"]}
        refreshed = client.post(refresh_url, json=old_token)
        assert refreshed.status_code == 200
        assert client.post(refresh_url, json=old_token).status_code == 401
        new_token = {"refresh_token": refreshed.json()["refresh_token"]}
        assert client.post("/api/v1/auth/logout", json=new_token).status_code == 204
        assert client.post(refresh_url, json=new_token).status_code == 401
    finally:
        get_settings.cache_clear()


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


def test_org_admin_cannot_access_other_org_or_escalate(client, monkeypatch):
    settings = get_settings()
    suffix = uuid4().hex
    with monkeypatch.context() as env:
        env.setenv("AUTH_DEV_MODE", "false")
        env.setenv("JWT_SECRET", "test-secret-with-at-least-32-bytes")
        get_settings.cache_clear()
        try:
            def login(email, password):
                response = client.post("/api/v1/auth/token", json={"email": email, "password": password})
                assert response.status_code == 200
                return {"Authorization": f"Bearer {response.json()['access_token']}"}

            service = login(settings.seed_admin_email, settings.seed_admin_password.get_secret_value())
            password = uuid4().hex

            def create_account(label, role):
                org = client.post(
                    "/api/v1/organizations", headers=service, json={"name": f"{label}-{suffix}"}
                )
                assert org.status_code == 201
                user = client.post(
                    "/api/v1/users",
                    headers=service,
                    json={
                        "organization_id": org.json()["id"],
                        "email": f"{label}-{suffix}@example.com",
                        "full_name": label,
                        "password": password,
                        "role": role,
                    },
                )
                assert user.status_code == 201
                return user.json()

            admin = create_account("org-admin", "org_admin")
            foreign = create_account("other-user", "user")
            headers = login(admin["email"], password)
            users = client.get("/api/v1/users", headers=headers)
            assert users.status_code == 200
            assert [user["id"] for user in users.json()["items"]] == [admin["id"]]

            own_url = f"/api/v1/users/{admin['id']}"
            assert client.patch(own_url, headers=headers, json={"full_name": "Updated"}).status_code == 200
            assert client.patch(
                f"/api/v1/users/{foreign['id']}", headers=headers, json={"is_active": False}
            ).status_code == 404
            assert client.patch(
                own_url, headers=headers, json={"role": "service_admin"}
            ).status_code == 403
            me = client.get("/api/v1/auth/me", headers=headers)
            assert me.status_code == 200
            assert me.json()["role"] == "org_admin"
        finally:
            env.undo()
            get_settings.cache_clear()
