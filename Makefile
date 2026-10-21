# Developer shortcuts. On Windows without make, run the underlying commands shown here.

UV := cd backend && uv run python

.PHONY: taxonomy regulation tune-classifier datasets datasets-regulation datasets-estate datasets-verify test lint runner-install runner-test runner-images

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

# Embed the personal data taxonomy into PostgreSQL (needs the database and the embedding model).
taxonomy:
	cd backend && uv run python ../scripts/load_taxonomy.py

# Embed the GDPR text into PostgreSQL (the knowledge base; needs the database and the embedding model).
regulation:
	cd backend && uv run python ../scripts/ingest_regulation.py

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
