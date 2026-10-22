# ProcessLedger: Privacy Operations Platform

ProcessLedger automates the privacy documentation workflow of an organization: system inventory, discovery of the personal data each system handles, Records of Processing Activities, Data Protection Impact Assessments, and data subject access requests. The full development plan is in [PLAN_PRIVACY_OPS.md](PLAN_PRIVACY_OPS.md).

Generated legal or compliance documents are drafts for review by a qualified privacy professional. They are not legal advice. All data in this repository is demonstration data.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Database, migrations, tenant isolation (row level security) | Done |
| 2 | Authentication, authorization, security baseline | Done |
| 3 | Dataset and reference estate (`datasets/`) | Done |
| 4 | REA integration and evidence extraction (`rea-runner/`, `backend/app/discovery/`) | Done |
| 5 | Classification and the data element engine (`backend/app/classify/`) | Done |
| 6 | Knowledge base and hybrid retrieval (`backend/app/knowledge/`) | Done |
| 7 | LLM router, cache, budgets and call log (`backend/app/llm/`) | Done |
| 8 | Fusion, findings, record generation, versions, exports (`backend/app/fusion/`, `backend/app/records/`) | Done |
| 9 | Impact assessments: screening, drafting, risk register, review (`backend/app/dpia/`) | Done |
| 10 onwards | Access requests, workflow, frontend | Planned |

## Quick start (backend)

Prerequisites: Docker, Python 3.12, [uv](https://docs.astral.sh/uv/).

```
cp .env.example .env          # then set JWT_SECRET and EVIDENCE_ENCRYPTION_KEY (see the file)
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head
uv run python ../scripts/seed_demo_users.py
uv run uvicorn app.main:create_app --factory --port 8000
```

Run the tests (they start their own throwaway PostgreSQL container):

```
cd backend
uv run pytest
uv run ruff check . && uv run black --check . && uv run mypy
```

Discovery uses the pinned [REA](https://github.com/morluto/rea) release. Install it once with `cd rea-runner && npm ci` (Node 24.15 or newer); without it the backend falls back to built-in parsers and the REA tests are skipped.

Classification needs the embedding model and the taxonomy index: `cd backend && uv run python ../scripts/download_embedding_model.py && uv run python ../scripts/load_taxonomy.py`. Without the model the classification tests are skipped.

The knowledge base needs the same model plus the GDPR text: `cd backend && uv run python ../scripts/ingest_regulation.py` (or `make regulation`). The cross encoder used for optional reranking is downloaded on first use (`RERANK_ENABLED=true`); the retrieval tests that need either model are skipped when it is not cached.

Runner tests (Node 24.15 or newer): `cd rea-runner && npm test`. Container images: `make runner-images`.

Use `127.0.0.1` rather than `localhost` in database URLs; `localhost` can resolve to IPv6 first and stall on some machines.

## Dataset

`datasets/` holds the GDPR text, taxonomies, vendor registry and a fictional company with eight systems, 2,000 synthetic people and 19 seeded privacy problems. Rebuild it with `make datasets`, or `cd backend && uv run python ../datasets/scripts/run.py all`. See [datasets/README.md](datasets/README.md) for provenance, licenses and what is modeled.

## Documentation

- [docs/architecture.md](docs/architecture.md): evidence discovery with REA, the runner, commands and fallbacks.
- [docs/database.md](docs/database.md): schema, migrations and the tenancy model.
- [docs/security.md](docs/security.md): authentication, authorization, uploads, request forgery protection and runner isolation.

## Demo accounts

`scripts/seed_demo_users.py` creates one account per role (admin, analyst, system owner, viewer) in a demo organization. The default password is for local use only. Change every credential outside a local machine.

## Responsible use

The platform performs static or observational analysis of systems the organization owns or is authorized to examine. It never executes uploaded files.

## Project plan

The phase by phase plan is in [PLAN_PRIVACY_OPS.md](PLAN_PRIVACY_OPS.md). Phases 1 to 9 are complete: database and tenancy, authentication and security baseline, the dataset with the reference estate, evidence extraction, classification, the knowledge base with hybrid retrieval, the LLM router with budgets, and the comparison of questionnaire, notice and evidence with record generation and export, and impact assessments.
