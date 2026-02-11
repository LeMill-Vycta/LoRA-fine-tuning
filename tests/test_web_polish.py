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


def test_landing_contains_breadcrumb_and_primary_sections(client: TestClient):
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert 'aria-label="Breadcrumb"' in html
    assert "Open Portal Dashboard" in html
    assert "Create Tenant Workspace" in html


def test_portal_contains_back_button_and_breadcrumb_container(client: TestClient):
    response = client.get("/portal/dashboard")
    assert response.status_code == 200
    html = response.text
    assert 'id="back-btn"' in html
    assert 'id="breadcrumbs"' in html
    assert 'id="screen-subtitle"' in html
    assert 'id="screen-prev-link"' in html
    assert 'id="screen-next-link"' in html


def test_all_portal_screens_render_navigation_shell(client: TestClient):
    for screen in ("dashboard", "documents", "datasets", "training", "evaluation", "deploy", "audit"):
        response = client.get(f"/portal/{screen}")
        assert response.status_code == 200
        html = response.text
        assert 'id="back-btn"' in html
        assert 'id="refresh-screen"' in html
        assert "Project Context" in html

