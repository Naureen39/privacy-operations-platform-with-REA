# Architecture

This document grows with the phases. It currently covers evidence discovery (Phase 4). The system onboarding pipeline is `CREATED, EVIDENCE_ATTACHED, DISCOVERING, CLASSIFIED, FUSED, DRAFTED, AWAITING_REVIEW, APPROVED, PUBLISHED, FAILED`; this phase implements the first extraction step of `DISCOVERING`.

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
