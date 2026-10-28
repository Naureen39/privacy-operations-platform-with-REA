# Security review

A checklist in the style of the OWASP Application Security Verification Standard (version 4, level 2 headings), with what was checked, how, and what is still open. It was written from the code and the tests of this repository on the date of the evaluation (`docs/evaluation.md`), not from a third party assessment: no external penetration test has been done and no certification is claimed.

Status: **Verified** (a test or a scan checks it), **Reviewed** (read in the code, no automated check), **Partial** (some of it is in place), **Open** (not done), **Not applicable**.

## Checklist

| Area | Requirement | Status | Evidence |
|---|---|---|---|
| V1 Architecture | Trust boundaries are drawn and the tenant boundary is enforced below the application | Verified | Row Level Security forced on every tenant table, restricted application role: `tests/test_tenant_isolation.py` |
| V1 | Uploaded files are analysed in isolation | Verified | Runner containers: no route out, read only root, no capabilities, limits (`docs/security.md`, built images inspected) |
| V1 | A written threat model | Partial | The model is in `docs/security.md`; there is no separate diagram or STRIDE table |
| V2 Authentication | Passwords hashed with argon2id, minimum length enforced | Verified | `tests/test_security_units.py`, `tests/test_auth_api.py` |
| V2 | Lockout and the same response for every failure | Verified | `tests/test_auth_api.py` |
| V2 | Registration disabled; accounts provisioned by an administrator | Verified | `tests/test_auth_api.py` |
| V2 | Multi factor authentication, single sign on, password reset | Open | Planned. The sign in page says reset is unavailable |
| V3 Session | Short lived access token, rotating refresh token, reuse revokes the family | Verified | `tests/test_auth_api.py` |
| V3 | Cookies are httpOnly, Secure, SameSite | Verified | `tests/test_auth_api.py` |
| V3 | Logout and switching organization revoke the old tokens | Verified | `tests/test_auth_api.py`, `tests/test_console_api.py` |
| V4 Access control | Every route declares its roles; every route refuses anonymous requests | Verified | `tests/test_authorization.py` (route walk, 118 protected routes) |
| V4 | Every route is tested for every role | Verified | The role matrix and its coverage test |
| V4 | A system owner sees only owned systems; other organizations answer 404 | Verified | `tests/test_authorization.py`, `tests/test_tenant_isolation.py` |
| V4 | No insecure direct object reference across tenants | Verified | Row Level Security; `tests/test_tenant_isolation.py` |
| V5 Validation | Request bodies validated and unknown fields refused | Verified | Pydantic models with `extra="forbid"`; every example is validated by `tests/test_api_contract.py` |
| V5 | SQL is parameterized | Reviewed | SQLAlchemy throughout; the few text statements use bound parameters, and the one built from constants (`daily_metrics` columns) is marked and reviewed. Bandit reports nothing above low severity |
| V5 | Output encoding; no raw HTML from data | Reviewed | React escapes; Markdown is rendered without raw HTML; CSV cells starting with `=`, `+`, `-`, `@` are prefixed (`tests/test_billing_units.py`) |
| V5 | Server side request forgery | Verified | `tests/test_security_units.py` (the URL guard), runner re-validation |
| V5 | Prompt injection | Verified | `tests/test_prompt_injection.py`, `tests/test_llm_router.py` |
| V6 Cryptography | Evidence encrypted at rest, authenticated, bound to its record | Verified | AES-256-GCM: `tests/test_evidence_api.py`, `tests/test_security_units.py` |
| V6 | Subject identifiers keyed hashed | Verified | `tests/test_dsar_units.py`, `tests/test_dsar_acceptance.py` |
| V6 | Secrets come from the environment and the API refuses to start without them | Verified | `tests/test_security_units.py` |
| V7 Errors and logging | Errors show a request id and no internals | Verified | `tests/test_api_contract.py` |
| V7 | No personal data, password, token or key is logged | Verified | `tests/test_log_hygiene.py` |
| V7 | Security relevant actions are audited; the log is append only | Verified | `tests/test_authorization.py`, `tests/test_tenant_isolation.py` |
| V8 Data protection | API responses are not cached by browsers | Verified | `tests/test_authorization.py` (headers on every response) |
| V8 | Only metadata and masked text reach a model | Verified | `tests/test_llm_units.py`, `tests/test_llm_router.py`, `tests/test_prompt_injection.py` |
| V8 | Evidence is deleted after its retention period | Verified | `tests/test_retention.py` |
| V9 Communications | Strict transport security and the usual headers | Verified | `tests/test_authorization.py` |
| V9 | TLS terminates in front of the API | Open | A hosted deployment with Caddy is not part of the repository yet |
| V10 Malicious code | Uploaded files are never executed | Verified | Executable formats refused: `tests/test_evidence_api.py` |
| V10 | Dependencies scanned | Verified | See the scan table below |
| V11 Business logic | Two person approval, deadlines, extension limits | Verified | `tests/test_records.py`, `tests/test_dsar_acceptance.py` |
| V11 | Rate limits on sign in, public forms and every route | Verified | `tests/test_authorization.py`, `tests/test_platform.py` |
| V12 Files | Size cap, extension allowlist, content checks, safe names and paths | Verified | `tests/test_evidence_api.py` |
| V12 | A 50 MB capture is processed within a memory limit | Verified | `docs/evaluation.md`, section 11 |
| V13 API | CSRF protection on changes; CORS allowlist | Verified | `tests/test_authorization.py` |
| V13 | The interactive API documentation is not served in production | Partial | It is served at `/docs` with a relaxed policy; a hosted deployment should disable it or put it behind the proxy |
| V14 Configuration | No default secrets, debug off, pinned dependencies with lock files | Verified | `uv.lock`, `package-lock.json`, startup checks |
| V14 | Container images are small, non root and scanned | Partial | The two runner images are hardened and scanned (below); the API and worker images do not exist yet |

## Scans

| Scan | Tool | Result |
|---|---|---|
| Python dependencies | pip-audit on the exported lock file | One finding (`certifi`, fixed in 2026.10.19); the lock file was updated to 2026.10.23 and the scan is clean |
| Frontend dependencies | `npm audit --omit=dev` | 0 vulnerabilities (react-router was moved to version 7 in an earlier phase for two advisories) |
| REA runner dependencies | `npm audit --omit=dev` | 2 high findings in `zod` through the pinned `rea-agents` (memory exhaustion on oversized collections). The release pins `zod` 4.4.3 and offers no fix; an npm override to 4.6.7 clears the finding, and the runner tests (47, one skipped) and the evaluation pass with it |
| Secrets in the history | gitleaks | One finding, a made up password in an OpenAPI example (`a-long-passphrase-123`), allowlisted in `.gitleaks.toml`; the history is clean |
| Static analysis | bandit (`-ll`) | No medium or high findings after review: eight reviewed sites (string built SQL over quoted identifiers or constants, and plain text templates that are never rendered as HTML) carry an inline `nosec` with the matching ruff `noqa`. Low findings are the `assert` statements marked for the type checker and the use of `random` in the simulation seeds |
| Repository files | Trivy `fs` (vulnerabilities, secrets, misconfiguration) | No high or critical findings |
| Runner images | Trivy `image`, fixable high and critical only | Clean after the fix below (Debian packages 0, Node packages 0) |

## Findings and what was done

| Finding | Severity | Disposition |
|---|---|---|
| `certifi` known vulnerability | Moderate | Fixed by upgrading the lock file |
| `zod` memory exhaustion through `rea-agents` | High | Fixed with an npm override; tests pass. The risk was also bounded by the runner's memory, process and time limits |
| gitleaks match on an example password | Informational | Allowlisted with a comment |
| REA refuses a capture of about 32 MiB or more | Functional | Found by the load check. The platform records REA's error and uses the fallback parser, so a 50 MB capture is analysed (see `docs/evaluation.md`) |
| Trivy: 4 high findings (`brace-expansion`, `undici`) in both runner images | High | They were in the copy of npm bundled with the Node base image, which the runner never loads. The Dockerfiles now remove npm and corepack after the install step; both images were rebuilt and rescanned clean, and the runner still starts |
| Label and visible text of two buttons differed | Accessibility | Fixed in the previous phase's browser checks |

## Open items

- Multi factor authentication, single sign on and password reset.
- An external penetration test.
- API and worker images with a scan, and TLS termination for a hosted demonstration.
- The continuous integration workflow (`.github/workflows/ci.yml`) has not been run on GitHub; each of its steps was run locally.
- Dependency scans cover known advisories only.
