from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.services.storage import write_json


@dataclass
class TrainingArtifacts:
    checkpoint_path: Path
    adapter_path: Path


class TrainingEngine:
    """
    Production-friendly training engine.

    - mock backend: deterministic artifact generation for CI/local smoke tests
    - command backend: executes external trainer command for real GPU jobs
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def run(
        self,
        *,
        output_dir: Path,
        base_model_id: str,
        dataset_paths: dict,
        config: dict,
    ) -> TrainingArtifacts:
        if self.settings.trainer_backend == "command":
            return self._run_command_backend(
                output_dir=output_dir,
                base_model_id=base_model_id,
                dataset_paths=dataset_paths,
                config=config,
            )
        return self._run_mock_backend(
            output_dir=output_dir,
            base_model_id=base_model_id,
            dataset_paths=dataset_paths,
            config=config,
        )

    def _run_mock_backend(
        self,
        *,
        output_dir: Path,
        base_model_id: str,
        dataset_paths: dict,
        config: dict,
    ) -> TrainingArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_dir = output_dir / "checkpoints" / "step-100"
        adapter_dir = output_dir / "adapter"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        adapter_dir.mkdir(parents=True, exist_ok=True)

        time.sleep(0.2)

        checkpoint_payload = {
            "base_model_id": base_model_id,
            "dataset_paths": dataset_paths,
            "config": config,
            "checkpoint_step": 100,
            "backend": "mock",
        }
        write_json(checkpoint_dir / "checkpoint.json", checkpoint_payload)
        write_json(adapter_dir / "adapter_config.json", {"base_model": base_model_id, "lora": config})
        (adapter_dir / "adapter_model.safetensors").write_bytes(b"mock-adapter-weights")

        return TrainingArtifacts(checkpoint_path=checkpoint_dir, adapter_path=adapter_dir)

    def _run_command_backend(
        self,
        *,
        output_dir: Path,
        base_model_id: str,
        dataset_paths: dict,
        config: dict,
    ) -> TrainingArtifacts:
        output_dir.mkdir(parents=True, exist_ok=True)
        checkpoint_dir = output_dir / "checkpoints" / "external"
        adapter_dir = output_dir / "adapter"
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        adapter_dir.mkdir(parents=True, exist_ok=True)

        template = self.settings.trainer_command_template
        if not template:
            raise ValueError("TRAINER_BACKEND=command requires TRAINER_COMMAND_TEMPLATE")

        command = template.format(
            output_dir=str(output_dir),
            adapter_dir=str(adapter_dir),
            checkpoint_dir=str(checkpoint_dir),
            train_path=dataset_paths.get("train", ""),
            val_path=dataset_paths.get("val", ""),
            test_path=dataset_paths.get("test", ""),
            base_model_id=base_model_id,
        )

        env = os.environ.copy()
        env["LORA_BASE_MODEL_ID"] = base_model_id
        env["LORA_TRAIN_PATH"] = str(dataset_paths.get("train", ""))
        env["LORA_VAL_PATH"] = str(dataset_paths.get("val", ""))
        env["LORA_TEST_PATH"] = str(dataset_paths.get("test", ""))
        env["LORA_CONFIG_JSON"] = str(config)
        env["LORA_ADAPTER_DIR"] = str(adapter_dir)
        env["LORA_CHECKPOINT_DIR"] = str(checkpoint_dir)

        result = subprocess.run(
            command,
            shell=True,
            cwd=str(output_dir),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        write_json(
            output_dir / "trainer_command_result.json",
            {
                "command": command,
                "return_code": result.returncode,
                "stdout_tail": result.stdout[-4000:],
                "stderr_tail": result.stderr[-4000:],
            },
        )

        if result.returncode != 0:
            raise ValueError(f"External trainer failed with code {result.returncode}")

        adapter_weights = adapter_dir / "adapter_model.safetensors"
        if not adapter_weights.exists():
            raise ValueError("External trainer did not produce adapter_model.safetensors")

        if not (adapter_dir / "adapter_config.json").exists():
            write_json(adapter_dir / "adapter_config.json", {"base_model": base_model_id, "lora": config})

        return TrainingArtifacts(checkpoint_path=checkpoint_dir, adapter_path=adapter_dir)


class DeploymentPackager:
    def package(
        self,
        *,
        target_dir: Path,
        adapter_dir: Path,
        run_manifest: dict,
    ) -> Path:
        target_dir.mkdir(parents=True, exist_ok=True)
        bundle_root = target_dir / "bundle"
        if bundle_root.exists():
            shutil.rmtree(bundle_root)
        bundle_root.mkdir(parents=True, exist_ok=True)

        adapter_target = bundle_root / "adapter"
        shutil.copytree(adapter_dir, adapter_target)

        write_json(bundle_root / "run_manifest.json", run_manifest)
        write_json(
            bundle_root / "inference_config.json",
            {
                "api": {"path": "/api/v1/inference/chat", "method": "POST"},
                "runtime_policy": {
                    "must_ground_facts": True,
                    "refusal_on_missing_context": True,
                },
            },
        )

        archive_path = shutil.make_archive(str(target_dir / "deployment_bundle"), "zip", root_dir=bundle_root)
        return Path(archive_path)
