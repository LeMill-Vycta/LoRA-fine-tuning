# Spec Coverage Matrix

## Core product coverage

- Web app portal: implemented (`/portal/{screen}`) with all core screens from spec.
- API backend: implemented with auth, project state, ingestion, jobs, eval, deploy, audit, plan quotas.
- Worker system: implemented with queue polling worker and atomic queued-run claim.
- Artifact store: implemented tenant/project isolated filesystem layout.
- Model runtime service: implemented with active deployment resolution + grounding-aware inference API.

## Data onboarding coverage

- Upload + type detection: yes
- Virus scan: size-gate stub (replace with ClamAV or equivalent in production)
- Extraction: yes (PDF/DOCX/TXT/MD/HTML/CSV)
- OCR fallback: quality flag stub only
- Normalization and metadata capture: yes
- Exact + near dedupe: yes (stable hashing)
- Quality scoring and PII gate: yes

## Dataset builder coverage

- Chunking and provenance: yes
- Instruction generation: yes
- Refusal/escalation examples: yes
- Example scoring and review queue: yes
- Document-level split and gold set: yes

## Training orchestrator coverage

- State machine and transitions: yes
- VRAM estimator and preflight gate: yes
- Checkpointing and packaging artifacts: yes
- Retry/cancel controls: yes
- Background queue worker: yes
- Run event timeline persistence: yes (`run_events`)

## Evaluation coverage

- Accuracy, fuzzy, semantic, refusal, unsupported claims, latency/tps: yes
- Regression against previous version: yes
- Report artifact + failure examples: yes

## Deployment coverage

- Deployment package record + active version switch: yes
- Inference routing by tenant/project: yes
- Grounding layer (RAG-lite): yes (token-overlap retrieval)
- Runtime provider abstraction: yes (`mock` or `ollama` backend)

## Security/compliance coverage

- Tenant data isolation in DB and artifact paths: yes
- PII detection + redaction required status: yes
- Audit trail for major events: yes
- Model/data rights checks at run creation: yes (gating on confirmation + approved model registry)
- Plan-based quotas: yes (docs/runs/storage)
- Password policy + normalized email: yes
- Password hashing: yes (PBKDF2) with legacy bcrypt migration
- Operator/API-key guardrails for ops endpoints: yes

## Observability coverage

- JSON structured logs: yes
- Request IDs: yes (`X-Request-Id`)
- Prometheus metrics endpoint: yes (`/api/v1/metrics`)

## Remaining gaps for full enterprise production

- Integrate real antivirus scanner and OCR engine.
- Integrate full PEFT/QLoRA trainer execution backend and distributed workers.
- Add object storage (S3/Blob), encryption keys/KMS, immutable audit retention.
- Add full migration stack (Alembic) and zero-downtime schema rollout process.
- Add billing/subscription payments and commercial invoicing workflows.
- Add CI/CD pipeline with deployment promotion gates and environment parity checks.
