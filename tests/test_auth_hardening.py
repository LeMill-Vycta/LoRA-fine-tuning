from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import bcrypt
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


def test_register_and_login_supports_password_longer_than_72_bytes(client: TestClient):
    password = "A1" + ("x" * 90)
    email = f"longpw-{uuid4().hex[:8]}@example.com"

    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert register.status_code == 200, register.text

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    assert login.json()["access_token"]


def test_legacy_bcrypt_hash_is_accepted_and_migrated_on_login(client: TestClient):
    from app.core.db import get_session_maker
    from app.models import User

    email = f"legacy-{uuid4().hex[:8]}@example.com"
    password = "LegacyPass123"
    legacy_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")

    session_maker = get_session_maker()
    with session_maker() as db:
        user = User(email=email, hashed_password=legacy_hash, is_active=True)
        db.add(user)
        db.commit()

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text

    with session_maker() as db:
        stored = db.query(User).filter(User.email == email).one()
        assert stored.hashed_password.startswith("pbkdf2_sha256$")


def test_auth_me_returns_memberships(client: TestClient):
    email = f"owner-{uuid4().hex[:8]}@example.com"
    register = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Strongpass123"},
    )
    assert register.status_code == 200, register.text
    token = register.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme Ops", "namespace": f"acme-ops-{uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert tenant.status_code == 200, tenant.text

    me = client.get("/api/v1/auth/me", headers=auth_headers)
    assert me.status_code == 200, me.text
    payload = me.json()
    assert payload["email"] == email
    assert len(payload["memberships"]) == 1
    assert payload["memberships"][0]["tenant_id"] == tenant.json()["id"]
