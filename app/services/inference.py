from __future__ import annotations

import json
import re
import time
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.metrics import INFERENCE_REQUESTS
from app.models import Document, DocumentStatus, Project
from app.schemas import ChatResponse
from app.schemas.api import Citation
from app.services.deployment import DeploymentService


class InferenceService:
    def __init__(self, db: Session):
        self.db = db
        self.settings = get_settings()

    def chat(
        self,
        *,
        tenant_id: str,
        project_id: str,
        question: str,
        use_grounding: bool,
    ) -> ChatResponse:
        started = time.perf_counter()

        project = self.db.get(Project, project_id)
        if not project or project.tenant_id != tenant_id:
            raise ValueError("Project not found")

        deployment = DeploymentService(self.db).active_deployment(tenant_id, project_id)
        if deployment is None:
            raise ValueError("No active deployment for project")

        citations = self._retrieve_citations(tenant_id, project_id, question)
        must_ground = use_grounding and self.settings.require_grounding

        if must_ground and not citations:
            answer = "I do not have grounded evidence in the current knowledge set. Please provide more context or escalate."
            refused = True
        else:
            answer = self._generate_answer(project=project, question=question, citations=citations)
            refused = False

        INFERENCE_REQUESTS.labels(refused=str(refused).lower()).inc()
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ChatResponse(answer=answer, citations=citations, refused=refused, latency_ms=latency_ms)

    def _generate_answer(self, *, project: Project, question: str, citations: list[Citation]) -> str:
        prompt = self._compose_prompt(project, question, citations)
        if self.settings.inference_backend == "ollama":
            generated = self._chat_ollama(prompt, project.system_prompt)
            if generated:
                return generated
        return self._fallback_answer(project, question, citations)

    def _chat_ollama(self, prompt: str, system_prompt: str) -> str | None:
        payload = {
            "model": self.settings.ollama_chat_model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            with httpx.Client(timeout=45.0) as client:
                response = client.post(f"{self.settings.ollama_base_url.rstrip('/')}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
                return str((data.get("message") or {}).get("content") or "").strip() or None
        except Exception:
            return None

    def _retrieve_citations(self, tenant_id: str, project_id: str, question: str) -> list[Citation]:
        docs = list(
            self.db.scalars(
                select(Document).where(
                    Document.tenant_id == tenant_id,
                    Document.project_id == project_id,
                    Document.status.in_([DocumentStatus.READY, DocumentStatus.NEEDS_REVIEW]),
                )
            ).all()
        )

        q_tokens = set(self._tokenize(question))
        scored: list[tuple[float, str, str]] = []
        for doc in docs:
            payload = json.loads(Path(doc.normalized_text_path).read_text(encoding="utf-8"))
            text = payload.get("text", "")
            sections = payload.get("sections") or []
            content_candidates = [section.get("content", "") for section in sections[:15]] or [text]

            for chunk in content_candidates:
                chunk_tokens = set(self._tokenize(chunk))
                overlap = len(q_tokens & chunk_tokens)
                if overlap == 0:
                    continue
                score = overlap / max(len(q_tokens), 1)
                snippet = " ".join(chunk.split()[:120])
                scored.append((score, doc.id, snippet))

        scored.sort(key=lambda row: row[0], reverse=True)
        top = scored[:3]
        return [Citation(document_id=doc_id, snippet=snippet, score=round(score, 4)) for score, doc_id, snippet in top]

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return re.findall(r"[a-zA-Z0-9]{2,}", text.lower())

    @staticmethod
    def _compose_prompt(project: Project, question: str, citations: list[Citation]) -> str:
        style = "\n".join(project.style_rules) if project.style_rules else "Use concise, professional style."
        refusal = "\n".join(project.refusal_rules) if project.refusal_rules else "Refuse unsupported claims."
        evidence = "\n".join(f"[{idx+1}] {c.snippet}" for idx, c in enumerate(citations)) or "No citations available."
        return (
            "Answer the question using only the provided evidence.\n"
            f"Style rules:\n{style}\n"
            f"Refusal rules:\n{refusal}\n"
            f"Evidence:\n{evidence}\n"
            f"Question:\n{question}"
        )

    @staticmethod
    def _fallback_answer(project: Project, question: str, citations: list[Citation]) -> str:
        lead = project.system_prompt.strip()
        style = " ".join(project.style_rules) if project.style_rules else "Use concise, professional style."
        refusal = " ".join(project.refusal_rules) if project.refusal_rules else "Refuse unsupported claims."

        if not citations:
            return f"{lead} {style} {refusal} I can answer generally, but there are no explicit citations for: {question}"

        evidence = " ".join(f"[{idx+1}] {c.snippet}" for idx, c in enumerate(citations))
        return (
            f"{lead} {style} Based on grounded project documents, here is the answer: {evidence} "
            f"If a detail is missing, follow policy: {refusal}"
        )
