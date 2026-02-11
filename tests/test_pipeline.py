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


def test_end_to_end_pipeline(client: TestClient):
    register = client.post(
        "/api/v1/auth/register",
        json={"email": f"owner-{uuid4().hex[:8]}@example.com", "password": "strongpass123"},
    )
    assert register.status_code == 200, register.text
    token = register.json()["access_token"]

    auth_headers = {"Authorization": f"Bearer {token}"}

    tenant = client.post(
        "/api/v1/tenants",
        json={"name": "Acme Health", "namespace": f"acme-health-{uuid4().hex[:8]}"},
        headers=auth_headers,
    )
    assert tenant.status_code == 200, tenant.text
    tenant_id = tenant.json()["id"]

    headers = {**auth_headers, "X-Tenant-Id": tenant_id}

    project = client.post(
        "/api/v1/projects",
        json={"name": "Policy Assistant", "description": "Ops policy"},
        headers=headers,
    )
    assert project.status_code == 200, project.text
    project_id = project.json()["id"]

    file_content = (
        "# Returns Policy\n"
        "Returns are accepted within 30 days with receipt. "
        "Escalate damaged-item disputes to support lead."
    ).encode("utf-8")
    files = {"file": ("policy.txt", io.BytesIO(file_content), "text/plain")}
    data = {"metadata": '{"department":"support","effective_date":"2026-01-20"}'}
    doc = client.post(
        f"/api/v1/projects/{project_id}/documents/upload",
        files=files,
        data=data,
        headers=headers,
    )
    assert doc.status_code == 200, doc.text
    assert doc.json()["status"] in {"ready", "needs_review"}

    dataset = client.post(
        f"/api/v1/projects/{project_id}/datasets",
        json={"name": "dataset-v1"},
        headers=headers,
    )
    assert dataset.status_code == 200, dataset.text
    dataset_id = dataset.json()["id"]

    run_payload = {
        "dataset_version_id": dataset_id,
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
    }
    run = client.post(
        f"/api/v1/projects/{project_id}/runs",
        json=run_payload,
        headers=headers,
    )
    assert run.status_code == 200, run.text
    run_id = run.json()["id"]

    process = client.post("/api/v1/runs/process-next", headers=headers)
    assert process.status_code == 200, process.text
    assert process.json()["id"] == run_id
    assert process.json()["state"] == "ready"

    deployments_before = client.get(f"/api/v1/projects/{project_id}/deployments", headers=headers)
    assert deployments_before.status_code == 200, deployments_before.text

    deployment = client.post(
        f"/api/v1/projects/{project_id}/deployments",
        json={"training_run_id": run_id, "version": "v1", "endpoint_url": "http://localhost:8000/api/v1/inference/chat"},
        headers=headers,
    )
    assert deployment.status_code == 200, deployment.text
    assert deployment.json()["status"] == "active"

    chat = client.post(
        "/api/v1/inference/chat",
        json={"project_id": project_id, "question": "What is the returns window?", "use_grounding": True},
        headers=headers,
    )
    assert chat.status_code == 200, chat.text
    assert "grounded" in chat.json()["answer"].lower()
    assert chat.json()["refused"] is False

    reports = client.get(f"/api/v1/projects/{project_id}/evaluations", headers=headers)
    assert reports.status_code == 200, reports.text
    assert len(reports.json()) == 1

    audit = client.get(f"/api/v1/projects/{project_id}/audit", headers=headers)
    assert audit.status_code == 200, audit.text
    assert len(audit.json()) >= 4

