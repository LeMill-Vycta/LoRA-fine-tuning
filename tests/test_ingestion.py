from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from uuid import uuid4
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


def bootstrap(client: TestClient) -> tuple[dict, str]:
    token = client.post(
        "/api/v1/auth/register",
        json={"email": f"reviewer-{uuid4().hex[:8]}@example.com", "password": "strongpass123"},
    ).json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}
    tenant_id = client.post(
        "/api/v1/tenants",
        json={"name": f"tenant-{uuid4().hex[:8]}", "namespace": f"tenant-{uuid4().hex[:8]}"},
        headers=auth,
    ).json()["id"]
    headers = {**auth, "X-Tenant-Id": tenant_id}
    project_id = client.post(
        "/api/v1/projects",
        json={"name": "Project", "description": "desc"},
        headers=headers,
    ).json()["id"]
    return headers, project_id


def test_pii_documents_are_redaction_required(client: TestClient):
    headers, project_id = bootstrap(client)

    pii_text = "Customer SSN 123-45-6789 and email jane@example.com must remain private."
    files = {"file": ("pii.txt", io.BytesIO(pii_text.encode("utf-8")), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files=files,
        data={"metadata": "{}"},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text
    payload = upload.json()
    assert payload["status"] == "redaction_required"
    assert len(payload["pii_hits"]) >= 2


def test_exact_duplicate_is_rejected(client: TestClient):
    headers, project_id = bootstrap(client)

    text = "Standard operating procedure for intake and escalation."
    for idx in [1, 2]:
        files = {"file": (f"doc{idx}.txt", io.BytesIO(text.encode("utf-8")), "text/plain")}
        response = client.post(
            f"/api/v1/projects/{project_id}/documents/upload",
            files=files,
            data={"metadata": "{}"},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        if idx == 1:
            assert response.json()["status"] in {"ready", "needs_review"}
        else:
            assert response.json()["status"] == "rejected"
            assert response.json()["near_duplicate_of"] is not None

