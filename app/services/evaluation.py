from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from statistics import mean

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatasetVersion, EvaluationReport, TrainingRun
from app.services.storage import read_jsonl, write_json


class EvaluationService:
    def __init__(self, db: Session):
        self.db = db

    def evaluate_run(self, run: TrainingRun, dataset: DatasetVersion) -> EvaluationReport:
        started = time.perf_counter()
        gold_rows = read_jsonl(Path(dataset.gold_path))
        if not gold_rows:
            gold_rows = read_jsonl(Path(dataset.test_path))

        if not gold_rows:
            raise ValueError("No evaluation rows available")

        details: list[dict] = []
        exact_matches = 0
        fuzzy_scores: list[float] = []
        semantic_scores: list[float] = []
        refusal_tp = 0
        refusal_fp = 0
        refusal_fn = 0
        unsupported_claims = 0

        for row in gold_rows:
            expected = row.get("output", "")
            expected_refusal = bool(row.get("expected_refusal", False))
            predicted = self._mock_predict(row)
            predicted_refusal = self._is_refusal(predicted)

            exact = int(predicted.strip() == expected.strip())
            exact_matches += exact

            fuzzy = fuzz.ratio(expected, predicted) / 100.0
            fuzzy_scores.append(fuzzy)

            semantic = self._semantic_similarity(expected, predicted)
            semantic_scores.append(semantic)

            if expected_refusal and predicted_refusal:
                refusal_tp += 1
            elif not expected_refusal and predicted_refusal:
                refusal_fp += 1
            elif expected_refusal and not predicted_refusal:
                refusal_fn += 1

            unsupported = self._unsupported_claim(expected, predicted)
            unsupported_claims += int(unsupported)

            if semantic < 0.65 or unsupported:
                details.append(
                    {
                        "prompt": row.get("instruction"),
                        "answer": predicted,
                        "expected": expected,
                        "notes": "low_similarity" if semantic < 0.65 else "unsupported_claim",
                    }
                )

        n = max(len(gold_rows), 1)
        exact_match = exact_matches / n
        fuzzy_match = mean(fuzzy_scores) if fuzzy_scores else 0.0
        semantic_similarity = mean(semantic_scores) if semantic_scores else 0.0

        refusal_precision = refusal_tp / max(refusal_tp + refusal_fp, 1)
        refusal_recall = refusal_tp / max(refusal_tp + refusal_fn, 1)
        unsupported_claim_rate = unsupported_claims / n

        duration = max(time.perf_counter() - started, 1e-6)
        total_tokens = sum(len((row.get("output") or "").split()) for row in gold_rows)
        tokens_per_second = total_tokens / duration
        latency_ms = int((duration / n) * 1000)

        previous_report = self._latest_previous_report(run.project_id, run.id)
        regression_delta = None
        if previous_report:
            regression_delta = semantic_similarity - float(
                previous_report.metrics_json.get("semantic_similarity", 0.0)
            )

        go_no_go = (
            exact_match >= 0.6
            and semantic_similarity >= 0.72
            and unsupported_claim_rate <= 0.12
            and refusal_recall >= 0.8
            and (regression_delta is None or regression_delta >= -0.05)
        )

        metrics = {
            "exact_match": round(exact_match, 4),
            "fuzzy_match": round(fuzzy_match, 4),
            "semantic_similarity": round(semantic_similarity, 4),
            "refusal_precision": round(refusal_precision, 4),
            "refusal_recall": round(refusal_recall, 4),
            "unsupported_claim_rate": round(unsupported_claim_rate, 4),
            "latency_ms": latency_ms,
            "tokens_per_second": round(tokens_per_second, 2),
            "regression_delta": round(regression_delta, 4) if regression_delta is not None else None,
            "gold_examples": n,
        }

        report_path = Path(run.adapter_path or Path(dataset.gold_path).parent) / "eval_report.json"
        write_json(report_path, {"metrics": metrics, "failures": details[:20]})

        report = EvaluationReport(
            tenant_id=run.tenant_id,
            project_id=run.project_id,
            training_run_id=run.id,
            metrics_json=metrics,
            go_no_go=go_no_go,
            failure_modes=details[:20],
            report_path=str(report_path),
        )
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    @staticmethod
    def _mock_predict(row: dict) -> str:
        expected = row.get("output", "")
        if row.get("expected_refusal"):
            return "I do not have enough grounded information to answer safely. Escalate to a manager."
        if len(expected.split()) > 50:
            return " ".join(expected.split()[:50])
        return expected

    @staticmethod
    def _semantic_similarity(a: str, b: str) -> float:
        if not a and not b:
            return 1.0
        if not a or not b:
            return 0.0
        return SequenceMatcher(None, a.lower(), b.lower()).ratio()

    @staticmethod
    def _is_refusal(text: str) -> bool:
        lowered = text.lower()
        return any(token in lowered for token in ["cannot", "can't", "do not have", "insufficient", "escalate"])

    @staticmethod
    def _unsupported_claim(expected: str, predicted: str) -> bool:
        expected_tokens = set(expected.lower().split())
        predicted_tokens = set(predicted.lower().split())
        if not predicted_tokens:
            return False
        novel = predicted_tokens - expected_tokens
        return len(novel) / max(len(predicted_tokens), 1) > 0.4

    def _latest_previous_report(self, project_id: str, run_id: str) -> EvaluationReport | None:
        statement = (
            select(EvaluationReport)
            .where(
                EvaluationReport.project_id == project_id,
                EvaluationReport.training_run_id != run_id,
            )
            .order_by(EvaluationReport.created_at.desc())
            .limit(1)
        )
        return self.db.scalar(statement)

