# Architecture

This document grows with the phases. It currently covers evidence discovery (Phase 4) and classification (Phase 5). The system onboarding pipeline is `CREATED, EVIDENCE_ATTACHED, DISCOVERING, CLASSIFIED, FUSED, DRAFTED, AWAITING_REVIEW, APPROVED, PUBLISHED, FAILED`; this phase implements the first extraction step of `DISCOVERING`.

## Discovery

```
evidence_items (encrypted at rest)
      │ decrypt to a short lived directory (rea_input), removed after the call
      ▼
Executor ── REA runner (rea-offline | rea-browser) ──► pinned rea-agents 6.7.0
      │            └─ on error, no runner or a missing capability ──► fallback parser
      ▼
Extraction  (extractor, command, REA version, duration, masked raw output, candidates)
      ▼
discovery_evidence (one row per extractor run) ◄── data_elements / recipients / technologies
                                                    (every fact has an evidence_id)
```

Code: `backend/app/discovery/` (adapter, executor, extractors, masking, service), runner: `rea-runner/`.

### The REA runner

`rea-runner/wrapper.mjs` is a thin wrapper around the REA command line. It accepts a command name, a path relative to a read only input directory (or a URL for website observation) and a few validated options, runs the pinned REA release without a shell, and returns one JSON envelope: `{ok, command, rea_version, duration_ms, result}` or `{ok: false, error: {code, message, details}}`.

| Mode | Use |
|---|---|
| `node wrapper.mjs run <command> --path P [--options JSON]` | one shot; used by the backend in development and in tests (`REA_TRANSPORT=local`) |
| `node wrapper.mjs serve` | HTTP service for containers (`POST /v1/run`, `GET /v1/health`, `x-runner-token` header) |
| `node wrapper.mjs health` | prints the REA version and the commands this runner provides |

Two images, one code base, selected by `REA_RUNNER_ROLE`:

| Image | Role | Provides | Notes |
|---|---|---|---|
| `processledger-rea-offline` | `offline` | HAR, SQLite and JavaScript analysis | no internet, evidence read only, no browser |
| `processledger-rea-browser` | `browser` | website observation | headless Chromium, internal networks only, hard timeout |

Both pin `rea-agents` through `package.json` and `package-lock.json` (`npm ci --ignore-scripts`, so nothing is downloaded at install time), require Node 24.15 or newer (REA's SQLite inspection needs it), and install `procps` (REA checks process ownership with `ps` on Linux).

### Commands used

Verified against `rea-agents` **6.7.0** (MIT, https://github.com/morluto/rea). The sources read were REA's `docs/cli.md`, `docs/web-network-captures.md`, `docs/browser-observation.md`, `docs/sqlite-databases.md` and the generated tool catalog. The adapter records the REA command line with every extractor run.

| Evidence | Wrapper command | REA command line(s) | Used for |
|---|---|---|---|
| HAR network capture | `inspect-web-network-capture` | `rea inspect-web-network-capture <capture.har> har --json` | submitted field names (form, JSON, query), response fields, cookies set, outbound hosts. Offline: recorded URLs are never fetched. Authentication headers and cookie values come back redacted. |
| SQLite snapshot | `inspect-sqlite-database` | `rea inspect-sqlite-database <db> --schema-scope database --json`, then per table `rea inspect-sqlite-database <db> --table <name> --row-limit <n> --json` | tables, columns and declared types; a bounded row sample per table for pattern detection. The database is copied privately and never modified. |
| JavaScript or Electron bundle | `analyze-javascript-application` | `rea analyze-javascript-application <dir> --json` (a single script is presented as a one file directory) | `require` and `import` references (SDKs, packages), routes, Electron IPC channels and the context bridge, the SQLite file the app opens, URL string literals. |
| Website | `observe-website` | `rea inspect-web-page <cdp-endpoint> <target-id> --observation-ms <ms> --include-accessibility-text --include-storage-keys --allowed-origins <origin>... --json`; the runner opens the page in a headless browser and reloads it during the observation window | hosts the page references or loads (resources, DOM URLs, requests), accessible label and state of each control |

Not used in this phase: native analysis providers (Hopper, Ghidra, IDA), `rea setup`, MCP serving, snapshots and comparison commands.

`rea capabilities --json` lists availability; the runner's `health` reports the REA version and the commands that exist in a given role.

### Capability gaps and the fallback parsers

REA is the primary extractor. A deterministic parser takes over when REA is unavailable, a call fails, or the pinned release does not provide the fact. Which extractor produced each fact is recorded in `discovery_evidence.extractor`.

| Evidence | Fallback | Known difference from REA |
|---|---|---|
| HAR | standard library `json` over `log.entries` | none for the estate: both yield the same candidates and hosts |
| SQLite | standard library `sqlite3`, opened read only and immutable | none for the estate |
| JavaScript | regular expressions over the source | finds a URL inside an options object (such as a Sentry DSN) that REA's literal list omits; REA resolves bindings and understands Electron boundaries that the regular expressions only match by text |
| Website | `html.parser` (BeautifulSoup) over the saved page | **always runs**: REA's page inspection keeps DOM node and attribute names but not attribute values, so input names, types and `autocomplete` hints are outside what the pinned release returns. REA still supplies the observed hosts and the control labels. |

A registered website URL has no fallback: the API never fetches it, so only the browser runner can read it.

### Persistence and provenance

- One `discovery_evidence` row per extractor run: `extractor`, `command`, `rea_version`, `duration_ms`, `status`, `error`, `raw_output`, `raw_sha256`, `raw_truncated`. A failed REA call keeps its row (status `error`) next to the fallback row that replaced it.
- Every `data_elements`, `recipients` and `technologies` row has an `evidence_id`, preferring REA's row when both extractors support the fact, and lists all supporting rows in `context.discovery_evidence_ids`.
- Sample values from evidence are used inside the discovery step to detect pattern classes (e-mail, IP address, payment card with Luhn check, IBAN with mod 97 check, hashes and so on) and are then reduced to shape masks (letters become `x`, digits `9`). Stored raw output has the same treatment: query values, request and response bodies, cell values and cookie values are masked or dropped, URL credentials are removed. `raw_sha256` is the hash of the unmasked result, so a stored record can still be tied to the exact output it was derived from. Output over 8 MiB is replaced by a summary (`raw_truncated`).
- Re-running discovery updates facts in place. Facts a person has reviewed (`review_status` other than `pending`, or a recipient with a vendor) are kept; pending facts that are no longer found are removed.
- Plaintext evidence exists only in the staging directory for the duration of one call and is removed afterwards.

A completed run leaves the system in `DISCOVERING` with `finished_at` set; moving to `CLASSIFIED` belongs to Phase 5. A run with no usable evidence, or where every extractor failed, ends `FAILED`.

### API

All under `/api/v1`, scoped to the organization and (for system owners) to owned systems.

| Route | Roles |
|---|---|
| `POST /systems/{id}/discovery-runs` | admin, analyst (runs synchronously until Phase 11 adds background jobs) |
| `GET /systems/{id}/discovery-runs`, `/data-elements`, `/recipients`, `/technologies` | all roles |
| `GET /discovery-evidence/{id}` | admin, analyst (audited) |

### Running it

```
cd rea-runner && npm ci                    # installs the pinned rea-agents (Node 24.15 or newer)
cd backend && uv run pytest                # includes the runner's own test suite and the acceptance test

docker build -f rea-runner/Dockerfile.offline -t processledger-rea-offline:6.7.0 rea-runner
docker build -f rea-runner/Dockerfile.browser -t processledger-rea-browser:6.7.0 rea-runner
docker compose --profile runners up -d rea-offline rea-browser
```

Settings: `REA_ENABLED`, `REA_TRANSPORT` (`local` or `http`), `REA_OFFLINE_URL`, `REA_BROWSER_URL`, `REA_RUNNER_TOKEN`, `REA_INPUT_DIR`, `REA_TIMEOUT_SECONDS`, `REA_OBSERVATION_MS`, `SQLITE_ROW_SAMPLE` (see `.env.example`).

### Upgrading REA

Change the version in `rea-runner/package.json`, run `npm install` there, rebuild the images, run the backend tests and re-read the changed commands in REA's documentation. REA changes quickly, so check the release notes for renamed commands or changed output shapes before moving the pin.

### Measured on the reference estate

| Extractor path | Data elements | Locations | Recipient hosts | Slowest system |
|---|---|---|---|---|
| REA (HAR, SQLite, JavaScript, website observation) with the website parser | 72 of 72 | 100 percent | 19 of 19 | about 11 s |
| Fallback parsers only | 72 of 72 | 100 percent | 19 of 19 | under 1 s |

Candidate precision (share of discovered names that are a ground-truth location) is about 70 percent: discovery deliberately lists everything it sees, including non-personal fields such as `idsite` or `created_at`. Classification (Phase 5) decides what is personal data. The estate is small and was generated from the same specification as its ground truth, so these figures show that the machinery recovers everything the evidence contains; they are not a prediction for unseen systems.

### Limits and known gaps

- Discovery runs inside the request until Phase 11. A very large capture (REA output can reach hundreds of megabytes for a real JavaScript application) needs the background job and the load test planned for Phase 15.
- The REA call for a website needs a Chrome-family browser. Chromium runs with its own sandbox disabled inside the container, which is the isolation boundary (unprivileged user, no capabilities, read only root file system, no route to the internet).
- The browser resolves no names itself: host resolution is mapped to "not found" except for the served snapshot (or the single pinned address for a URL), so a saved page's third-party requests are recorded as attempts and never leave the machine.
- REA reports DOM attribute values, text and request bodies only in limited ways by design; this project relies on that minimisation rather than working around it.
- An uploaded script is analysed as data. Nothing is executed.

## Classification

Runs after discovery: it decides the category of each data element, flags Article 9 data, resolves recipient hosts to vendors, and queues what a person must look at. **No LLM is called**; the code in `backend/app/classify/` has no provider or network client, and a test checks its imports.

```
data_elements (name, type, pattern class, label, autocomplete, table)  (never sample values)
      ├─ rule layer ────────── autocomplete hint, value pattern, input type, name and label vs. synonyms
      ├─ embedding layer ───── description → bge-small-en-v1.5 (384 d, CPU) → nearest taxonomy entries in pgvector
      ▼
decision (category, confidence, method, reasons, top candidates)  +  Article 9 check  +  vendor resolution
      ▼
data_elements.category / special_category / confidence / embedding / context.classification
findings: special_category_review, low_confidence_classification, unknown_recipient_host
system status → CLASSIFIED
```

### Layers

- **Rules** (`rules.py`): patterns for e-mail, phone, IP address, payment card (Luhn), IBAN (mod 97), password hashes and coordinates; HTML `autocomplete` tokens; input types; the element name and label compared with the taxonomy synonyms (exact, without qualifiers such as `billing_`, multi word, single word). Generic words (`name`, `number`, `order`) never decide alone. A technical name (`created_at`, `status`, `idsite`) with no personal-data word and no personal value pattern is not personal data.
- **Embeddings** (`embedder.py`, `index.py`): the taxonomy labels, definitions and synonyms (about 410 entries) are embedded once into `taxonomy_entries` (pgvector, HNSW cosine index). An element description (normalised name, label, autocomplete hint in words, type, pattern class, table; no values) is embedded and matched against it; the best entry per category is that category's similarity.
- **Decision** (`decide.py`): a confident, unambiguous rule result is accepted (an agreeing embedding adds confidence). Rules that tie are broken by the embedding. Without a rule result, a clear embedding match (similarity and margin over the next category) is accepted. Anything plausible but short of the thresholds stays unclassified and becomes a review item; implausible names produce nothing.
- **Special categories** (`special.py`): strong if the element is classified as one or its name or label contains an Article 9 word; near if it carries only a weak word (`patient_email`), sits in a table with strong special data and its meaning depends on context (an appointment time, a doctor), or its embedding is close to a special category. Strong and near are both escalated to review whatever the confidence; only strong sets `special_category`.
- **Vendors** (`vendors.py`): the first matching entry of `vendor_registry.yaml` gives vendor, role, country and category; the organisation's own domains are internal; anything else is unknown and gets a finding. A vendor entered by a person is kept.

### Thresholds

Stored in `datasets/regulation/taxonomy/classifier_config.json` and recorded with every decision. `scripts/tune_classifier.py` chooses them by grid search on five tuning systems (objective: correct minus three times wrong, minus penalties for technical names classified and for extra escalations; every special category element must be flagged). It then scores three held-out systems (`web_analytics`, `crm`, `staff_desktop`) and a hand-written challenge set (`datasets/evaluation/classification_challenge.json`, 87 names written independently of the synonym lists). Neither is used to choose values.

| Set | Labelled | Correct | Wrong | Unclassified | Special categories flagged |
|---|---|---|---|---|---|
| Tuning systems (5) | 150 | 148 | 0 | 2 | 100 percent |
| Held-out systems (3) | 66 | 65 | 0 | 1 | 100 percent |
| Whole estate | 216 | 213 (98.6 percent) | 0 | 3 | 17 of 17 (16 strong, 1 near) |
| Challenge set | 78 personal + 9 technical | 72 + 9 | 3 | 3 | not applicable |

Ablation on the estate: rules only 94.4 percent, embeddings only 65.3 percent, both 98.6 percent. Treat the estate figures with care: the synonym lists and the estate field names were written by the same author, which flatters the rule layer. The challenge set (92.3 percent, no technical name mistaken for personal data) is the fairer estimate for unseen systems. The three remaining estate misses are an obscure tracker parameter (`cd[value]`), an abbreviated Meta parameter (`ud[ph]`) and an appointment time next to health data (escalated as near, category unclassified).

### Setup

```
cd backend
uv run alembic upgrade head
uv run python ../scripts/download_embedding_model.py   # once; bake into the image and set EMBEDDING_LOCAL_FILES_ONLY=true
uv run python ../scripts/load_taxonomy.py              # embeds the taxonomy into taxonomy_entries (owner connection)
```

`taxonomy_entries` is shared reference data that the application role can only read; classification answers 503 until it has been loaded. A different taxonomy or model reloads it.

### API

| Route | Roles |
|---|---|
| `POST /systems/{id}/classification` | admin, analyst |
| `PATCH /systems/{id}/data-elements/{element_id}` (accept, override, mark as not personal data) | admin, analyst |
| `GET /taxonomy` | all roles |

Reviewed elements (`accepted` or `overridden`) are never overwritten by a later run, and findings are deduplicated by key: a review item closes automatically when it no longer applies.

### Limits

- Names are judged in English. Field names in other languages rely on the embedding model, which is trained mostly on English.
- Values are used only to detect pattern classes and are never embedded or stored.
- A column meaning can depend on a neighbour (an `amount`, a `title`); table context is used for special categories only.

## Knowledge base and retrieval

Holds the text the later phases reason over (the GDPR, the organisation's policies, questionnaires and vendor agreements) and returns passages that a downstream claim can cite. **No LLM is called**; retrieval is full text plus vectors in PostgreSQL.

```
datasets/regulation/gdpr_articles.json ── scripts/ingest_regulation.py (owner role) ──► regulation_chunks (shared)
policy / questionnaire / agreement (upload or evidence item)
      ├─ chunking.py ── by heading and paragraph, page and section kept ──► document_chunks (per organisation, RLS)
      ▼
embedding (bge-small-en-v1.5, "title. heading: text")  +  generated tsvector (heading + text)

query ─┬─ vector: pgvector cosine (HNSW) over both tables, top 30 by similarity
       ├─ full text: to_tsquery with OR-ed terms, ts_rank_cd, top 30
       ▼
reciprocal rank fusion (k = 60) ─► optional cross encoder over the top 10 ─► passages with id, citation, label, score, signals
```

### Chunking (`backend/app/knowledge/chunking.py`)

- Markdown: one passage never crosses a heading; nested headings become a path (`Security > Backups`). Paragraphs under one heading are packed up to 900 characters, longer ones are split at sentence boundaries, a small tail is merged back. The italic provenance note under the title is not indexed.
- PDF (pdfplumber): numbered headings (`1. Subject matter`) and the page number of each passage are kept. HTML (BeautifulSoup): headings, paragraphs and list items without scripts. Questionnaire JSON: one passage per answer, headed by the question.
- The embedding of a document passage is computed from `document title. heading: text`, so a section called "How long we keep it" is tied to the system it belongs to. The full text vector covers heading and text.
- Regulation passages are the 412 article and paragraph chunks, embedded as `GDPR Article 30(1), Records of processing activities: text`. Each has a stable key (`gdpr-art30-p1`).

### Retrieval (`backend/app/knowledge/retrieval.py`)

- Vector and full text candidate lists (30 each) are merged by reciprocal rank fusion. Cosine similarity is comparable across the two tables, so the vector list mixes regulation and document passages by similarity; the full text list is merged by `ts_rank_cd`.
- Filters: system, document type, article numbers, source (regulation or documents). A system owner sees organisation wide documents and those of the systems they own. Row Level Security keeps other organisations out whatever the query says.
- The bge query instruction is added to the question before embedding. Query terms are reduced to letters and digits before they reach `to_tsquery`, so operators in user text have no effect.
- Cross encoder (`cross-encoder/ms-marco-MiniLM-L-6-v2`, Apache-2.0) over the top 10: off by default (`RERANK_ENABLED=false`), `rerank` can be set per request.
- Every passage has an `id`, a `citation` (`reg:gdpr-art30-p1` or `doc:<document id>#<chunk>`), a human readable `label` (`GDPR Article 30(1), Records of processing activities`, `Privacy notice: Web shop, How long we keep it`), its score, which lists found it (`vector_rank`, `fulltext_rank`) and metadata (article, heading, page, system, document type). `resolve_citation` and `GET /knowledge/passage` turn a citation back into the exact text, which lets later phases reject a claim whose citation does not resolve.

### Ingestion

Idempotent: a document is identified by its evidence item (or system, source and type for uploads); the checksum covers the content, the chunk size and the embedding model, so unchanged content is not embedded again and any change replaces the document and its passages in one transaction. The regulation load compares text and model and skips when nothing changed.

### Setup

```
cd backend
uv run alembic upgrade head
uv run python ../scripts/download_embedding_model.py   # once
uv run python ../scripts/ingest_regulation.py          # embeds the GDPR text (owner connection)
```

Policies, questionnaires and agreements are indexed per system with `POST /systems/{id}/knowledge/ingest` (reads the evidence already uploaded) or uploaded directly as organisation wide or system documents. Search answers 503 while the knowledge base is empty.

### API

| Route | Roles |
|---|---|
| `POST /knowledge/search` | all roles (system owners see their own systems and organisation wide documents) |
| `GET /knowledge/passage?citation=` | all roles |
| `GET /knowledge/documents` | all roles |
| `POST /knowledge/documents` (upload), `DELETE /knowledge/documents/{id}` | admin, analyst |
| `POST /systems/{id}/knowledge/ingest` | admin, analyst, system owner (own systems) |

### Evaluation

`datasets/evaluation/retrieval_gold.json` holds 40 questions (24 on the regulation, 16 on policies, questionnaires and agreements of the estate), written before any tuning. A question counts as found when a relevant passage is in the top 5. `backend/tests/test_knowledge_gold.py` fails below 90 percent.

| Method | Recall at 5 | MRR | Median latency |
|---|---|---|---|
| Full text only | 75.0 percent (30 of 40) | 0.600 | 16 ms |
| Vector only | 97.5 percent (39 of 40) | 0.869 | 72 ms |
| **Hybrid (default)** | **97.5 percent (39 of 40)** | **0.910** | 111 ms |
| Hybrid + cross encoder | 97.5 percent (39 of 40) | 0.950 | 360 ms (p95 455 ms) |

Hybrid and vector only find the same questions; fusion improves the position of the answer (MRR) and keyword matches rescue exact terms that the embedding blurs. The cross encoder improves the order further at about 250 ms extra, which is why it is optional. The one miss is "Which service providers receive the patients' data?" scoped to the clinic portal: the questionnaire's declared recipients and the vendor agreements outrank the notice section "Who we share it with". Times are for a laptop CPU with 412 regulation and 245 document passages.

### Limits

- English only (model and stemming). The full text configuration is `english`.
- Document passages are not shared across organisations; the same agreement uploaded by two organisations is embedded twice.
- The gold set covers the reference estate; recall on other corpora is not measured. Questions that need several passages together (a contradiction between a notice and a record) are the fusion phase's job, not retrieval's.
- Scanned PDFs without a text layer are rejected as empty.

## LLM router and token budget

The model is used for free text and ambiguous judgments only. Extraction, classification, vendor lookup, conflict screening and retrieval are rules, embeddings and SQL. The code is in `backend/app/llm/`.

```
task + payload ── guard (mask identifiers, refuse sample values) ── fenced JSON in <data> ... </data>
      ▼
llm_cache (org, SHA-256 of task, prompt version + hash, payload)  ── hit: zero tokens, logged as a cache hit
      ▼ miss
budgets: request cap 5,000 ─ job budget ─ system per day ─ organisation per day   ── over: BudgetExceededError (logged)
      ▼
providers in the organisation's order (default Groq, then Gemini)
   circuit breaker (3 failures, open 60 s) ─ token bucket per provider ─ retry with backoff and jitter ─ failover
      ▼
JSON parsed and validated (Pydantic, task checks); one repair call; still invalid: next provider
      ▼
answer cached, every attempt written to llm_calls (provider, model, task, tokens, cached tokens, latency, status, system)
```

### Tasks and prompts

| Task | Used for | Calls |
|---|---|---|
| `suggest_purpose_and_basis` | purposes and a lawful basis suggestion | one per processing activity |
| `adjudicate_conflict` | a statement the rules cannot settle, with the top 3 retrieved passages | only when needed |
| `draft_dpia_sections` | description and necessity, then risks | two per assessment |
| `draft_request_cover_note` | optional short cover note (counts only) | optional |
| `answer_question` | retrieval augmented answer with citations | none when nothing is retrieved |

Prompts are files (`backend/app/llm/prompt_files/<task>.v1.md`) behind a shared first part (`_common.v1.md`) so the prefix is constant and provider prompt caching applies. The version and the hash of the text are part of the cache key: editing a prompt never serves an old answer. The output schemas (`schemas.py`) require every field, forbid extras and cap every string, so an answer cannot outgrow the 800 token output cap. Requests use temperature 0 and strict JSON schema output (Groq `json_schema`, Gemini `responseJsonSchema`).

### What is sent

Element names, category labels, vendor names, roles, countries and short retrieved passages. `guard.py` refuses payload fields called `sample`, `values`, `raw`, `email`, `identifier`, `subject_hash` and similar, and masks e-mail addresses, IP addresses, IBANs, long digit runs, hashes and telephone numbers inside text. ISO dates and passage ids are kept. The data sits inside `<data>` tags, any tag in the text is removed, and the prompt tells the model that the content is untrusted. Answers cite passage ids; an id that was not in the request makes the answer invalid. The model has no tools and writes no documents.

### Failure behaviour

| Event | Behaviour |
|---|---|
| 429 | provider marked blocked for its `Retry-After`; retried once after a short backoff when that is short; then the next provider |
| 5xx, timeout, network error | retried once with backoff and jitter, then the next provider |
| 401 or 403 | next provider at once |
| Invalid JSON or schema or citation | one repair call, then the next provider |
| Three consecutive failures | provider skipped for 60 seconds, then one probe call |
| Every provider unavailable | `LLMUnavailableError` with `retry_after_seconds`; the caller keeps its job and retries |
| Budget exceeded | `BudgetExceededError`, no provider is called; cached answers still work |

Rate limit state (token and request buckets, breaker) is held in the process and is seeded from Groq's `x-ratelimit-remaining-*` headers. Several workers each keep their own state, so a worker may still receive a 429; failover handles it. Daily budgets are summed from `llm_calls` (UTC day); two jobs running at the same moment can overshoot a budget by one request each.

### Budgets (defaults)

| Budget | Default | Where set |
|---|---|---|
| One request (estimated input + output cap) | 5,000 tokens | `LLM_REQUEST_TOKEN_CAP` |
| One system onboarding | 4,000 tokens | `LLM_ONBOARDING_TOKEN_BUDGET` (a `JobBudget`) |
| Per system per day | 20,000 tokens | organisation settings |
| Per organisation per day | 200,000 tokens | organisation settings |

### Measured (reference estate, `backend/tests/test_llm_onboarding.py`)

The worst case onboarding of one system is one purpose call plus two conflict calls with three passages each. The provider is scripted and token counts come from the router's high estimate (3.5 characters per token), so they are an upper bound for real tokenizers.

| Case | Tokens |
|---|---|
| First onboarding, 8 systems | 1,650 to 1,914 (limit 4,000) |
| Repeat with unchanged evidence | 0, no provider call |
| One new recipient | one call for the changed question only |

The tests use responses recorded in the providers' documented formats (`backend/tests/recorded/llm/`); CI never calls a provider. No live call has been made from this repository, so real token counts and the Gemini free tier limits are unverified: confirm the current free models and quotas in Google AI Studio, set `GEMINI_MODEL`, and run `POST /api/v1/llm/test-connection` once keys are configured.

### Setup and privacy

```
GROQ_API_KEY=...          # optional; without a key the provider is not registered
GEMINI_API_KEY=...        # optional
GEMINI_MODEL=gemini-2.5-flash-lite
```

Free tier content may be used by the provider to improve its products. Send only synthetic or masked data (the guard enforces masking, not consent). With no key the router has no provider and every uncached call raises `LLMUnavailableError`; nothing else in the platform depends on it yet.

### API

| Route | Roles |
|---|---|
| `GET /llm/usage` (today's calls, tokens, cache hits, failed attempts, circuit states) | admin, analyst, viewer |
| `POST /llm/test-connection` (one tiny call per configured provider) | admin |

The provider order and the two daily budgets are organisation settings (`GET/PUT /settings`).

## Fusion, findings and records

Runs after classification. It compares three sources for one system, raises findings, and builds a versioned record of processing from the facts. Code: `backend/app/fusion/` and `backend/app/records/`.

```
questionnaire (evidence)  ─┐
privacy notice (evidence) ─┼─ FactsLoader ── SystemFacts ── rules (no model) ── findings (dedupe key, evidence refs)
discovered elements,       │                                      │
recipients (database)     ─┤                                      └─ conflicts the rules cannot settle ── adjudicate_conflict (top 3 passages)
company policy, agreements │
(knowledge base)          ─┘
                                   facts ── Jinja templates ── record (citation for every field) ── versions ── review ── XLSX / PDF
                                   suggest_purpose_and_basis (one cached call) fills purposes and a basis suggestion
```

### Rules

| Finding type | Raised when | Severity |
|---|---|---|
| `element_not_in_policy` | a discovered category (confidence 0.80 or more, or special, or reviewed) is not named by the notice | medium, high for special categories |
| `cookie_not_in_policy` | the same for a cookie whose kind of data is not already reported | low |
| `undeclared_recipient` | an external recipient is missing from the notice or from the questionnaire | high |
| `third_country_no_safeguard` | recipient outside the EEA, no applicable adequacy decision (the US needs a safeguard) and no safeguard in the questionnaire | high |
| `missing_agreement` | a processor with no agreement in the questionnaire or among the agreements on file | high |
| `missing_art9_condition` | special category data and no condition recorded | critical |
| `missing_retention` / `stale_review` | no retention in the questionnaire / last review more than twelve months before the comparison date | medium / low |
| `policy_contradiction` | the notice promises limited sharing and another recipient is found, or promises not to store something that is stored in a database column | high |
| `consent_defect` | the notice promises an active opt in and a consent checkbox is ticked by default | high |
| `retention_conflict` | records older than the period the notice states for them, or a period over the company limit for customers | medium |
| `retention_review` | the company limit may or may not apply (other data subjects): put to the model, or left to a person | low |

The notice is read with the same classifier that classifies discovered elements (a bullet such as "your date of birth" gives a category; close candidates count, so "an identifier of your computer" names a device identifier). Sentences are matched for three kinds of claim: limited sharing, "never store / not stored" and active consent. Retention periods are parsed from words and numbers ("seven years", "25 months"); open ended ones ("employment plus six years") are not compared. Discovery now records the oldest and newest record month of timestamp columns (never birth dates), which is how "records older than the stated period" is checked.

Findings are keyed (`fusion:<system>:<type>:<subject>`), so running again updates them in place. A finding that stops applying is resolved; a dismissed or acknowledged one stays as the person left it; one that returns reopens. Every finding carries evidence references (`questionnaire`, `policy`, `discovery`, `company_policy`) with the id of the evidence item or discovery record.

### The model's part

The only ambiguity the rules meet is whether the company retention limit covers data subjects other than customers (patients, employees, visitors). That goes to `adjudicate_conflict` with the company clause as the single passage. `contradicts_policy` raises the conflict; `supported_by_policy` and `undetermined` become a low severity review item. Without a provider, or over budget, the review item is created and nothing is lost. Answers are cached, so a repeat comparison costs no tokens.

### Records

A record has the fields of an Article 30 entry: purposes, data subjects, data categories, recipients, transfers, retention, security measures, lawful basis, Article 9 condition, owner and next review date. Text is rendered from Jinja templates; every field has citations (the questionnaire, discovery evidence, the notice, or `assistant` for the suggestion, or `manual` for a person's edit).

- Purposes and a lawful basis: the owner's words come first. The assistant's suggestion is added to the purposes and marked "Suggested for review"; it fills the basis only when the owner gave none, and never states an Article 9 condition.
- A required field that is empty is reported as missing; a record with missing fields cannot be submitted. Special category data without a condition keeps the record incomplete on purpose.
- Versions: regenerating without new evidence creates nothing; changed content becomes a new version with a change summary, and a diff (`GET /activities/{id}/diff`) shows fields and list items added or removed. Fields a person edited survive regeneration. A change to an approved or published record returns it to draft.
- Workflow: draft, submit (admin, analyst), approve or reject (admin; the submitter cannot approve their own record), publish (admin). The review queue lists approvals, incomplete drafts and open high or critical findings.
- Exports: the register as XLSX (sheets Register, Recipients, Evidence, Open findings) and PDF. The notice "Draft for review by a qualified privacy professional. Not legal advice." is on the first rows of every sheet and in every PDF page footer.

### Measured (reference estate, `backend/tests/test_fusion_acceptance.py`, `test_records.py`)

| Check | Result |
|---|---|
| Seeded contradictions found (all expected finding types) | 19 of 19 |
| Expected (system, type) findings reported | 24 of 24 |
| Precision | 88.9 percent (24 of 27 reported pairs) |
| Records complete against the required fields | 8 of 8, apart from the Article 9 condition of the clinic and HR systems (a real gap, also a finding) |
| Fields citing existing evidence | every required field of every record |
| Tokens per system, fusion + record, scripted model | 520 to 660 for the record; 0 or about 490 for the comparison (limit 4,000) |

The three reported pairs the dataset does not list: the newsletter and staff notices promise not to share beyond what they name while an undeclared recipient receives data (a true inconsistency the dataset records only as `undeclared_recipient`), and a CRM finding caused by a classifier mistake (`amount` read as purchase history). The first run had 80 percent precision. After reading the false positives, two general changes were made: findings need a classification confidence of 0.80 or more (below that the item belongs in the classification review queue), and cookies are reported under their own low severity type. The figures above are measured on the same estate that was used to look at those mistakes, so they are optimistic for unseen systems. Recall is not affected by either change.

### Limits

- The notice is parsed from Markdown or plain text; PDF and HTML notices are searchable in the knowledge base but not yet read by the rules (a `missing_evidence` finding is raised).
- Notice wording is English. The claim patterns cover the sentences of the reference estate and similar common phrasing; unusual wording is missed, which is why the notice is also shown to a person.
- Retention age uses the creation month of records, not the closure date, and compares only tables named in the retention sentence.
- Vendor names are matched by whole words (`BrightLens` matches `BrightLens Agency`).
- Self-approval is blocked by user, so an organisation needs two people with the right roles.

### API

| Route | Roles |
|---|---|
| `POST /systems/{id}/fusion`, `PATCH /findings/{id}` | admin, analyst |
| `GET /findings` | all roles (owners see their systems) |
| `POST /systems/{id}/record`, `PATCH /activities/{id}`, `POST /activities/{id}/submit` | admin, analyst |
| `POST /activities/{id}/approve`, `/reject`, `/publish` | admin |
| `GET /activities`, `/activities/{id}`, `/versions`, `/versions/{n}`, `/diff` | all roles (owners see their systems) |
| `GET /review-queue` | admin, analyst |
| `GET /exports/register.xlsx`, `/exports/register.pdf` | admin, analyst, viewer |

## Impact assessments

For each processing activity: screen it against the criteria, and for those that need one, draft an assessment with a risk register, review it, and approve it. Code: `backend/app/dpia/`.

```
record + discovered evidence + stated scale ── screening (9 criteria, no model) ── dpia_screenings (met / not met / unknown, with evidence)
                                                       │ two or more met (or a reason given)
                                                       ▼
retrieved GDPR passages ── draft_dpia_sections x2 (description; risks) ── validated ── dpias + dpia_risks (5 x 5, mitigations, residual)
risk catalogue + templates (fallback)   comparison findings (transfer, agreement gaps) ── risks with evidence
                                                       ▼
                    completeness check ── submit ── privacy officer opinion ── approve / reject ── PDF with the draft notice
```

### Screening

The criteria are in `datasets/regulation/taxonomy/dpia_criteria.json` (the project's wording of the criteria discussed in the EDPB guidelines; check the current guidelines before relying on it). Two or more met means an assessment is likely required. A criterion is met, not met, or **unknown** when the evidence cannot say.

| Criterion | Judged from |
|---|---|
| sensitive data | special category elements, or criminal data, national identifier, bank account |
| vulnerable subjects | data subjects named patients, employees, staff, children, minors, elderly and similar |
| systematic monitoring | location or browsing behaviour stored in a database column (data only passed to a third party does not count), or a monitoring purpose such as CCTV |
| large scale | an estimate of 1,000 or more data subjects, or 3 or more countries (stated by an analyst, or "five countries" in the system description); **unknown** until one is given |
| combining datasets | a recipient registered as an enrichment vendor, or text such as "added from business data sources" |
| innovative technology | biometric or genetic data, or machine learning, facial recognition and similar in the purposes |
| evaluation or scoring, automated decisions, blocks rights | keywords in the purposes and the notice sections on purposes ("we do not use profiling" does not count) |

Scale is the one thing nothing in the evidence shows, so the screening asks for it (`needs` in the answer) and keeps what an analyst enters. The 1,000 person threshold is a round number chosen for the demonstration; the guidelines give none. Analysts can also state that a criterion applies; those are marked as stated, with no automatic evidence. An activity that is not required but has enough unknown criteria to reach the threshold is reported as `undecided`.

### Assessment

Fields: systematic description, necessity and proportionality, risk register (likelihood and severity 1 to 5; bands low up to 4, medium up to 9, high up to 15, very high above), mitigations, residual rating per risk and overall, privacy officer opinion, status (draft, in review, approved, rejected).

Drafting makes two assistant calls (`draft_dpia_sections`, part `description` and part `risks`) with the activity facts as labels only (no values) and up to four retrieved GDPR passages that the answer must cite. The risk citation holds the passage citations (`reg:gdpr-art9-p1`) and, for gaps found by the comparison, the finding (`finding:<id>`): a transfer without a safeguard or a processor without an agreement becomes a risk with that evidence. If no provider answers, the descriptions come from templates and the risks from `risk_catalogue.json` (typical risks and measures per criterion with their articles), so a complete draft exists with no model. The model's risks are checked: each must cite passages it was given. Residual ratings are drafted one step lower in likelihood than the inherent rating and are for the privacy officer to change.

An assessment can be submitted when it has a description, a necessity text, at least one risk and each risk has a mitigation, a citation and a residual rating. Approval also needs the officer's opinion (recorded by an admin only) and a decider who did not submit it. A rejected assessment can be edited and submitted again; an approved one is closed. Starting a new draft for unchanged facts costs no tokens (cache).

### Measured (reference estate, `backend/tests/test_dpia_acceptance.py`)

| Check | Result |
|---|---|
| Screening against the rubric (`datasets/expected/dpia_screening.json`) | 8 of 8 activities: the same criteria and the same required decision |
| Assessments drafted (the 4 required) | all complete; every risk cites a resolvable article or finding |
| Tokens per assessment (scripted model, high estimate) | 1,878 to 1,988 for two calls (limit 6,000) |
| Repeat draft for the same facts | 0 tokens |

The first screening run matched on 7 of 8 activities; the 8th reported "evaluation or scoring" because the word "profile" in "view their profile" matched the profiling keyword. The pattern was narrowed to "profiling". The people counts used as the scale are those of the synthetic people file; the rubric itself is never read by the platform.

### Limits

- Criteria that depend on judgment (evaluation, automated decisions, rights) are keyword based on the text of the purposes and the notice; wording that avoids the keywords is missed, so an analyst can state them.
- The scale threshold is a convention. The assessment is a draft: likelihood and severity are starting points and the mitigation text is generic until the owner adds the specifics.
- The EDPB guidance and national lists of processing that always need an assessment change; the criteria file records its version.
- The PDF is a single document; there is no version history of assessments (a new draft replaces nothing, rejected ones stay).

### API

| Route | Roles |
|---|---|
| `POST /activities/{id}/dpia-screening` | admin, analyst |
| `GET /activities/{id}/dpia-screening`, `GET /dpia-screenings` | all roles (owners see their systems) |
| `POST /activities/{id}/dpia` (screening required, or a reason), `PATCH /dpias/{id}`, risk add, edit, delete, `POST /dpias/{id}/submit` | admin, analyst (the officer opinion: admin) |
| `POST /dpias/{id}/approve`, `/reject` | admin |
| `GET /dpias`, `GET /dpias/{id}` | all roles (owners see their systems) |
| `GET /dpias/{id}/export.pdf` | admin, analyst, viewer |

## Access requests

Handles a person's request for a copy of their data (Article 15): intake, deadline, identity check, a search of the data map, a drafted response and its approval. Code: `backend/app/dsar/`.

```
identifier (email or phone) ── normalise ── HMAC-SHA256(key, organisation + type + value) ── access_requests.subject_hash   (the raw value is not kept)
                                                                                          deadline: 1 month, next working day
identity checklist ── verified
identifier sent again for the search ── checked against the hash ── bound parameter only
      │
      ▼ for each system: discovered identifier columns (category contact_email / contact_phone, location db_column)
snapshot decrypted in memory ── read only, parameterised count per table and column ── request_results (counts, never content)
      │                                            approved by the privacy officer ── content of those locations, for the copy, not stored
      ▼
letter from a template (systems, where found, kinds of data, purposes, recipients, retention from the records) + optional cover note (counts only)
      ── submit ── approve (another person) ── respond ── close
```

### Identifiers

An e-mail address is trimmed and lower-cased; a telephone number is reduced to digits. The hash is HMAC-SHA256 over `organisation : type : value` with a secret key (`SUBJECT_HASH_KEY`, or derived from the evidence encryption key), so the same person has different hashes in different organisations and a hash cannot be recomputed without the key. The raw value exists only in the call that carries it: the search and the disclosed data call send it again, it is checked against the stored hash (a different identifier is refused) and used only as a query parameter. It is a `SecretStr` in the request model, validation errors are returned without the submitted value, audit entries hold counts, and the cover note payload holds counts only (`days_taken`, `systems_found`). A test scans every table of the database, the logs, the output, the audit log, the request listings and every model request for the identifiers of three cases.

### Deadlines

The deadline is one month from receipt (the corresponding date, or the last day of the month when there is none), moved to the next working day when it falls on a weekend (Regulation 1182/71). Public holidays are not modelled. One extension of one or two further months is allowed for a complex or numerous request, with a recorded reason, and only within the first month. Reminders (`GET /access-requests/reminders`) list open requests that are overdue, due today or due within seven days (`REQUEST_REMINDER_DAYS`), most urgent first. Nothing is sent by e-mail: the platform has no mail transport.

### Search

Only columns that discovery found and classified as the identifier are queried, and the table and column names are checked against the snapshot's own schema before they are quoted. Telephone numbers match after punctuation is removed; a number written with its country code does not match the same number written without it. The result is a count per system, table and column. A system with no snapshot, or none with an identifier column, is listed as not covered and named in the letter. The content behind a location is returned only after an admin approves that location (`POST /{id}/disclosure`, `POST /{id}/disclosed-data`, at most 50 rows per table, nothing stored).

### Workflow

`received` then `identity_verification` (checklist incomplete) then `searching` (identity verified) then `drafting` (search done) then `awaiting_approval` then `responded` then `closed`; `rejected` from any open state with a recorded reason. Searching needs a verified identity, drafting needs a search, the person who submitted the response cannot approve it, and sending needs an approved response. The letter carries the draft notice and a placeholder for the privacy officer's contact details. Access requests are for the privacy team: admin and analyst work on them, viewers read, system owners have no access.

### Measured (reference estate, `backend/tests/test_dsar_acceptance.py`)

| Check | Result |
|---|---|
| Request cases RC01 to RC10 (expected system, table, column and row count) | 10 of 10 exact; 52 of 52 locations found, none extra; RC09 and RC10 return nothing |
| Identifier in logs, database, audit log, model requests | none (checked for three cases) |
| Cover note | 3 numbers and a tone; no name or identifier |

### Limits

- Only e-mail and telephone identifiers are supported. A name is not an identifier (too many people share one), so a person known only by a pseudonymous identifier (RC09) finds nothing.
- Only data in the database snapshots is searched. Files, logs, backups and data held by processors are not, and the letter says which systems were not covered.
- The identity check is a checklist; no identity document is stored.
- Matching is exact on the normalised value. Misspellings, aliases and the same address with a plus tag are not found.
- A "copy of the data" is a list of rows for approved locations, not a formatted export.

### API

| Route | Roles |
|---|---|
| `POST /access-requests`, `/{id}/identity`, `/{id}/extension`, `/{id}/search`, `/{id}/response`, `PATCH /{id}/response`, `/{id}/submit`, `/{id}/close`, `GET /reminders` | admin, analyst |
| `POST /{id}/disclosure`, `/{id}/disclosed-data`, `/{id}/approve`, `/{id}/return`, `/{id}/respond`, `/{id}/reject` | admin |
| `GET /access-requests`, `/{id}`, `/{id}/results`, `/{id}/response` | admin, analyst, viewer |

## Background jobs, workflow and the API

### Onboarding as a job

`POST /systems/{id}/onboard` creates a job and queues the first stage; each stage is a Celery task (`onboarding.stage`, `backend/app/workers/tasks.py`) that runs one step and queues the next.

```
discover ──► classify ──► fuse ──► record ──► screen          (each: claim, work, record the result, queue the next)
   │ every transition writes a row in job_events (queued, started, stage_started, retry, stage_succeeded, stage_failed, succeeded, failed, cancelled)
   ▼
GET /jobs/{id}/events   Server-Sent Events, resumable with Last-Event-ID, ends with an `end` event
GET /jobs/{id}/log      the same events as JSON
```

- **Idempotent.** A stage that already succeeded is skipped when its message is delivered again; the stage functions themselves (`backend/app/services/pipeline.py`, shared with the API routes) change nothing when run again on unchanged evidence, and the model answers are cached, so a repeated onboarding costs no tokens.
- **Retries.** Transient failures (database, network, no provider) are retried with a growing delay (`JOB_RETRY_SECONDS` times 1, 2, 4; `JOB_MAX_RETRIES` times), each retry is an event. Anything else fails the job at once: the stage and the job are marked failed, the system status becomes `FAILED`, and the person who started it and the admins get a notification. The next job can start again.
- **One job per system** at a time; a job can be cancelled before its next stage.
- **No worker needed to try it.** With `CELERY_EAGER=true` the stages run inside the request (tests, a laptop without Redis). In the real deployment the API only queues, `celery -A app.workers.celery_app worker` runs the stages, and an unreachable broker answers 503 and leaves no job waiting.
- The job state is kept in PostgreSQL, not in Celery's result backend (task results are ignored), so the progress stream and the job list survive a broker restart.

### Tasks, comments, notifications, reminders

| Piece | What it does |
|---|---|
| Tasks (`/tasks`) | Work items with an assignee, a system, a due date and a status. A finding becomes one task for the owner of its system (`POST /findings/{id}/task`, asking again returns the same task). The person a task is assigned to can change its status. |
| Comments (`/comments`) | On a system, a record, an assessment or a finding; visible only to people who can see the thing. The owner and earlier commenters are notified, never the author. |
| Notifications (`/notifications`) | In-app, per person, created when a job finishes or fails, a task is assigned, someone comments, an approval is asked for (the admins) and when it is decided (the person who asked). `X-Unread-Count` tells how many are waiting. There is no e-mail transport. |
| Approvals | Analysts submit, admins decide; the submitter cannot approve their own record, assessment or response. |
| Review reminders (`POST /reminders/run`, daily in the worker) | Records past their review date, or within 14 days of it, get a task for the owner and a notification (the admins as well when overdue); access requests that are overdue or due within seven days notify the person handling them and the admins. Each reminder is created once per review date or deadline level. |

### The API

All routes are under `/api/v1`, documented at `/docs` and `/openapi.json`.

- **One error format.** Every error keeps FastAPI's `detail` and adds `error`: `{"code", "message", "status", "request_id"}` (codes such as `not_found`, `forbidden`, `conflict`, `validation_error`, `rate_limited`, `unavailable`). A validation error names the field and never repeats the submitted value. The `X-Request-ID` response header carries the same id (a valid id sent by the client is kept), and an unexpected failure returns only that id; the log line has the id and the exception type.
- **Paging.** Lists take `limit` (1 to 200) and `offset` and return the total in `X-Total-Count`.
- **Examples.** Every JSON request body has an example (`backend/app/api/schemas.py`, `EXAMPLES`). A test validates each example against its model and sends each one to the running API; a schema error fails the test.
- **Coverage.** `tests/test_authorization.py` holds a role matrix; one test fails when a route has no row in it, so every route is tested for every role.
- **Vendors** (`GET /vendors`) lists the recipients of the systems you can see, one entry per vendor, with its systems and the open gaps (transfer safeguard, agreement, declaration).
- **Chat** (`POST /chat`) retrieves passages from the GDPR and the organisation's documents, keeps those that match the question, and asks the model for an answer that cites them (at most 3,000 tokens). If nothing relevant is found the answer is "No supporting evidence found." and no model is called; without a provider the passages are returned without an answer.
- **Public site.** `POST /public/leads` (no sign in, 5 per minute, a hidden `website` field catches bots; stored for the organisation named in `LEADS_ORG_ID`, read by its admins at `GET /leads`) and `GET /public/metrics` (the latest platform snapshot, marked simulated, and the size of the regulation text) and `GET /public/plans` (the price list, for the pricing page).
- Billing and analytics routes are described in the next section.

### Running it

```
docker compose up -d redis                                        # the broker
cd backend && uv run celery -A app.workers.celery_app worker -l INFO --pool=solo   # --pool=solo on Windows
cd backend && uv run celery -A app.workers.celery_app beat -l INFO                 # the daily reminders
```

### Measured (`backend/tests/test_jobs.py`, `test_end_to_end_api.py`)

| Check | Result |
|---|---|
| Full onboarding from API calls only (evidence upload to approved, published and exported record, assessment drafted) | passes, second run changes nothing |
| Full access request from API calls only (intake to closed case) | passes |
| A real Celery worker (in-memory broker) runs the stages from a queue | passes |
| Retries, permanent failure, redelivery, cancel, unreachable broker, resumable stream | covered |

### Limits

- The in-memory broker test proves the task code and the queue path, not Redis itself; there is no test against a Redis server.
- Notifications are polled (`GET /notifications`); only the job progress is pushed.
- The progress stream polls the database every 0.4 seconds per connected client and closes after five minutes (the client reconnects with `Last-Event-ID`).
- The worker and API images are not built yet; the compose file provides Redis only.

## Billing, metrics and analytics (Phase 12)

**Revenue figures are simulated.** There are no real customers and no payment processor. The seeded organisations, subscriptions, invoices and payments carry `is_simulated = true`, the metrics endpoints return `simulated: true` with a note, and the public metrics endpoint carries the same note (the interface footnote comes with the frontend phase). The calculations are real: every number is computed from the tables, never typed in.

### Plans and metering

| Plan | Base fee | Systems included | Requests included | Per extra system | Per extra request |
|---|---|---|---|---|---|
| Starter | free | 3 | 5 a month | not billed | not billed |
| Professional | $399 a month | 25 | 50 | $15 | $8 |
| Enterprise | $1,800 a month | 150 | 500 | $6 | $4 |

Usage events (`usage_events`) record active systems (a count at the end of each month), requests processed (written when a response is sent), assessments generated (written when one is drafted) and tokens used (summed per provider from the call log when a month is invoiced). Starter has no price for extras, so overage is shown in the usage report but not invoiced.

`billing.invoice_run_all` runs on the first of each month and invoices the month that ended, for the plan in force on its last day: a base line (the fee of the subscription, so a price change never rewrites history) plus a line for systems and one for requests beyond the allowance. Running a month twice returns the same invoice, and a month that has not ended is refused. Payment states (`paid`, `open`, `overdue`, `void`) come from the seed or from a deterministic stand-in (`settle_simulated`): about 90 percent of invoices are paid 3 to 25 days after the month ends, a few stay open or become overdue, and a few are voided.

### Metric definitions

Amounts are integer cents. A subscription is in force from its start date up to, but not including, its end date.

| Metric | Definition |
|---|---|
| MRR | Sum of the base fees of the subscriptions in force. Usage revenue is tracked separately and is not part of MRR. |
| New MRR | Fee of a subscription that starts for an organisation with none ending that day. |
| Expansion MRR | Increase when an organisation's subscription is replaced by a dearer one the same day. |
| Contraction MRR | Decrease when it is replaced by a cheaper one. |
| Churned MRR | Fee of a subscription that ends for an organisation with none starting that day. |
| Net new MRR | New + expansion - contraction - churned. It equals MRR today minus MRR yesterday, which a test checks for every day of a random history. |
| Net revenue retention | MRR today of the organisations that were paying 365 days ago, divided by their MRR then (stored in basis points). |
| Gross churn | Churned MRR of the month so far divided by MRR at the end of the previous month (basis points). |
| ARPA | MRR divided by the accounts that pay (a fee above zero). |
| Usage revenue | Sum of the extra-system and extra-request invoice lines (not voided) of the month, reported on the last day of the month. |

The pure functions are in `backend/app/analytics/definitions.py`; each has unit tests.

### Snapshots and endpoints

- `daily_metrics` (platform wide) and `compliance_daily_metrics` (one row per organisation and day) are written by the `analytics.nightly` job, which rebuilds the last three days each night. The platform snapshot reads every organisation, so the job connects with the database owner connection (`MIGRATION_DATABASE_URL`); the compliance rows are written through each organisation's own tenant session, so Row Level Security still applies. The API only reads.
- The compliance snapshot is rebuilt from timestamps (findings opened and resolved, approvals and their dates, the review date in the version in force, requests received and answered), so a past day shows what was known then.
- Billing: `GET /billing/plans`, `GET` and `PUT /billing/subscription`, `GET /billing/usage`, `GET /billing/invoices`, `GET /billing/invoices/{id}`, `POST /billing/invoice-run`, `POST /billing/invoices/{id}/pay` (organisation admins; the price list is open to every role).
- Analytics: `GET /analytics/revenue` and `GET /analytics/platform` (admins of the host organisation, `LEADS_ORG_ID`, only), `GET /analytics/compliance` (admin, analyst, viewer of the caller's organisation), `POST /analytics/refresh` (host admins; rebuilds the latest snapshots and drops the cache).
- Query parameters: `start`, `end` (default: the last 90 days), `granularity` (`day`, `week`, `month`), `compare=true` (adds the previous period of equal length with absolute and percent change) and `format=csv`. Flows (new MRR, requests) are summed over a period; stocks (MRR, accounts, open findings) take the last day of the period. CSV cells that start with `=`, `+`, `-` or `@` are prefixed with an apostrophe so a spreadsheet does not run them.
- Responses are cached for 60 seconds, in Redis when `CACHE_URL` is set and in memory otherwise; a cache that cannot be reached is a miss, not an error. `X-Cache` says `hit` or `miss`.

### Demonstration history

`scripts/seed_billing_history.py` (seed 42) writes 24 months for about 120 fictional organisations across five industries and four regions: sign-ups on an S shaped curve, a plan mix, churn that is higher on Starter than on Enterprise, expansion through added systems and upgrades, usage, invoices and payments, then rebuilds the daily metrics. `scripts/seed_compliance_history.py` (seed 42) writes 12 months of findings opened and closed, record approvals and reviews, assessments and access requests with realistic response times for the demonstration organisation, and the daily snapshots derived from them. Both are deterministic for a seed and accept `--reset`. In a Makefile shell: `make seed-billing RESET=--reset`.

### Reconciliation (`backend/tests/test_billing_db.py`)

| Check | Result |
|---|---|
| Net new MRR equals the change in MRR, every day and every month of a seeded history | passes |
| Base lines billed for a month equal the MRR on its last day (all invoices, including voided ones) | passes |
| Extra lines of non-voided invoices equal the usage revenue shown | passes |
| Invoice total equals the sum of its lines, for every invoice | passes |
| The same seed gives the same history; running the invoice run or the nightly job twice changes nothing | passes |
| Revenue endpoints refuse non-host users; compliance figures never include another organisation | passes |

### Limits

- The reconciliation is run on a smaller history (16 organisations, 8 months) for speed; the full 120 organisation, 24 month seed uses the same code but is not run in the test suite.
- Failovers and cache hits for seeded days are simulated figures proportional to requests, because the seed has no real call log.
- The stand-in payment outcome means no real money is involved; marking an invoice paid through the API only records the payment.
- There is no test against a real Redis server for the cache; the in-memory implementation and the key and version logic are tested.

## Frontend foundation and public site (Phase 13)

`frontend/` is a React 18 and TypeScript (strict) single page application built with Vite. It holds the public marketing site and the sign in page. The authenticated console is the next phase; `/app` is a placeholder that confirms the session and signs out.

### Stack and structure

React Router 7, TanStack Query, React Hook Form with Zod, Tailwind CSS with shadcn/ui style components over Radix primitives, Apache ECharts (only the line chart module, loaded on the pricing page), react-markdown (loaded on documentation pages), Framer Motion, Lucide icons and a self hosted Inter typeface. Only free and open source packages are used.

| Path | Contents |
|---|---|
| `src/styles/tokens.css` | The one token file: colors, radii, shadows (light theme, plus a dark theme for the console). Tailwind reads every value from it. |
| `src/components/ui/` | Button, input, label, card, badge, accordion, sheet (mobile drawer), tabs and a field wrapper that wires labels, hints and errors for screen readers. |
| `src/site/` | Layout (utility bar, mega menus, sticky header that condenses on scroll, mobile drawer, footer), pages, sections, content and the illustrations. |
| `src/lib/` | The API client (cookies, CSRF header, the error envelope), the price list and cost formula, and the queries. |
| `src/charts/` | Charts, each loaded on demand. |
| `e2e/` | Playwright tests against the production build with the API replaced by route mocks. |

Palette: navy `#0B1F3A`, primary blue `#0F62FE`, teal `#00A3A3` (decoration and text on navy only: it does not reach 4.5:1 on white), a neutral scale and status colors. Badge and link colors were darkened after the browser accessibility run found tinted backgrounds under 4.5:1.

### Pages

Home (hero, six capability cards, an animated figures band from `GET /public/metrics`, how it works, industry tiles, an interactive tour, trust summary, sample scenarios, FAQ), Platform, Solutions (an index and one page per industry), Regulations (supported and planned, labeled), Pricing (plans from the new `GET /public/plans`, a comparison table and a cost calculator with a chart), Security (implemented practices and a list of what is planned; no certification is claimed), Resources (the project documentation, read from `docs/` at build time and rendered as Markdown, three technical articles and a link to the API reference), Company, Contact (contact and demo request, stored in `leads`), Legal (sample privacy policy and terms), Status (live checks of `/health` and `/ready`), Sign in and a not found page.

Sign in posts to `/api/v1/auth/login` and sends each role to its console area. Registration is disabled and password reset is a labeled placeholder. In development Vite proxies `/api` to the API, so the cookies and the CSRF header work without CORS.

### Imagery

No third party photographs are used (the plan allowed licensed photography; original SVG avoids licensing and download steps). Logos, the Open Graph image, favicons, the pipeline diagram, industry tiles and the product illustrations are drawn in the repository and labeled as illustrations. `frontend/public/images/ATTRIBUTION.md` lists the third party assets that ship (the Inter typeface and the Lucide icons). Product screenshots from the running console come with the console phase.

### Measured

| Check | Result |
|---|---|
| Unit and component tests (`npm test`): price formula against the backend numbers, API client, forms, sign in, every page rendered with structural accessibility rules | 54 passed |
| Browser tests (`npm run e2e`, Chromium, production build): every page at 360, 768, 1280 and 1920 px has one h1, no horizontal scroll and no console error | 96 of 96 |
| Same pages checked with axe-core for WCAG 2.1 A and AA, including color contrast | 24 of 24 clean |
| Every internal link on every page leads to a real page, and every `#anchor` target exists | passes |
| Layout shift while loading and scrolling the home page | below 0.1 |
| Home page does not download the chart or Markdown code | passes |
| Lighthouse 12, desktop preset, local production preview, home / pricing / platform / resources | performance 100 / 99 / 100 / 99, accessibility 100 on all four, best practices 96 / 96 / 100 / 100, SEO 100 on all four (home was 91 until the generic "Learn more" links got descriptive text) |
| `npm audit --omit=dev` | 0 vulnerabilities |
| ESLint (with the accessibility rules), `tsc --noEmit` strict, Prettier, long dash check (`npm run check:dash`) | clean |

### Limits

- Lighthouse was run against a local preview with no API behind it and without compression or a CDN, so a hosted result will differ. The interface text was only checked on Chromium.
- The tour and the hero show illustrations drawn with markup, not screenshots, and say so in a caption.
- The browser tests replace the API with mocks. The calls the site makes (`public/plans`, `public/metrics`, `public/leads`, `auth/login`, `auth/me`, `/health`, `/ready`) are covered by the backend tests, but no test drives the browser against a running API.
- The API reference link points at `/docs` of the API; it works when the site and the API share an origin (or the proxy forwards it).
- `/app` is a placeholder until the console is built.

### Running it

```
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to http://127.0.0.1:8000
npm test           # Vitest
npm run build && npm run e2e
npm run images     # rebuild favicons and the Open Graph image from the SVG sources
```
