from __future__ import annotations

import json
from pathlib import Path

from app.core.config import get_settings


class ArtifactStore:
    def __init__(self) -> None:
        self.settings = get_settings()

    def tenant_project_dir(self, tenant_id: str, project_id: str) -> Path:
        path = self.settings.artifacts_path / tenant_id / project_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def raw_docs_dir(self, tenant_id: str, project_id: str) -> Path:
        path = self.tenant_project_dir(tenant_id, project_id) / "raw"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def normalized_dir(self, tenant_id: str, project_id: str) -> Path:
        path = self.tenant_project_dir(tenant_id, project_id) / "normalized"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def datasets_dir(self, tenant_id: str, project_id: str, dataset_id: str) -> Path:
        path = self.tenant_project_dir(tenant_id, project_id) / "datasets" / dataset_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def runs_dir(self, tenant_id: str, project_id: str, run_id: str) -> Path:
        path = self.tenant_project_dir(tenant_id, project_id) / "runs" / run_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def deployments_dir(self, tenant_id: str, project_id: str) -> Path:
        path = self.tenant_project_dir(tenant_id, project_id) / "deployments"
        path.mkdir(parents=True, exist_ok=True)
        return path


def write_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows

