# Developer shortcuts. On Windows without make, run the underlying commands shown here.

UV := cd backend && uv run python

.PHONY: frontend frontend-test frontend-e2e seed-billing seed-compliance taxonomy regulation worker beat tune-classifier datasets datasets-regulation datasets-estate datasets-verify test lint runner-install runner-test runner-images

# Rebuild the whole dataset. Needs the network only if gdpr_articles.json is missing.
datasets:
	$(UV) ../datasets/scripts/run.py all

datasets-regulation:
	$(UV) ../datasets/scripts/run.py regulation --force

# Offline: people, evidence packs, policies, questionnaires, ground truth, request cases.
datasets-estate:
	$(UV) ../datasets/scripts/run.py estate

datasets-verify:
	$(UV) ../datasets/scripts/run.py verify

# Public site and sign in page (Node.js 24 or newer).
frontend:
	cd frontend && npm run dev

frontend-test:
	cd frontend && npm test && npm run lint && npm run typecheck && npm run check:dash

frontend-e2e:
	cd frontend && npm run build && npm run e2e

# Simulated demonstration history (needs the migrated database; RESET=--reset replaces a run).
seed-billing:
	cd backend && uv run python ../scripts/seed_billing_history.py $(RESET)

seed-compliance:
	cd backend && uv run python ../scripts/seed_compliance_history.py $(RESET)

# Embed the personal data taxonomy into PostgreSQL (needs the database and the embedding model).
taxonomy:
	cd backend && uv run python ../scripts/load_taxonomy.py

# Embed the GDPR text into PostgreSQL (the knowledge base; needs the database and the embedding model).
regulation:
	cd backend && uv run python ../scripts/ingest_regulation.py

# Background jobs: the worker runs the onboarding stages, beat schedules the daily reminders.
# Start the broker first: docker compose up -d redis (on Windows add --pool=solo to the worker).
worker:
	cd backend && uv run celery -A app.workers.celery_app worker -l INFO

beat:
	cd backend && uv run celery -A app.workers.celery_app beat -l INFO

# Re-tune the classifier thresholds on the reference estate (about 5 minutes).
tune-classifier:
	cd backend && uv run python ../scripts/tune_classifier.py --write

# The pinned REA release used by discovery (Node 24.15 or newer).
runner-install:
	cd rea-runner && npm ci

runner-test:
	cd rea-runner && npm test

runner-images:
	docker build -f rea-runner/Dockerfile.offline -t processledger-rea-offline:6.7.0 rea-runner
	docker build -f rea-runner/Dockerfile.browser -t processledger-rea-browser:6.7.0 rea-runner

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . ../datasets ../scripts --config pyproject.toml && uv run black --check --config pyproject.toml . ../datasets ../scripts && uv run mypy
