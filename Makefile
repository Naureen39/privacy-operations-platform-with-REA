# Developer shortcuts. On Windows without make, run the underlying commands shown here.

UV := cd backend && uv run python

.PHONY: datasets datasets-regulation datasets-estate datasets-verify test lint

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

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check . ../datasets ../scripts --config pyproject.toml && uv run black --check --config pyproject.toml . ../datasets ../scripts && uv run mypy
