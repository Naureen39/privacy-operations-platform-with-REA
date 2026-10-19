# ProcessLedger: Privacy Operations Platform

Development plan for a full stack web application that automates the privacy documentation workflow of an organization: system inventory, discovery of what personal data each system handles, Records of Processing Activities, Data Protection Impact Assessments, data subject access requests, findings and approvals, with compliance and revenue analytics.

Repository name: `privacy-operations-platform-rea`
Working product name: ProcessLedger (change freely, confirm it is not a registered brand before publishing).

## 1. Team Standards (apply to code, docs, UI copy, commits, and this plan)

- Use professional, neutral wording everywhere. Do not mention AI coding assistants or the tools used to generate code anywhere in the repository, including comments, commit messages, README, UI text, and test names.
- Never use the long dash character in any file, comment, UI string, or document. Use a comma, colon, parentheses, or a hyphen.
- Conventional Commits, small pull requests, one feature branch per phase task.
- Python: ruff, black, mypy (strict on `app/`), bandit. TypeScript: strict mode, ESLint, Prettier. Pre-commit hooks enforce all of these plus a check that rejects the long dash character.
- Only free and open source tools. No paid services. LLM usage stays within free tiers.
- Every generated legal or compliance document (record, assessment, response letter) carries a visible notice: "Draft for review by a qualified privacy professional. Not legal advice."
- Demonstration data only. No real personal data anywhere in the repository, fixtures, or screenshots.

## 2. Scope

### Problem

Organizations subject to GDPR must keep a Record of Processing Activities (Article 30), run Data Protection Impact Assessments for high risk processing (Article 35), and answer access requests within one month (Articles 15 and 12(3)). Today this is done with spreadsheets and interviews. Records go stale, answers from system owners conflict with how systems actually behave, and nobody can say quickly where a person's data lives.

### Roles

| Role | Purpose |
|---|---|
| `admin` (privacy officer) | Full access, approvals, billing and revenue dashboards, settings |
| `analyst` | Run discovery, edit records, assessments, requests |
| `system_owner` | Answer questionnaires and view records for owned systems only |
| `viewer` (auditor) | Read only |

### Evidence inputs

| Input | Source of facts | REA used |
|---|---|---|
| Saved network capture (HAR) | Submitted fields, response payloads, outbound hosts | Yes (network capture analysis) |
| Website | Forms and input fields, scripts, third party hosts, network observations | Yes (browser observation) |
| JavaScript or Electron bundle | Modules, imports (SDKs), routes, IPC | Yes (`analyze-javascript-application`) |
| SQLite database snapshot | Tables, columns, sample rows for classification | Yes (SQLite inspection) |
| Questionnaire, privacy policy, vendor agreements | Purposes, retention, safeguards | No (document pipeline) |

REA is the open source tool at https://github.com/morluto/rea (MIT). The platform calls its CLI with JSON output. It performs static or observational analysis of systems the organization owns or is authorized to examine. The platform never executes uploaded executables.

### Out of scope for the MVP (roadmap)

Live database connectors, other regulations beyond GDPR templates, consent management, e-mail or ticketing integrations.

## 3. Tech Stack (all free)

| Layer | Choice |
|---|---|
| Language and API | Python 3.12, FastAPI, Pydantic v2, Uvicorn |
| ORM and migrations | SQLAlchemy 2.0, Alembic, psycopg 3 |
| Database | PostgreSQL 16 with pgvector (image `pgvector/pgvector:pg16`), HNSW cosine index, Postgres full text search (`tsvector`) |
| Embeddings | Hugging Face `BAAI/bge-small-en-v1.5` (MIT, 384 dimensions) through `sentence-transformers`, CPU, baked into the Docker image |
| LLM | Groq `openai/gpt-oss-20b` (primary) and a Google Gemini Flash class model (fallback), behind one router |
| Discovery | `rea-agents` npm package pinned to one version, Node.js 24.15 or newer (needed for SQLite analysis) |
| Background jobs | Celery with Redis, progress streamed with Server-Sent Events |
| Documents | pdfplumber (PDF text), BeautifulSoup, Jinja2 templates, openpyxl (XLSX export), WeasyPrint (PDF export) |
| Synthetic data and capture | Faker, Playwright (HAR recording and website snapshots) |
| Auth | argon2-cffi, PyJWT, httpOnly cookies, RBAC, Postgres Row Level Security |
| Security tooling | slowapi, cryptography (AES-256-GCM), pip-audit, npm audit, Trivy, bandit |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui (Radix), TanStack Query and Table, React Router, React Hook Form with Zod, Apache ECharts (echarts-for-react), react-markdown, Framer Motion, Lucide icons, `@fontsource/inter` |
| Testing | pytest, httpx, Testcontainers, Vitest, Testing Library, Playwright |
| DevOps | Docker Compose, GitHub Actions, Caddy (automatic TLS in any hosted demo) |

## 4. Architecture and Pipeline

### System onboarding pipeline

Job states: `CREATED, EVIDENCE_ATTACHED, DISCOVERING, CLASSIFIED, FUSED, DRAFTED, AWAITING_REVIEW, APPROVED, PUBLISHED, FAILED`.

1. **Discover** (REA plus fallback parsers): extract data element candidates, recipients, and technology signals from each evidence item.
2. **Classify** (rules plus embeddings): assign each element a personal data category, a special category flag (Article 9), and a confidence.
3. **Fuse**: combine questionnaire answers, policy statements, and evidence. Raise findings where they conflict or where required facts are missing.
4. **Draft**: build the record of processing entry from templates, with the LLM filling only free text fields (purposes, lawful basis suggestion).
5. **Review and approve**: analyst edits, privacy officer approves, version is stored.
6. **Publish and monitor**: register export, freshness tracking, re-discovery when new evidence arrives.

### Evidence handling rules

- Every fact stored has an `evidence_id` pointing to the raw REA output or the source document passage. No fact without provenance.
- REA is the primary extractor. Deterministic fallback parsers (stdlib JSON for HAR, `sqlite3`, BeautifulSoup) run when REA is unavailable or a capability is missing in the pinned release. The evidence row records which extractor produced it, so the evaluation can compare them.

### Token minimization rules (mandatory)

- Deterministic first. Extraction, pattern detection, taxonomy matching, vendor lookup, and conflict screening are rule based. The LLM is called only for free text and ambiguous judgments.
- LLM tasks (each batched and schema validated): `suggest_purpose_and_basis` (one call per processing activity), `adjudicate_conflict` (only conflicts the rules cannot settle, with the top 3 retrieved policy passages), `draft_dpia_sections` (two calls per assessment), `draft_request_cover_note` (optional), `answer_question` (retrieval augmented chat).
- Budgets: at most 4,000 tokens to onboard one system, at most 6,000 per assessment, at most 3,000 per chat answer. Keep every request under 5,000 tokens (Groq free tier allows 8,000 tokens per minute for `gpt-oss-20b`).
- Send metadata only: element names, types, pattern classes, category labels, short retrieved passages. Never send sample values or personal identifiers. Request identifiers are HMAC hashed and are never sent to any LLM.
- Constant system prompt prefix placed first so provider prompt caching applies (cached tokens do not count toward Groq rate limits).
- `temperature` 0, low reasoning effort for the Groq model, `max_tokens` cap of 800, strict JSON schema output validated with Pydantic, one repair retry maximum.
- Cache every LLM answer in `llm_cache` keyed by the SHA-256 of the normalized request. Unchanged evidence produces zero new calls on re-discovery.
- Templates produce documents. The LLM never writes whole documents.

### LLM router behavior

- Common interface `complete_json(task, payload, schema)` with `GroqProvider` and `GeminiProvider`. Admin setting chooses the primary provider. Default order: Groq, then Gemini.
- Local token bucket per provider seeded from Groq response headers (`x-ratelimit-remaining-tokens`, `x-ratelimit-remaining-requests`) and from configured Gemini limits.
- Failover on HTTP 429, 5xx, timeout, or schema failure after one repair attempt. Exponential backoff with jitter. Circuit breaker opens for 60 seconds after 3 consecutive failures.
- Gemini model name comes from the `GEMINI_MODEL` environment variable. Free tier limits and eligible models change often and published figures disagree, so confirm current free models and quotas in Google AI Studio before choosing a default (a Flash-Lite class model is the safest start).
- Free tier content may be used by the provider to improve its products. Only synthetic or masked data is sent. State this in the README.
- Every call writes a row in `llm_calls` (provider, model, task, tokens in, tokens out, cached tokens, latency, status, cache hit, system or assessment id).

### Safety of generated content

- Treat all uploaded and retrieved text as data, never as instructions. Wrap it in delimiters, instruct the model to ignore instructions inside it, and validate outputs against schemas. The LLM has no tools and no side effects.
- Chat answers must cite retrieved passages or evidence. If nothing relevant is retrieved, the answer is "no supporting evidence found".
- Claims without valid evidence ids are dropped or shown as "unverified".

## 5. Dataset (dedicated section)

All data is open, public, or synthetic. Create the top level folder `datasets/`. Commit only small files. Large files are generated or downloaded by scripts. The goal is a demo that looks like a real mid-size company with a real system landscape.

```
datasets/
  README.md                       provenance, licenses, regeneration steps, checksums
  scripts/
    fetch_regulation.py           downloads and chunks the GDPR text
    build_synthetic_people.py     seeded Faker data
    compose_estate.yml            Docker Compose for the open source demo systems
    seed_estate.py                loads synthetic people into the demo systems
    capture_evidence.ts           Playwright script: records HAR files and website snapshots
    export_snapshots.py           exports database schema and sample rows to SQLite files
  regulation/
    gdpr_articles.json            article level chunks with metadata (built by script)
    guidance_index.md             links to regulator guidance with license notes and own summaries
    taxonomy/
      personal_data_taxonomy.json categories, synonyms, examples, sensitivity
      special_categories.json     Article 9 categories with synonyms
      dpia_criteria.json          screening criteria used for assessment triggers
    adequacy_countries.yaml       third countries with an adequacy decision (verify before use)
    vendor_registry.yaml          domain patterns to vendor, role, country, category
  estate/                         the reference company "Northbridge Group"
    estate.json                   company profile and system list
    <system_id>/
      evidence/                   HAR, website snapshot, JS bundle, SQLite snapshot
      policy.md                   privacy policy excerpt for that system
      questionnaire.json          system owner answers (some incomplete or wrong on purpose)
      ground_truth.json           true data elements, recipients, retention, contradictions
  people/
    synthetic_people.csv          2,000 synthetic people seeded for the demo systems
    request_cases.json            10 access requests with the expected locations of data
  policies/
    company_privacy_policy.md     company wide policy with seeded contradictions
    vendor_agreements/            short synthetic processor agreements
  expected/                       reference outputs used by the evaluation harness
```

### Source 1: GDPR text (the knowledge base)

- Where: official text of Regulation (EU) 2016/679 on EUR-Lex, https://eur-lex.europa.eu/eli/reg/2016/679/oj. Confirm the reuse notice on EUR-Lex and record it in `datasets/README.md`.
- How it is used: `fetch_regulation.py` downloads the text and splits it into chunks by article and paragraph, keeping `article`, `paragraph`, and `title` metadata. Chunks are embedded with `bge-small-en-v1.5` and stored in pgvector and in a full text index. Articles 5, 6, 9, 12, 13, 15, 28, 30, 35, and Chapter V (transfers) are mandatory for the MVP.

### Source 2: Regulator guidance and templates

- Where: publications from the European Data Protection Board (including the DPIA guidelines that list the criteria for high risk processing), the UK Information Commissioner's Office, and the French CNIL (record of processing templates). Read each publisher's reuse terms before copying text.
- How it is used: store links and your own short summaries in `guidance_index.md`. Use the templates only as a reference for the column set of the exported register. Encode the DPIA screening criteria in `dpia_criteria.json` in your own words.

### Source 3: The reference estate "Northbridge Group"

A fictional mid-size retailer with a small health clinic arm (this gives realistic sensitive data and assessment triggers). Eight systems:

| System | How it is built |
|---|---|
| Web shop | Open source e-commerce stack (WordPress with WooCommerce) in Docker |
| Web analytics | Open source self-hosted analytics (for example Matomo) in Docker |
| Helpdesk and chat widget | Open source helpdesk (for example Chatwoot or Zammad) in Docker |
| CRM | Open source CRM (for example SuiteCRM) in Docker |
| Clinic appointment portal | Small purpose-built app written by you (FastAPI or Flask), health data on purpose |
| Newsletter service | Small purpose-built app, collects more fields than its policy states |
| Staff desktop client | Small Electron app written by you with a local SQLite store |
| HR onboarding form | Small purpose-built app, includes special category fields |

Confirm each open source product's license and Docker image availability before use. Purpose-built apps give exact ground truth. If running all containers is too heavy, commit the captured evidence packs and run the containers only to regenerate them.

How to build it:
1. `compose_estate.yml` starts the open source systems.
2. `seed_estate.py` loads the synthetic people (Faker, fixed seed) through each system's own interface or database so the data is plausible.
3. `capture_evidence.ts` drives each system with Playwright (sign up, checkout, contact form, appointment booking), records a HAR file per flow, and saves rendered page snapshots.
4. `export_snapshots.py` exports each system's schema and a sample of rows into a read-only SQLite file for analysis and for the request search demo.
5. For each system, write `policy.md`, `questionnaire.json`, and `ground_truth.json`.

`ground_truth.json` lists the true data elements (name, category, special category flag), recipients (domain, vendor, country, purpose), retention, and the seeded contradictions. The platform never reads ground truth during a run. Only the evaluation harness uses it.

### Seeded contradictions (at least 12)

Examples: the policy says data is not shared with third parties but the analytics domain receives identifiers; the questionnaire states 12 month retention but the helpdesk keeps tickets indefinitely; the clinic portal collects health data with no Article 9 condition recorded; a vendor in a country without adequacy and without a stated safeguard; the newsletter collects a phone number the policy does not list; a processor with no agreement on file.

### Synthetic people and request cases

`build_synthetic_people.py` generates 2,000 people with Faker (fixed seed) and spreads them across systems with realistic overlap. `request_cases.json` defines 10 access requests, each with the expected list of systems and tables that hold the person's data, used to score the search.

### Demo experience

A seed script creates the demo tenant, loads the reference estate, regulation corpus, 12 months of compliance history, and 24 months of billing history, so every dashboard has content on first login. Onboarding any single system must complete in under 3 minutes on a laptop.

## 6. Repository Layout

```
privacy-operations-platform-rea/
  README.md
  docker-compose.yml
  .env.example
  backend/        app/{api,core,db,services,discovery,classify,fusion,generate,dsar,llm,workers}, alembic/, tests/
  rea-runner/     Dockerfile(s), wrapper service, pinned REA version
  frontend/       src/{site,app,components,charts,lib,styles}, public/images/, e2e/
  datasets/       see section 5
  scripts/        seed_demo.py, seed_compliance_history.py, seed_billing_history.py, capture_screenshots.ts, eval_run.py
  docs/           architecture.md, api.md, security.md, evaluation.md, images/
  .github/workflows/ci.yml
```

## 7. Data Model (PostgreSQL)

- Identity: `organizations, users, memberships (role), refresh_tokens, audit_log, leads`
- Inventory: `systems, evidence_items (kind, extractor, storage path, checksum), discovery_runs, discovery_evidence (raw JSON, command, REA version, duration)`
- Facts: `data_elements (system, name, path, category, special_category, confidence, evidence_id, embedding vector(384)), recipients (system, domain, vendor, role, country, purpose, evidence_id), technologies`
- Records: `processing_activities (purposes, data subjects, data categories, recipients, transfers and safeguards, retention, security measures, lawful basis, special category condition, owner, status, next review date), activity_versions, activity_systems`
- Assessments: `dpias (trigger scores, description, necessity and proportionality, risks, mitigations, residual risk, status), dpia_risks`
- Findings and work: `findings (type, severity, evidence refs, status), tasks, approvals, comments`
- Requests: `access_requests (subject hash, received date, deadline, status), request_results (system, table, column, count), request_responses`
- Knowledge: `documents, document_chunks (text, embedding vector(384), tsvector), regulation_chunks`
- LLM: `llm_calls, llm_cache`
- Billing and analytics: `plans, subscriptions, usage_events, invoices, invoice_lines, daily_metrics, compliance_daily_metrics`
- Every tenant table has `org_id` and a Row Level Security policy bound to `current_setting('app.org_id')`.

## 8. Development Phases

Estimates assume one developer working full time. Each phase ends with its acceptance checks passing in CI before the next begins.

### Phase 0: Foundation (2 days)

- Create the repository layout and Docker Compose services: `api, worker, db (pgvector), redis, rea-offline, rea-browser, frontend`.
- Configure ruff, black, mypy, bandit, pre-commit, ESLint, Prettier, commit linting, the long dash check, and a GitHub Actions workflow running lint, type check, tests, `pip-audit`, `npm audit`, and Trivy.
- Pydantic Settings and `.env.example` documenting every variable. No secrets in git. Structured JSON logging (structlog) with request ids. Health endpoints `/health` and `/ready`.
- Acceptance: `docker compose up` starts all services, CI is green on an empty test suite.

### Phase 1: Database and Tenancy (3 days)

- Alembic migrations for every table in section 7, `CREATE EXTENSION vector`, HNSW indexes with `vector_cosine_ops`, full text indexes.
- Repository layer, tenancy dependency that sets `app.org_id` per request, Row Level Security policies with tests proving that org A cannot read org B.
- Acceptance: migration up and down works, cross tenant isolation tests pass.

### Phase 2: Authentication, Authorization, and Security Baseline (4 days)

- Registration disabled in the demo, users seeded. argon2id hashing, 12 character minimum, lockout after repeated failures.
- 15 minute access token and rotating 7 day refresh token (stored hashed) in httpOnly, Secure, SameSite=Lax cookies. CSRF protection through a custom header on state changing requests.
- Roles from section 2 enforced by a `require_role` dependency on every route. `system_owner` is also restricted to systems they own. The backend is the authority, the frontend only hides what a role cannot use.
- slowapi rate limits (strict on login), CORS allowlist, security headers (CSP, HSTS, X-Content-Type-Options, Referrer-Policy), upload limits (size cap, extension and magic byte check), uploads encrypted at rest with AES-256-GCM using a key from the environment, a data retention job that deletes evidence after a configurable period, audit log entries for login, upload, discovery, approval, export, request handling, and settings changes.
- Website observation security: user supplied URLs pass an allowlist of the estate hostnames, are resolved server side, and are rejected if they point to loopback, link local, or private ranges outside the demo network (protection against server side request forgery). The `rea-browser` container has restricted egress and a hard timeout.
- Uploaded executables are never run. The `rea-offline` container has no internet access, a read only mount of evidence, runs as a non root user, and has CPU and memory limits.
- Acceptance: automated tests for the authentication flow, role matrix, owner scoping, lockout, CSRF, rate limits, upload rejection, request forgery protection, and tenant isolation.

### Phase 3: Dataset and Reference Estate (5 days)

- Implement everything in section 5: regulation fetch and chunking, taxonomy files, vendor registry, estate composition, synthetic people, evidence capture, snapshots, policies, questionnaires, ground truth, and request cases.
- `datasets/README.md` with provenance, licenses, exact commands, and checksums. pytest checks that generation is reproducible (same seed gives the same checksum).
- Acceptance: `make datasets` rebuilds the estate evidence from scratch, every system has a complete evidence pack, and ground truth matches the generated content.

### Phase 4: REA Integration and Evidence Extraction (5 days)

- Build the `rea-offline` image: Node 24.15 or newer, `rea-agents` at a pinned version, and a thin wrapper that accepts a command name, a file reference, and options, then returns the JSON output. Build the `rea-browser` image the same way with a Chrome-family browser and restricted egress.
- Confirmed command: `npx -y rea-agents@latest analyze-javascript-application /absolute/path --json` (pin the version instead of `latest`). For HAR capture analysis, website observation, and SQLite inspection, read REA's own documentation in the repository (`docs/cli.md`, `docs/web-network-captures.md`, `docs/browser-observation.md`, and the generated tool catalog in `docs/mcp-contracts.md`) and record the exact commands in `docs/architecture.md`. REA changes quickly, so also check release availability for newer commands.
- `rea_adapter.py`: timeouts, structured errors, and raw output persisted in `discovery_evidence` with command, REA version, and duration.
- Extractors that convert REA output into candidates:
  - network capture: submitted field names (form and JSON keys), response fields, outbound hosts, cookies set
  - website: form inputs with names, types, labels, and autocomplete hints, third party script hosts, observed requests
  - JavaScript bundle: imported SDKs and packages, routes, IPC channels
  - SQLite: tables and columns, with masked sample values used only locally for pattern detection
- Fallback parsers for each evidence kind, selected automatically when REA is unavailable, and recorded in the evidence row.
- Acceptance: on the reference estate, discovery recovers at least 90 percent of true data elements and at least 95 percent of true recipient hosts, and each result links to its evidence.

### Phase 5: Classification and Data Element Engine (4 days)

- Rule layer: patterns for e-mail, phone, postal address, date of birth, IP address, payment card (Luhn), IBAN, national identifiers, and online identifiers.
- Embedding layer: embed element descriptions (normalized name, type, pattern class, context such as form label) and match against the taxonomy in pgvector. Thresholds for acceptance and margin are tuned on a held out portion of the estate and stored in configuration.
- Special category detection against `special_categories.json`. Any element near a special category is always escalated for human review regardless of confidence.
- Vendor resolution: map hosts to vendor, role, country, and category through `vendor_registry.yaml`. Unknown hosts become review items.
- Acceptance: at least 90 percent category accuracy without any LLM call, and every special category element in ground truth is flagged.

### Phase 6: Knowledge Base and Retrieval (3 days)

- Ingest the regulation chunks, policies, and vendor agreements into `document_chunks` with embeddings and full text vectors. Chunk policies by heading and paragraph, keeping page or section metadata.
- Hybrid retrieval: full text and vector scores merged (reciprocal rank fusion), metadata filters by system and document type, optional cross encoder reranking of the top 10 if latency allows.
- Retrieval returns passages with ids so every downstream claim can cite them.
- Acceptance: a gold set of 40 questions reaches recall at 5 of at least 90 percent on the regulation and policy corpus.

### Phase 7: LLM Router and Token Budget (3 days)

- Implement `LLMRouter`, providers, rate limit tracking, failover, circuit breaker, `llm_cache`, `llm_calls`, and per system and per organization daily budgets.
- Versioned prompt files for the five tasks in section 4, with constant prefixes and JSON schemas. Unit tests use recorded provider responses so CI never calls a real provider.
- Acceptance: simulated 429 and timeout failover without losing the job, budgets stop a runaway job, a repeated onboarding with unchanged evidence uses zero tokens, a first onboarding stays under 4,000 tokens.

### Phase 8: Fusion, Findings, and Record Generation (5 days)

- Fusion engine: compare questionnaire answers, policy statements, and discovered evidence. Rule based checks produce findings such as: element found but not in policy, recipient found but not declared, special category without a recorded condition, third country recipient without adequacy or safeguard, missing retention, missing agreement for a processor, stale review date.
- Only conflicts the rules cannot settle go to `adjudicate_conflict`, with the top 3 retrieved policy passages.
- Record generation: Jinja templates fill the processing activity from facts (data subjects, data categories, recipients, transfers, security measures from the questionnaire). `suggest_purpose_and_basis` proposes purposes and a lawful basis for review.
- Versioning with diffs between versions, evidence citations on every field, and a review queue.
- Exports: register as XLSX and PDF with the draft notice.
- Acceptance: at least 90 percent of seeded contradictions are found with precision of at least 85 percent, generated records are complete against the required fields, and every field cites evidence.

### Phase 9: Impact Assessment Module (4 days)

- Screening: score each processing activity against the criteria in `dpia_criteria.json` (for example sensitive data, large scale, systematic monitoring, vulnerable subjects, combining datasets). Two or more criteria marks the activity as likely requiring an assessment. Check the current regulator guidance when finalizing the criteria text.
- Assessment record: systematic description, necessity and proportionality, risk register with likelihood and severity (5 by 5 matrix), mitigations, residual risk, privacy officer opinion, status.
- `draft_dpia_sections`: two calls per assessment using retrieved regulation passages and the activity facts. Output is validated and every risk cites an article or evidence.
- Acceptance: screening matches the rubric on all estate activities, generated assessments pass a completeness check, and token use is within budget.

### Phase 10: Access Request Module (4 days)

- Intake with received date, automatic deadline (one month, with an extension option up to two further months with a recorded reason), status workflow, and reminders.
- Subject identifiers are HMAC hashed in storage. Raw identifiers exist only transiently in the search call.
- Search across the data map: for each system snapshot, use the discovered identifier columns to run read only parameterized queries, returning counts per table and category, not full content unless approved.
- Response drafting from a template with an optional short cover note from the LLM. Identity verification is a checklist step in the demo.
- Acceptance: all 10 request cases return the expected systems and tables with no misses, the deadline logic is tested, and no raw identifier appears in logs or LLM calls.

### Phase 11: Workflow, Orchestration, and API (4 days)

- Celery tasks per stage with retries and idempotent steps, job events at each transition, Server-Sent Events for progress.
- Task queue, approvals (analyst submits, admin approves), comments, notifications, and review reminders for stale records.
- REST API under `/api/v1` with OpenAPI at `/docs`, covering auth, systems, evidence, discovery runs, data elements, recipients, activities, assessments, findings, requests, vendors, knowledge search and chat, exports, admin, analytics, billing, `public/metrics`, and `leads`. Consistent error format, pagination, filtering, validation.
- Acceptance: a full system onboarding and a full request run from API calls only, OpenAPI examples are accurate, API tests cover every route and role.

### Phase 12: Billing, Metrics, and Analytics APIs (5 days)

Revenue figures are simulated for demonstration because there are no real customers. The dashboard logic is real: all numbers are computed from tables, and every onboarding, assessment, and request in the app creates usage events that flow into the next invoice and metrics snapshot. Seeded rows carry `is_simulated=true`, and the README and UI footnote state it.

- Plans (illustrative): Starter (free, up to 3 systems and 5 requests per month), Professional ($399 per month, up to 25 systems and 50 requests per month, $15 per extra system, $8 per extra request), Enterprise ($1,800 per month, up to 150 systems and 500 requests per month, $6 per extra system, $4 per extra request).
- Metering: usage events for active systems at month end, requests processed, assessments generated, and tokens used. Monthly invoice run produces `invoices` and `invoice_lines`. No payment processor, statuses (`paid, open, overdue, void`) come from the seed or a simple simulation.
- Nightly jobs write `daily_metrics` (MRR, new, expansion, contraction, churned MRR, usage revenue, accounts, systems, requests, tokens by provider, failovers, cache hits) and `compliance_daily_metrics` (approved records, stale records, open findings by severity and type, assessments by status, requests open and overdue, discovery confidence average, REA run duration).
- `seed_billing_history.py` (seed 42): 24 months, about 120 fictional organizations across five industries and four regions, S curve growth, plan mix, churn (higher for Starter, lower for Enterprise), expansion through added systems, invoices and payments.
- `seed_compliance_history.py` (seed 42): 12 months of findings opened and closed, record approvals, assessments, requests with realistic response times, for the demo tenant.
- Metric definitions (document in `docs/architecture.md`): MRR is the sum of base fees of active subscriptions. Usage revenue is tracked separately. Net new MRR equals new plus expansion minus contraction minus churn. Net revenue retention is computed over the trailing 12 months. Gross churn is churned MRR divided by starting MRR. ARPA is MRR divided by active paying accounts.
- Analytics endpoints with date range, granularity (day, week, month), previous period comparison, and CSV export. Redis caching for 60 seconds. Revenue endpoints are admin only.
- Acceptance: metrics reconcile (invoice lines equal revenue shown, MRR movements add up month over month), tests for every metric formula.

### Phase 13: Frontend Foundation and Public Marketing Site (6 days)

Goal: a public site that looks and feels like a large enterprise software company.

Design system:
- Palette: deep navy `#0B1F3A`, primary blue `#0F62FE`, teal accent `#00A3A3`, neutral grays, success, warning, error. Inter font (self hosted). 8 point spacing grid, maximum content width 1280 px, generous whitespace, consistent 12 column grid.
- shadcn/ui customized into one token file (colors, radii, shadows, type scale). Light theme for the public site, light and dark for the console.
- WCAG 2.1 AA: focus states, keyboard navigation, aria labels, contrast, reduced motion support.
- Performance: Lighthouse at least 90 performance and 95 accessibility on desktop, route level code splitting, lazy loaded charts and images, WebP or AVIF images with explicit dimensions.

Global layout:
- Top utility bar (Contact, Documentation, Status) and main navigation with mega menus: Platform, Solutions, Regulations, Pricing, Resources, Company. A clear `Sign in` link at the far right and a primary `Open console` button, both routing to `/login`. Sticky header that condenses on scroll, mobile drawer menu.
- Footer with five link columns, a contact field storing to `leads`, legal links, region label, and a short portfolio notice that the site is a demonstration with sample data.

Pages and content:
- **Home**: hero (example headline: "Know where personal data lives. Prove it with evidence."), supporting sentence, primary and secondary calls to action, product screenshot; capability strip with six cards (System Inventory, Technical Discovery, Records of Processing, Impact Assessments, Access Requests, Compliance Analytics); animated metric band fed by `public/metrics` and labelled as demo environment figures; "How it works" four step section with a pipeline illustration; industry tiles (Healthcare, Retail and Commerce, Financial Services, Public Sector, Technology) with photos; interactive product tour using real screenshots; trust and security practices summary; illustrative case study cards clearly marked as sample scenarios based on the reference estate; FAQ accordion; closing call to action band.
- **Platform**: the pipeline stages in depth with diagrams and the evidence types supported.
- **Solutions** (one page per industry): challenge, approach, sample outcome, link to the demo scenario.
- **Regulations**: what the platform supports (Articles 30, 35, 15), with roadmap items clearly labelled as planned.
- **Pricing**: three plan cards from the plans API, comparison table, and a cost calculator (systems and monthly requests to estimated cost).
- **Security**: only implemented practices (tenant isolation, encryption at rest, role based access, audit logging, request forgery protection, no execution of uploaded files, dependency scanning). Do not claim certifications that do not exist.
- **Resources**: documentation viewer for project docs, API reference link, three technical articles written from the project (evidence based record generation, token efficient classification, access request search).
- **Company and Contact**: about, contact form (stored in `leads`, visible to admin), request demo form.
- **Legal**: privacy and terms templates clearly labelled as samples.
- **Login**: split layout with branded panel and form, validation, error states, forgot password placeholder, redirect to the console by role.

Imagery:
- Free licensed photography from Unsplash or Pexels (modern office, legal and compliance work, data protection concepts, healthcare, retail operations, engineering team). Download, convert to WebP, store under `frontend/public/images/`, and list every photographer, source URL, and license in `frontend/public/images/ATTRIBUTION.md`.
- unDraw or hand built SVG for diagrams. No real company logos, no real customer names, no testimonials presented as real.
- Product screenshots produced from the running seeded app by `scripts/capture_screenshots.ts` (Playwright), so they are authentic and regenerable. Open Graph images and a favicon set included.

Acceptance: all public pages responsive from 360 to 1920 px, Lighthouse targets met, no layout shift, all links work.

### Phase 14: Authenticated Console (9 days)

Layout: collapsible sidebar, top bar with organization switcher, command palette (Ctrl K), notifications, user menu, breadcrumbs, skeleton loaders, empty states, error boundaries, toasts.

Pages:
- **Overview**: compliance posture summary (approved records, stale records, open findings, assessments in progress, requests due), tasks due, recent findings, requests nearing deadline, quick start with the reference estate.
- **Systems**: inventory table with owner, status, last discovery, record status, open findings. System detail tabs: Overview, Evidence, Data Elements, Recipients, Findings, Activity.
- **Add System wizard**: 1) register and assign owner, 2) attach evidence (upload, capture, URL from allowlist), 3) discovery with live progress and an evidence drawer showing REA output per item, 4) review data elements (category, special category flag, confidence, accept or override), 5) fusion results and conflicts, 6) generated record draft with citations, 7) submit for approval.
- **Records of Processing**: register table, entry detail with version history and diff, evidence citations, export to XLSX and PDF.
- **Impact Assessments**: list with screening scores, editor with sections, 5 by 5 risk matrix, mitigations, residual risk, approval.
- **Findings**: filterable queue by severity, type, system, with evidence and suggested fix.
- **Access Requests**: list with deadline timers, detail with search results per system, response draft editor, status workflow.
- **Vendors and Transfers**: processor register, agreement status, country and safeguard view.
- **Regulation Library and Ask**: searchable article text, and a chat grounded in the regulation and the organization's own records with visible citations.
- **Analytics**, **Revenue** (admin), **Billing**, **Team**, **Audit Log**, **Settings** (LLM provider order, budgets, test connection, retention).

#### Compliance analytics dashboard (ECharts)

Controls: date range presets (30 days, 90 days, 12 months, custom), granularity, compare with previous period, CSV export, print layout.
- KPI row with sparkline and delta: record coverage, stale records, open findings, average discovery confidence, requests on time.
- Findings opened versus closed over time (stacked bars with net line) and by severity and type.
- Lawful basis distribution (donut) and processing activities by data category (heatmap, systems by categories).
- Data flow view: systems to vendors to countries (Sankey), with transfers without safeguard highlighted.
- Request volume and median days to respond (combo chart) with deadline compliance rate.
- Assessment pipeline by status, record freshness distribution (histogram), discovery confidence distribution.
- Operations panel: LLM tokens per system by provider (stacked), failover count, cache hit rate, REA run duration by evidence kind, extractor mix (REA versus fallback).

#### Revenue dashboard (admin only)

- KPI row with sparkline and delta: MRR, ARR, net new MRR, net revenue retention, gross churn, ARPA, active paying accounts.
- MRR over time (area) with dashed 6 month projection labelled as a projection.
- MRR movement (stacked bars: new, expansion, contraction, churn) with a waterfall toggle.
- Revenue by plan (stacked area), by industry (treemap or donut), by region (horizontal bars), subscription versus usage revenue (stacked columns).
- Cohort retention heatmap, customer growth with ARPA trend (dual axis), unit economics (revenue per system, tokens per system).
- Top 10 customers table with sparklines, invoices table with status badges, search, and pagination.
- A footnote states the historical figures are simulated for demonstration.

Chart standards: consistent color per series across all charts, labelled axes with units, readable tooltips with exact values, legends that toggle series, loading and empty states, responsive resize, compact number formatting, accessible text summaries per chart.

Acceptance: Playwright end to end tests cover login for each role, the full Add System wizard, a full access request, role restricted pages, and both dashboards rendering with seeded data.

### Phase 15: Evaluation, Testing, and Hardening (4 days)

- `scripts/eval_run.py` runs the reference estate end to end and writes `docs/evaluation.md` with:
  - data element discovery recall and precision, split by evidence kind
  - category classification accuracy before and after the LLM step
  - recipient detection recall
  - contradiction detection recall and precision
  - record completeness and faithfulness (share of claims with valid evidence ids)
  - impact assessment screening accuracy against the rubric
  - request search recall on the 10 cases
  - chat accuracy and citation validity on the 40 question gold set
  - tokens, LLM calls, and wall time per system, first run versus repeat run
  - ablations: REA extractors versus fallback parsers, rules only versus rules plus LLM, Groq versus Gemini
- Backend coverage target 80 percent on `discovery`, `classify`, `fusion`, `generate`, `dsar`, `llm`, and `core`. Frontend tests for wizard steps and chart data transforms. Contract tests for the router with recorded provider responses. Prompt injection tests with hostile text planted in a policy and an evidence file.
- Security pass: OWASP ASVS style checklist, dependency scans clean, secrets scan, log review confirming no personal data or tokens are logged, Trivy scan of images.
- Load sanity: onboarding a system with a 50 MB capture completes without exceeding a set memory limit.
- Acceptance: evaluation document committed, all CI checks green, no high severity findings open.

### Phase 16: Documentation and Release (3 days)

README requirements (clear, professional, no marketing exaggeration, no informal wording):

1. Title, one paragraph overview, status badges.
2. Problem and solution summary.
3. Feature list.
4. Architecture diagram (Mermaid) and pipeline description.
5. Tech stack table.
6. Quick start: prerequisites (Docker, Node, Python versions), `cp .env.example .env`, how to obtain a Groq key and a Gemini key, `docker compose up`, seed commands, URLs.
7. Dataset section: sources, licenses, how the reference estate is built, how to regenerate.
8. REA section: what it is used for, pinned version, Node requirement, how the runners are isolated, and the statement "Independent project. Not affiliated with or endorsed by the REA project." Link to https://github.com/morluto/rea and its MIT license. Include a `THIRD_PARTY_NOTICES.md`.
9. Demo accounts (admin, analyst, system owner, viewer) for local use only, with the instruction to change them outside local use.
10. Usage walkthrough with screenshots: onboarding a system, reviewing a record, running an assessment, handling an access request.
11. Token efficiency design and the measured results table from `docs/evaluation.md`.
12. Security model, tenant isolation, and responsible use statement (only systems the organization owns or is authorized to examine).
13. Dashboards overview with screenshots, and the statement that revenue history is simulated.
14. Legal notice: generated documents are drafts for qualified review, not legal advice.
15. API reference link, testing commands, project structure.
16. Attributions and licenses (regulation text, datasets, Hugging Face model, images, REA, open source systems used in the estate).
17. Troubleshooting, limitations, and roadmap.

Also deliver: `docs/architecture.md`, `docs/api.md`, `docs/security.md`, a 2 minute screen recording of the demo, and a tagged release `v1.0.0` with a changelog.

Acceptance: a new developer can clone the repository and reach a working demo using only the README.

## 9. Definition of Done

- A full system onboarding runs from the UI on at least 6 of the 8 estate systems and produces approved records with evidence citations.
- A full access request runs end to end with a correct search result and a draft response.
- Measured token use is within budget and the evaluation document proves it, including the REA versus fallback comparison.
- Role based access, tenant isolation, and audit logging are tested.
- Public site and console meet the design, accessibility, and performance targets.
- Compliance and revenue dashboards render with historical data and clearly disclose simulated data.
- Documentation is complete, professional, and free of the wording and character rules in section 1.
