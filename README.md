# LoRA Studio

LoRA Studio is a production-grade development baseline for **LoRA Fine-Tuning for Niche Expertise**.

It turns client knowledge into:

1. versioned LoRA adapter artifacts
2. evaluation reports with go/no-go
3. deployable inference bundles with tenant-safe routing

## ELI10: What this app does

Think of this as a training factory for a company AI assistant.

1. You upload company documents.
2. The app cleans/checks them (duplicates, quality, PII risk).
3. It creates training examples from those docs.
4. It runs a controlled LoRA training pipeline.
5. It evaluates the result and saves a report.
6. It packages a deployable version and serves it behind tenant isolation.

## Production hardening added

- Structured JSON logging with request IDs
- Prometheus metrics middleware + `/api/v1/metrics`
- Operator-token support for sensitive run-processing endpoint
- Optional API key protection for metrics endpoint
- Password policy enforcement (8+ chars, letter + number)
- PBKDF2 password hashing (no bcrypt 72-byte limit for new passwords)
- Legacy bcrypt login support with automatic hash migration on successful login
- Tenant plan/entitlement model with quotas
  - document count quota
  - monthly training-run quota
  - storage quota
- Atomic queued-run claim to reduce multi-worker race conditions
- Run event timeline table + `GET /api/v1/runs/{run_id}/events`
- Configurable inference backend (`mock` or `ollama`)
- Configurable trainer backend (`mock` or external command template)
- Deterministic/stable near-duplicate hashing in ingestion

## Core capabilities

- Multi-tenant auth + RBAC (`owner`, `manager`, `reviewer`, `viewer`)
- Tenant/project scoped artifact isolation
- Document onboarding (PDF/DOCX/TXT/MD/HTML/CSV)
- Dataset builder (instruction/structured/refusal examples + review queue)
- Training orchestrator state machine
  - `QUEUED -> PREFLIGHT -> STAGING -> TRAINING -> EVALUATING -> PACKAGING -> READY`
- Evaluation metrics (exact/fuzzy/semantic/refusal/unsupported claim rate/regression)
- Deployment version activation and inference routing
- Audit log for high-value actions

## Quickstart

```bash
python -m pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Open:

- UI: `http://localhost:8000/`
- API docs: `http://localhost:8000/docs`

## Seed plan-tier test accounts

```bash
python scripts/seed_demo.py
```

This seeds one tenant+project per plan account and prints IDs/quotas.

Accounts (shared password):

- `starter@lorastudio.local`
- `standard@lorastudio.local`
- `pro@lorastudio.local`
- `enterprise@lorastudio.local`

Password:

- `TestPass123!`

## Plan quotas

- `starter`: 200 docs, 10 runs/month, 2048 MB
- `standard`: 1000 docs, 50 runs/month, 10240 MB
- `pro`: 5000 docs, 200 runs/month, 51200 MB
- `enterprise`: 50000 docs, 5000 runs/month, 512000 MB

## Environment highlights

- `API_KEY`: optional API key gate (used by `/api/v1/metrics`)
- `OPERATOR_TOKEN`: optional extra guard for `/api/v1/runs/process-next`
- `PASSWORD_PBKDF2_ITERATIONS`: PBKDF2 work factor for password hashing
- `INFERENCE_BACKEND`: `mock` or `ollama`
- `TRAINER_BACKEND`: `mock` or `command`
- `TRAINER_COMMAND_TEMPLATE`: required when trainer backend is `command`

See `.env.example` for the full list.

## Testing

```bash
python -m pytest -q
```

Current suite includes:

- end-to-end pipeline run
- ingestion/PII/dedup checks
- password policy enforcement
- long-password auth regression (>72 bytes)
- legacy bcrypt migration regression
- tenant plan update + quota enforcement
- run event timeline endpoint
- metrics endpoint availability

## Docker

```bash
docker compose up --build
```

## Notes on real training/inference

- `TRAINER_BACKEND=mock` is deterministic for CI/local testing.
- `TRAINER_BACKEND=command` lets you plug in a real GPU LoRA command.
- `INFERENCE_BACKEND=ollama` enables runtime generation through Ollama.

## Manual validation flow

1. Run `python scripts/seed_demo.py`.
2. Login in UI with a seeded plan account.
3. Portal auto-loads tenant/project context from your memberships.
4. Upload docs, build dataset, queue run, process run.
5. Check run events, evaluation report, deployment activation, and chat inference.
6. Verify audit log entries and metrics endpoint.
