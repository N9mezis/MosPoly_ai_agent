import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import jwt
import pytest

from app.auth import tokens
from app.core.config import Settings
from app.core.errors import UnauthorizedError

TEST_SECRET = "test-secret-with-at-least-32-bytes"


@pytest.fixture(autouse=True)
def auth_settings(monkeypatch):
    settings = Settings(auth_dev_mode=False, jwt_secret=TEST_SECRET, jwt_access_ttl_minutes=30)
    monkeypatch.setattr(tokens, "get_settings", lambda: settings)


def test_issue_tokens_stores_only_refresh_hash():
    issued = []
    user_id = uuid.uuid4()
    access, refresh, ttl = tokens.issue_tokens(
        SimpleNamespace(add=issued.append), SimpleNamespace(id=user_id)
    )
    assert tokens.decode_access(access) == user_id
    assert ttl == 1800
    assert issued[0].user_id == user_id
    assert issued[0].token_hash == tokens.token_hash(refresh)
    assert issued[0].token_hash != refresh


def test_expired_access_token_is_rejected():
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(UTC) - timedelta(seconds=1)},
        TEST_SECRET,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError):
        tokens.decode_access(token)
