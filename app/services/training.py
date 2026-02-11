from __future__ import annotations

import threading
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.metrics import RUN_FAILURES, RUN_TRANSITIONS
from app.models import DatasetStatus, DatasetVersion, RunEvent, RunState, TrainingRun
from app.services.audit import log_audit_event
from app.services.entitlements import EntitlementService
from app.services.evaluation import EvaluationService
from app.services.storage import ArtifactStore, write_json
from app.services.training_engine import DeploymentPackager, TrainingEngine


ALLOWED_TRANSITIONS: dict[RunState, set[RunState]] = {
    RunState.QUEUED: {RunState.PREFLIGHT, RunState.CANCELLED},
    RunState.PREFLIGHT: {RunState.STAGING, RunState.FAILED, RunState.CANCELLED},
    RunState.STAGING: {RunState.TRAINING, RunState.FAILED, RunState.CANCELLED},
    RunState.TRAINING: {RunState.EVALUATING, RunState.FAILED, RunState.CANCELLED},
    RunState.EVALUATING: {RunState.PACKAGING, RunState.FAILED, RunState.CANCELLED},
    RunState.PACKAGING: {RunState.READY, RunState.FAILED, RunState.CANCELLED},
    RunState.READY: set(),
    RunState.FAILED: {RunState.QUEUED},
    RunState.CANCELLED: {RunState.QUEUED},
}


class TrainingOrchestrator:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()
        self.store = ArtifactStore()
        self.engine = TrainingEngine()
        self.packager = DeploymentPackager()
        self._lock = threading.Lock()

    def estimate_vram(self, *, config: dict, base_model_id: str) -> dict:
        seq_factor = config.get("sequence_length", 1024) / 1024
        rank_factor = config.get("lora_rank", 16) / 16
        batch_factor = config.get("per_device_batch_size", 1) * max(config.get("gradient_accumulation_steps", 1), 1) / 8
        precision_factor = 0.78 if config.get("precision") in {"bf16", "fp16"} else 1.0
        quant_factor = 0.7 if config.get("use_4bit", True) else 1.0

        base = 4.2
        estimate = base * seq_factor * (0.7 + 0.3 * rank_factor) * (0.6 + 0.4 * batch_factor) * precision_factor * quant_factor
        safe_limit = self.settings.max_gpu_vram_gb * self.settings.vram_safety_factor
        will_fit = estimate <= safe_limit

        recommendation = "config_safe"
        if not will_fit:
            recommendation = (
                "Reduce sequence length, enable 4-bit, lower effective batch, or use cloud burst."
            )

        return {
            "estimated_gb": round(float(estimate), 2),
            "safe_limit_gb": round(float(safe_limit), 2),
            "will_fit": will_fit,
            "recommendation": recommendation,
            "base_model_id": base_model_id,
        }

    def create_run(
        self,
        *,
        tenant_id: str,
        project_id: str,
        dataset_version_id: str,
        requested_by_user_id: str,
        base_model_id: str,
        config: dict,
        data_rights_confirmed: bool,
    ) -> TrainingRun:
        if not data_rights_confirmed:
            raise ValueError("Client data rights confirmation is required")

        EntitlementService(self.db).assert_training_quota(tenant_id)

        dataset = self.db.get(DatasetVersion, dataset_version_id)
        if not dataset or dataset.tenant_id != tenant_id or dataset.project_id != project_id:
            raise ValueError("Dataset version not found")
        if dataset.status not in {DatasetStatus.READY, DatasetStatus.NEEDS_REVIEW}:
            raise ValueError("Dataset is not eligible for training")

        model_meta = self.settings.supported_models.get(base_model_id)
        if not model_meta or not model_meta.get("approved"):
            raise ValueError("Base model is not approved for deployment")

        estimate = self.estimate_vram(config=config, base_model_id=base_model_id)
        if not estimate["will_fit"]:
            raise ValueError("Training config exceeds safe VRAM limits")

        run = TrainingRun(
            tenant_id=tenant_id,
            project_id=project_id,
            dataset_version_id=dataset_version_id,
            requested_by_user_id=requested_by_user_id,
            base_model_id=base_model_id,
            config_json=config,
            state=RunState.QUEUED,
            progress=0.0,
            vram_estimate_gb=estimate["estimated_gb"],
            state_message="Queued",
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        self._record_run_event(run, from_state=None, to_state=RunState.QUEUED, message="Run queued")

        log_audit_event(
            self.db,
            tenant_id=tenant_id,
            user_id=requested_by_user_id,
            project_id=project_id,
            action="training_run_created",
            entity_type="training_run",
            entity_id=run.id,
            details={"base_model_id": base_model_id, "vram_estimate": estimate},
        )
        return run

    def cancel_run(self, run: TrainingRun, user_id: str | None = None) -> TrainingRun:
        if run.state in {RunState.READY, RunState.FAILED, RunState.CANCELLED}:
            return run
        self._transition(run, RunState.CANCELLED, "Run cancelled by user")
        self.db.commit()
        log_audit_event(
            self.db,
            tenant_id=run.tenant_id,
            user_id=user_id,
            project_id=run.project_id,
            action="training_run_cancelled",
            entity_type="training_run",
            entity_id=run.id,
            details={},
        )
        return run

    def retry_run(self, run: TrainingRun, user_id: str | None = None) -> TrainingRun:
        if run.state not in {RunState.FAILED, RunState.CANCELLED}:
            raise ValueError("Only failed or cancelled runs can be retried")
        self._transition(run, RunState.QUEUED, "Retry queued")
        run.progress = 0.0
        run.error_message = None
        self.db.commit()
        log_audit_event(
            self.db,
            tenant_id=run.tenant_id,
            user_id=user_id,
            project_id=run.project_id,
            action="training_run_retried",
            entity_type="training_run",
            entity_id=run.id,
            details={},
        )
        return run

    def process_next_queued_run(self) -> TrainingRun | None:
        with self._lock:
            run = self._claim_next_queued_run()
            if not run:
                return None
            return self._process_run(run, already_in_preflight=True)

    def _claim_next_queued_run(self) -> TrainingRun | None:
        candidate = self.db.scalar(
            select(TrainingRun.id)
            .where(TrainingRun.state == RunState.QUEUED)
            .order_by(TrainingRun.created_at.asc())
            .limit(1)
        )
        if not candidate:
            return None

        stmt = (
            update(TrainingRun)
            .where(TrainingRun.id == candidate, TrainingRun.state == RunState.QUEUED)
            .values(state=RunState.PREFLIGHT, state_message="Picked by worker")
        )
        result = self.db.execute(stmt)
        if result.rowcount != 1:
            self.db.rollback()
            return None
        self.db.commit()

        run = self.db.get(TrainingRun, candidate)
        if run:
            self._record_run_event(run, from_state=RunState.QUEUED, to_state=RunState.PREFLIGHT, message="Picked by worker")
        return run

    def _process_run(self, run: TrainingRun, already_in_preflight: bool = False) -> TrainingRun:
        dataset = self.db.get(DatasetVersion, run.dataset_version_id)
        if not dataset:
            self._fail(run, "Dataset missing")
            return run

        run_dir = self.store.runs_dir(run.tenant_id, run.project_id, run.id)
        try:
            if not already_in_preflight:
                self._transition(run, RunState.PREFLIGHT, "Validating dataset and license")
            run.progress = 0.1
            self.db.commit()
            self._run_preflight(run, dataset)

            self._transition(run, RunState.STAGING, "Staging artifacts")
            run.progress = 0.25
            write_json(
                run_dir / "run_config_snapshot.json",
                {
                    "dataset_version_id": run.dataset_version_id,
                    "dataset_hash": dataset.id,
                    "base_model_id": run.base_model_id,
                    "config": run.config_json,
                },
            )
            self.db.commit()

            self._transition(run, RunState.TRAINING, "Training adapter")
            run.progress = 0.45
            self.db.commit()

            artifacts = self.engine.run(
                output_dir=run_dir,
                base_model_id=run.base_model_id,
                dataset_paths={
                    "train": dataset.train_path,
                    "val": dataset.val_path,
                    "test": dataset.test_path,
                },
                config=run.config_json,
            )
            run.checkpoint_path = str(artifacts.checkpoint_path)
            run.adapter_path = str(artifacts.adapter_path)
            run.progress = 0.7
            self.db.commit()

            self._transition(run, RunState.EVALUATING, "Running evaluation")
            self.db.commit()
            report = EvaluationService(self.db).evaluate_run(run, dataset)
            run.eval_report_id = report.id
            run.progress = 0.85
            self.db.commit()

            self._transition(run, RunState.PACKAGING, "Building deployment package")
            package = self.packager.package(
                target_dir=run_dir / "package",
                adapter_dir=Path(run.adapter_path),
                run_manifest={
                    "run_id": run.id,
                    "dataset_version_id": run.dataset_version_id,
                    "base_model_id": run.base_model_id,
                    "eval_report_id": report.id,
                },
            )
            run.package_path = str(package)
            run.progress = 1.0

            self._transition(run, RunState.READY, "Run complete")
            self.db.commit()

            log_audit_event(
                self.db,
                tenant_id=run.tenant_id,
                user_id=run.requested_by_user_id,
                project_id=run.project_id,
                action="training_run_ready",
                entity_type="training_run",
                entity_id=run.id,
                details={"eval_report_id": run.eval_report_id, "package_path": run.package_path},
            )
            return run
        except Exception as exc:
            self._fail(run, str(exc))
            return run

    def _run_preflight(self, run: TrainingRun, dataset: DatasetVersion) -> None:
        if dataset.status not in {DatasetStatus.READY, DatasetStatus.NEEDS_REVIEW}:
            raise ValueError("Dataset status invalid for training")

        model_meta = self.settings.supported_models.get(run.base_model_id)
        if not model_meta:
            raise ValueError("Base model is not in approved registry")

        estimate = self.estimate_vram(config=run.config_json, base_model_id=run.base_model_id)
        run.vram_estimate_gb = estimate["estimated_gb"]
        if not estimate["will_fit"]:
            raise ValueError("VRAM preflight failed")

    def _transition(self, run: TrainingRun, target_state: RunState, message: str | None = None) -> None:
        if target_state not in ALLOWED_TRANSITIONS.get(run.state, set()):
            raise ValueError(f"Invalid transition from {run.state} to {target_state}")
        from_state = run.state
        run.state = target_state
        run.state_message = message
        self._record_run_event(run, from_state=from_state, to_state=target_state, message=message)
        RUN_TRANSITIONS.labels(state=target_state.value).inc()

    def _record_run_event(
        self,
        run: TrainingRun,
        *,
        from_state: RunState | None,
        to_state: RunState,
        message: str | None,
        details: dict | None = None,
    ) -> None:
        event = RunEvent(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            run_id=run.id,
            from_state=from_state.value if from_state else None,
            to_state=to_state.value,
            message=message,
            details_json=details or {},
        )
        self.db.add(event)
        self.db.commit()

    def _fail(self, run: TrainingRun, error: str) -> None:
        if run.state != RunState.FAILED:
            if RunState.FAILED not in ALLOWED_TRANSITIONS.get(run.state, set()):
                previous_state = run.state
                run.state = RunState.FAILED
                self._record_run_event(
                    run,
                    from_state=previous_state,
                    to_state=RunState.FAILED,
                    message="Run failed",
                    details={"error": error},
                )
            else:
                self._transition(run, RunState.FAILED, "Run failed")
        run.error_message = error
        run.state_message = "Run failed"
        self.db.commit()
        RUN_FAILURES.inc()

        log_audit_event(
            self.db,
            tenant_id=run.tenant_id,
            user_id=run.requested_by_user_id,
            project_id=run.project_id,
            action="training_run_failed",
            entity_type="training_run",
            entity_id=run.id,
            details={"error": error},
        )
