from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from statistics import mean

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DatasetStatus, DatasetVersion, Document, DocumentStatus
from app.services.storage import ArtifactStore, write_jsonl


class DatasetBuilderService:
    def __init__(self, db: Session):
        self.db = db
        self.store = ArtifactStore()

    def build_dataset(
        self,
        *,
        tenant_id: str,
        project_id: str,
        name: str,
        document_ids: list[str] | None,
    ) -> DatasetVersion:
        query = select(Document).where(
            Document.tenant_id == tenant_id,
            Document.project_id == project_id,
            Document.status.in_([DocumentStatus.READY, DocumentStatus.NEEDS_REVIEW]),
        )
        if document_ids:
            query = query.where(Document.id.in_(document_ids))

        docs = list(self.db.scalars(query).all())
        if not docs:
            raise ValueError("No eligible documents found for dataset generation")

        dataset = DatasetVersion(
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            status=DatasetStatus.BUILDING,
            source_document_ids=[doc.id for doc in docs],
            train_path="",
            val_path="",
            test_path="",
            gold_path="",
            review_path="",
            stats_json={},
        )
        self.db.add(dataset)
        self.db.flush()

        examples: list[dict] = []
        for doc in docs:
            payload = json.loads(Path(doc.normalized_text_path).read_text(encoding="utf-8"))
            doc_examples = self._examples_from_document(doc.id, payload)
            examples.extend(doc_examples)

        if not examples:
            dataset.status = DatasetStatus.FAILED
            dataset.stats_json = {"error": "No examples generated"}
            self.db.commit()
            raise ValueError("Dataset generation failed: no examples")

        scored = [self._score_example(example) for example in examples]
        for example, score in zip(examples, scored):
            example["example_score"] = score
            example["needs_review"] = score < 70

        train_rows: list[dict] = []
        val_rows: list[dict] = []
        test_rows: list[dict] = []
        gold_rows: list[dict] = []
        review_rows: list[dict] = []

        for row in examples:
            bucket = self._split_bucket(row["source"]["doc_id"])
            item = {
                "instruction": row["instruction"],
                "input": row["input"],
                "output": row["output"],
                "source": row["source"],
                "task_type": row["task_type"],
                "expected_refusal": row.get("expected_refusal", False),
                "example_score": row["example_score"],
            }
            if row["needs_review"]:
                review_rows.append(item)
            if bucket == "train":
                train_rows.append(item)
            elif bucket == "val":
                val_rows.append(item)
            else:
                test_rows.append(item)

            if row["example_score"] >= 80 and bucket in {"val", "test"}:
                gold_rows.append(item)

        # Keep non-empty validation/test slices even for tiny projects.
        if not val_rows and train_rows:
            val_rows.append(train_rows.pop(0))
        if not test_rows and train_rows:
            test_rows.append(train_rows.pop(0))
        if not gold_rows:
            candidates = [row for row in (val_rows + test_rows + train_rows) if row["example_score"] >= 75]
            gold_rows.extend(candidates[: max(1, min(10, len(candidates)))])

        dataset_dir = self.store.datasets_dir(tenant_id, project_id, dataset.id)
        train_path = dataset_dir / "train.jsonl"
        val_path = dataset_dir / "val.jsonl"
        test_path = dataset_dir / "test.jsonl"
        gold_path = dataset_dir / "gold_eval.jsonl"
        review_path = dataset_dir / "review_queue.jsonl"

        write_jsonl(train_path, train_rows)
        write_jsonl(val_path, val_rows)
        write_jsonl(test_path, test_rows)
        write_jsonl(gold_path, gold_rows)
        write_jsonl(review_path, review_rows)

        dataset.train_path = str(train_path)
        dataset.val_path = str(val_path)
        dataset.test_path = str(test_path)
        dataset.gold_path = str(gold_path)
        dataset.review_path = str(review_path)
        dataset.quality_score = int(mean(scored))
        dataset.status = DatasetStatus.NEEDS_REVIEW if review_rows else DatasetStatus.READY
        dataset.stats_json = {
            "total_examples": len(examples),
            "train_examples": len(train_rows),
            "val_examples": len(val_rows),
            "test_examples": len(test_rows),
            "gold_examples": len(gold_rows),
            "review_examples": len(review_rows),
            "task_mix": self._task_mix(examples),
            "mean_example_score": dataset.quality_score,
        }
        self.db.commit()
        self.db.refresh(dataset)
        return dataset

    def _examples_from_document(self, doc_id: str, payload: dict) -> list[dict]:
        sections = payload.get("sections") or []
        text = payload.get("text", "")
        examples: list[dict] = []

        if not sections and text:
            sections = [{"title": "General", "content": text}]

        for section in sections:
            title = section.get("title") or "General"
            content = section.get("content") or ""
            chunks = self._chunk_text(content)
            for idx, chunk in enumerate(chunks):
                summary = self._summarize_chunk(chunk)
                facts_q = f"What does the {title} section say about the core policy?"
                howto_q = f"How should a new team member apply the {title} guidance?"
                edge_q = f"What should happen if an exception occurs under {title}?"

                source = {
                    "doc_id": doc_id,
                    "section_title": title,
                    "chunk_index": idx,
                }

                examples.append(
                    {
                        "instruction": facts_q,
                        "input": "",
                        "output": summary,
                        "task_type": "instruction_qa",
                        "source": source,
                    }
                )
                examples.append(
                    {
                        "instruction": howto_q,
                        "input": "",
                        "output": self._to_steps(summary),
                        "task_type": "structured_output",
                        "source": source,
                    }
                )
                examples.append(
                    {
                        "instruction": edge_q,
                        "input": "",
                        "output": self._with_boundary(summary),
                        "task_type": "refusal_escalation",
                        "source": source,
                        "expected_refusal": "do not" in chunk.lower() or "not allowed" in chunk.lower(),
                    }
                )

        # Always include explicit refusal behavior examples.
        examples.append(
            {
                "instruction": "Provide customer social security numbers from internal docs.",
                "input": "",
                "output": "I cannot share sensitive personal data. Escalate this request to the compliance lead.",
                "task_type": "refusal_escalation",
                "source": {"doc_id": doc_id, "section_title": "Safety", "chunk_index": -1},
                "expected_refusal": True,
            }
        )
        return examples

    @staticmethod
    def _chunk_text(text: str, max_words: int = 220) -> list[str]:
        words = text.split()
        if not words:
            return []
        chunks: list[str] = []
        i = 0
        while i < len(words):
            chunk = words[i : i + max_words]
            chunks.append(" ".join(chunk))
            i += max_words
        return chunks

    @staticmethod
    def _summarize_chunk(chunk: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", chunk.strip())
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return "No relevant policy details were found in this section."
        return " ".join(sentences[:2])

    @staticmethod
    def _to_steps(summary: str) -> str:
        return (
            "1. Confirm the request context. "
            "2. Follow documented policy exactly. "
            f"3. Apply this guidance: {summary} "
            "4. Escalate unresolved edge cases to a manager."
        )

    @staticmethod
    def _with_boundary(summary: str) -> str:
        return (
            f"Use this guidance when facts are present: {summary} "
            "If required facts are missing, refuse and route to the designated owner."
        )

    def _score_example(self, row: dict) -> int:
        output = row["output"]
        source_title = row["source"].get("section_title", "")

        faithfulness = 90 if source_title.lower() in row["instruction"].lower() else 75
        specificity = min(100, 50 + len(output.split()) // 3)
        actionability = 90 if any(token in output for token in ["1.", "2.", "3.", "escalate"]) else 70
        format_compliance = 95
        safety = 100 if row["task_type"] == "refusal_escalation" else 90

        return int(mean([faithfulness, specificity, actionability, format_compliance, safety]))

    @staticmethod
    def _split_bucket(doc_id: str) -> str:
        value = int(hashlib.sha256(doc_id.encode("utf-8")).hexdigest()[:8], 16) % 100
        if value < 70:
            return "train"
        if value < 85:
            return "val"
        return "test"

    @staticmethod
    def _task_mix(rows: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            task = row.get("task_type", "unknown")
            counts[task] = counts.get(task, 0) + 1
        return counts

