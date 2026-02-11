from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["ARTIFACTS_PATH"] = str(tmp_path / "artifacts")
    os.environ["ENABLE_BACKGROUND_WORKER"] = "false"
    os.environ["SESSION_SECRET"] = "test-secret"

    from app.core.config import get_settings
    from app.core.db import reset_db_cache

    get_settings.cache_clear()
    reset_db_cache()

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def test_login_accepts_local_domain_seed_style(client: TestClient):
    from app.core.db import get_session_maker
    from app.services.auth import AuthService

    session_maker = get_session_maker()
    with session_maker() as db:
        AuthService(db).register_user("starter@lorastudio.local", "Strongpass123")

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "starter@lorastudio.local", "password": "Strongpass123"},
    )
    assert login.status_code == 200, login.text
    assert "access_token" in login.json()
