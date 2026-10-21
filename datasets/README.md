# Datasets and the Reference Estate

This folder holds everything the platform is developed, tested and demonstrated with: the GDPR text, taxonomies, a vendor registry, and a fictional company, **Northbridge Group**, with eight systems, 2,000 synthetic people and a known set of seeded privacy problems. Everything is open, public or synthetic. No real personal data is used anywhere.

Generated legal or compliance documents in this folder carry the notice "Draft for review by a qualified privacy professional. Not legal advice."

## Contents

```
regulation/
  gdpr_articles.json         412 article and paragraph chunks of Regulation (EU) 2016/679 (built by script)
  guidance_index.md          links to regulator guidance with reuse notes and own summaries
  adequacy_countries.yaml    countries with an adequacy decision (verify before use)
  vendor_registry.yaml       domain patterns to vendor, role, country and category
  taxonomy/                  personal data categories, Article 9 categories, DPIA screening criteria
estate/
  estate.json                company profile and the list of systems with their files
  <system_id>/
    evidence/                capture.har, website_snapshot.html, JavaScript bundle, snapshot.sqlite
    policy.md                privacy notice of the system
    questionnaire.json       the system owner's answers (some incomplete or wrong on purpose)
    ground_truth.json        true data elements, recipients, retention and seeded contradictions
people/
  synthetic_people.csv       2,000 synthetic people and the systems each belongs to
  request_cases.json         10 access requests with the expected locations of the person's data
policies/
  company_privacy_policy.md  company wide policy with statements the systems contradict
  vendor_agreements/         short synthetic processor agreements (only where one is on file)
expected/                    reference outputs for the evaluation harness
evaluation/                  hand written evaluation data (classification challenge set); not regenerated
scripts/                     the build (see below)
MANIFEST.sha256              SHA-256 of every committed file in the folders above
```

The platform must never read `ground_truth.json` or `expected/` during a run. Only the evaluation harness does.

## Rebuilding

From the repository root, with Python 3.12 and [uv](https://docs.astral.sh/uv/):

```
make datasets                # everything (needs the network only if gdpr_articles.json is missing)
make datasets-estate         # offline: people, evidence, policies, questionnaires, ground truth
make datasets-regulation     # download and chunk the GDPR text again
make datasets-verify         # check the files against MANIFEST.sha256
```

Without `make` (for example on Windows):

```
cd backend
uv sync
uv run python ../datasets/scripts/run.py all          # or: estate, regulation --force, verify
```

The estate build takes a few seconds and is fully deterministic: the same seed (42), library versions (pinned in `backend/uv.lock`) and reference date (2026-10-01) give byte identical files. `backend/tests/test_datasets.py` builds the estate twice and compares every file, compares a fresh build with the committed files, and checks the ground truth against the evidence.

### How the estate is produced

1. `build_synthetic_people.py` generates the people with Faker (seed 42) and assigns them to systems with realistic overlap.
2. `seed_estate.py` loads them into one live SQLite database per system through the system's own store.
3. `capture_evidence.py` runs a small web application per system (built from the system's specification in `estate_spec.py`). A simulated browser loads its pages, submits its forms for three synthetic visitors and fires the requests its scripts would send to third parties. The pages and API responses are real output of the applications; third party responses are stubs. This writes the HAR file, the website snapshot and the JavaScript bundle.
4. `export_snapshots.py` writes a read-only SQLite snapshot with the schema and the rows of 120 people per system. The people of the 10 access request cases are always included.
5. `build_documents.py` writes the privacy notices, questionnaires, ground truth, processor agreements and reference outputs. `request_cases.py` computes the expected locations of each access request from the committed snapshots.

### What is modeled and what is built

| System | Origin |
|---|---|
| Web shop | **Modeled** on WordPress with WooCommerce: its default checkout field names, session cookie and typical third party calls |
| Web analytics | **Modeled** on Matomo: its tracking API parameters and `log_visit` style schema |
| Helpdesk and chat widget | **Modeled** on Chatwoot: its website widget payload and conversation schema |
| CRM | **Modeled** on SuiteCRM: its web-to-lead form fields and lead schema |
| Clinic appointment portal | Purpose-built (health data on purpose) |
| Newsletter service | Purpose-built (collects more than its policy states) |
| Staff desktop client | Purpose-built Electron-style app with a local SQLite store |
| HR onboarding form | Purpose-built (special category fields) |

The four open source products are **not run** to create the committed evidence. Their evidence is generated by the same machinery as the others, shaped after the products' public defaults, so the pipeline can be rebuilt on any laptop in seconds. `scripts/compose_estate.yml` and `scripts/capture_evidence.ts` are provided for recording flows against the real software. They are **not exercised by the automated tests or by the committed evidence**. Confirm each product's license and that its image tag still exists before use (the `bitnami/suitecrm` image was last published in August 2025 and may need replacing).

## Seeded contradictions

`expected/contradictions.json` lists 19 seeded problems across all eight systems, each with the finding types a correct fusion step should report and the evidence files that show it. Examples: a privacy notice that says data is shared with no one while a checkout sends hashed e-mail to an advertising platform; a questionnaire promising 12 months of retention while tickets from 2022 remain; health data with no Article 9 condition; a recipient in India with no transfer safeguard; a processor with no agreement on file; a newsletter form that pre-ticks consent.

Tests assert that the structurally derivable problems (undeclared elements and recipients, missing safeguards, agreements, retention and Article 9 conditions, stale reviews) are exactly the seeded ones, so nothing is missing and nothing unseeded exists.

## Synthetic people

2,000 people, generated with Faker and a fixed seed. Names, telephone numbers and IBANs are random and any resemblance to a real person is coincidental. E-mail addresses use the reserved `.example` suffix. IP addresses come from the `198.18.0.0/15` benchmarking range and are unique per person. National identifiers use a made-up format. Employees (about 6 percent) belong to the HR and staff desktop systems; about 8 percent of people appear in no system, which gives the access request module a negative case.

## Sources, licenses and provenance

| Item | Source | License or terms | Notes |
|---|---|---|---|
| `regulation/gdpr_articles.json` | Regulation (EU) 2016/679, Official Journal L 119, 4.5.2016 (CELEX 32016R0679). Downloaded as the official XHTML text from the Publications Office resolver `https://publications.europa.eu/resource/celex/32016R0679`, which serves EUR-Lex content. EUR-Lex itself answers automated clients with a bot challenge. | The Publications Office states that its content is available under the Creative Commons Attribution 4.0 licence (reuse allowed with acknowledgement of the source and an indication of changes) and that EUR-Lex documents are subject to its own legal notice | Changes made here: split into article and paragraph chunks, whitespace normalised, typographic quotes replaced by plain ones and long dashes replaced by a spaced hyphen. Only the text printed in the Official Journal is authentic. **The EUR-Lex specific legal notice could not be retrieved automatically; confirm it before redistributing.** The SHA-256 of the downloaded source document is recorded in the file. |
| `regulation/guidance_index.md` | Links to EDPB, ICO and CNIL publications | Own summaries only, no text copied | Read each publisher's reuse terms before copying text |
| `regulation/taxonomy/*` | Written for this project | Project license | DPIA criteria follow the structure of the EDPB guidelines in the project's own words. Re-check the current guidelines before relying on them |
| `regulation/adequacy_countries.yaml` | European Commission adequacy decisions | Facts, listed from public information | Verify against the Commission's current list before use. Reviewed for this project at the reference date |
| `regulation/vendor_registry.yaml` | Public vendor names and headquarters countries; fictional vendors use `.example` | Facts | Does not claim any certification status |
| `people/*`, `estate/*`, `policies/*`, `expected/*` | Generated by the scripts | Project license | Fictional company, synthetic data |
| Open source products named above | WordPress, WooCommerce, Matomo, Chatwoot, SuiteCRM | GPL-2.0-or-later, GPL-3.0-or-later, GPL-3.0-or-later, MIT (core), AGPL-3.0 respectively, as published by each project | Used only as models for field names and schemas. Confirm before running them |
| Faker | `faker` Python package | MIT | Pinned in `backend/uv.lock` |

## Checksums

`MANIFEST.sha256` lists the SHA-256 of every file under `estate/`, `people/`, `policies/`, `expected/` and `regulation/` in the format `<hash>  <relative path>`. Verify with `make datasets-verify` or `uv run python ../datasets/scripts/run.py verify`. After intentionally changing the specification, rebuild with `run.py estate`, which rewrites the manifest.
