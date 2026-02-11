from __future__ import annotations

import io
import os
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'test.db'}"
    os.environ["ARTIFACTS_PATH"] = str(tmp_path / "artifacts")
    os.environ["ENABLE_BACKGROUND_WORKER"] = "false"
    os.environ["SESSION_SECRET"] = "test-secret"
    os.environ["ENABLE_METRICS"] = "true"

    from app.core.config import get_settings
    from app.core.db import reset_db_cache

    get_settings.cache_clear()
    reset_db_cache()

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def auth_bootstrap(client: TestClient) -> tuple[dict, str]:
    register = client.post(
        "/api/v1/auth/register",
        json={"email": f"owner-{uuid4().hex[:8]}@example.com", "password": "Strongpass123"},
    )
    assert register.status_code == 200, register.text
    token = register.json()["access_token"]

    auth_headers = {"Authorization": f"Bearer {token}"}
    tenant = client.post(
        "/api/v1/tenants",
        json={"name": f"Tenant-{uuid4().hex[:6]}", "namespace": f"tenant-{uuid4().hex[:6]}"},
        headers=auth_headers,
    )
    assert tenant.status_code == 200, tenant.text
    tenant_id = tenant.json()["id"]

    headers = {**auth_headers, "X-Tenant-Id": tenant_id}
    return headers, tenant_id


def create_project(client: TestClient, headers: dict) -> str:
    response = client.post(
        "/api/v1/projects",
        json={"name": "Project", "description": "desc"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_register_rejects_weak_password(client: TestClient):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "weakpass"},
    )
    assert response.status_code == 400
    assert "Password must be" in response.json()["detail"]


def test_tenant_plan_defaults_and_update(client: TestClient):
    headers, _tenant_id = auth_bootstrap(client)

    plan = client.get("/api/v1/tenants/plan", headers=headers)
    assert plan.status_code == 200, plan.text
    assert plan.json()["plan_tier"] == "starter"

    updated = client.put(
        "/api/v1/tenants/plan",
        json={"plan_tier": "pro"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    payload = updated.json()
    assert payload["plan_tier"] == "pro"
    assert payload["max_documents"] >= 5000


def test_document_quota_enforced(client: TestClient):
    headers, tenant_id = auth_bootstrap(client)
    project_id = create_project(client, headers)

    from app.core.db import get_session_maker
    from app.models import TenantPlan

    session_maker = get_session_maker()
    with session_maker() as db:
        plan = db.query(TenantPlan).filter(TenantPlan.tenant_id == tenant_id).one()
        plan.max_documents = 1
        db.commit()

    file_one = {"file": ("doc1.txt", io.BytesIO(b"policy one"), "text/plain")}
    upload_one = client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files=file_one,
        data={"metadata": "{}"},
        headers=headers,
    )
    assert upload_one.status_code == 200, upload_one.text

    file_two = {"file": ("doc2.txt", io.BytesIO(b"policy two"), "text/plain")}
    upload_two = client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files=file_two,
        data={"metadata": "{}"},
        headers=headers,
    )
    assert upload_two.status_code == 400, upload_two.text
    assert "quota" in upload_two.json()["detail"].lower()


def test_run_events_and_metrics_available(client: TestClient):
    headers, _tenant_id = auth_bootstrap(client)
    project_id = create_project(client, headers)

    file_payload = {"file": ("policy.txt", io.BytesIO(b"Returns within 30 days with receipt."), "text/plain")}
    upload = client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files=file_payload,
        data={"metadata": "{}"},
        headers=headers,
    )
    assert upload.status_code == 200, upload.text

    dataset = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "ds-v1"},
        headers=headers,
    )
    assert dataset.status_code == 200, dataset.text

    run = client.post(
        f"/api/v1/projects/{project_id}/runs",
        json={
            "dataset_version_id": dataset.json()["id"],
            "base_model_id": "mistralai/Mistral-7B-Instruct-v0.3",
            "data_rights_confirmed": True,
            "config": {
                "lora_rank": 16,
                "lora_alpha": 32,
                "lora_dropout": 0.05,
                "sequence_length": 1024,
                "per_device_batch_size": 1,
                "gradient_accumulation_steps": 8,
                "precision": "bf16",
                "epochs": 2,
                "max_steps": 0,
                "save_every_steps": 100,
                "use_4bit": True,
            },
        },
        headers=headers,
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]

    process = client.post("/api/v1/runs/process-next", headers=headers)
    assert process.status_code == 200, process.text

    events = client.get(f"/api/v1/runs/{run_id}/events", headers=headers)
    assert events.status_code == 200, events.text
    states = [row["to_state"] for row in events.json()]
    assert "queued" in states
    assert "ready" in states

    metrics = client.get("/api/v1/metrics")
    assert metrics.status_code == 200
    assert "lora_studio_requests_total" in metrics.text
