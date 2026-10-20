# Security Model (Phase 2 baseline)

This document describes what is implemented and tested. Nothing here is a claim about certifications.

## Authentication

- Registration is disabled. Accounts are created by the owner role (`scripts/seed_demo_users.py`, `app/services/provisioning.py`).
- Passwords: argon2id, minimum 12 characters (enforced when an account is provisioned). Unknown accounts are verified against a dummy hash so timing does not reveal whether an account exists, and every failure returns the same response.
- Lockout: 5 consecutive failures lock the account for 15 minutes (`MAX_FAILED_LOGINS`, `LOCKOUT_MINUTES`). A locked account refuses the correct password too, with the same generic response.
- Access token: 15 minute JWT (HS256, `typ=access`, `exp`/`iat`/`sub`/`org` required) in an `httpOnly; Secure; SameSite=Lax` cookie.
- Refresh token: random 384 bit value, stored as a SHA-256 hash, 7 day lifetime, rotated on every use, delivered in an `httpOnly; Secure; SameSite=Lax` cookie scoped to `/api/v1/auth`. Presenting an already rotated token revokes the whole token family (theft detection). Logout revokes the family.
- The role in the token is informational. Every request re-reads the membership and the user's active flag from the database, so removing a membership or deactivating a user takes effect immediately.

## Authorization

- `require_role(...)` is a dependency on every protected route. A test walks the route table and fails if any route lacks one, and another confirms every protected route refuses anonymous requests.
- Roles: `admin`, `analyst`, `system_owner`, `viewer`. The role matrix is tested for every route and role.
- `system_owner` is restricted to systems where they are the owner: other systems answer 404, and list endpoints are filtered.
- Tenant isolation is enforced in the database (see `docs/database.md`) and re-tested through the API.

## CSRF

State changing requests (`POST`, `PUT`, `PATCH`, `DELETE`) that carry a session cookie must send `X-CSRF-Token` equal to the `pl_csrf` cookie (double submit). The cookie is readable by the frontend, the session cookies are not. A token from another session is rejected.

## HTTP hardening

- Rate limits with slowapi: strict on login (`LOGIN_RATE_LIMIT`, default 5 per minute), a default limit on every route (`DEFAULT_RATE_LIMIT`). The in-memory store is per process; Phase 11 moves it to Redis.
- CORS: explicit origin allowlist, credentials allowed only for those origins, limited methods and headers.
- Headers on every response: `Content-Security-Policy` (restrictive for the API, relaxed only for `/docs`), `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`. API responses are `Cache-Control: no-store`.
- Startup refuses to run without a `JWT_SECRET` of at least 32 characters and an `EVIDENCE_ENCRYPTION_KEY` that decodes to 32 bytes. No secret has a default.

## Uploads and evidence

- Size cap (`MAX_UPLOAD_BYTES`, read with a one byte overrun so oversized files are never held in memory), extension allowlist per evidence kind, content checks (HAR must be a JSON object with `log`, SQLite and PDF magic bytes, text files must be text) and rejection of executable formats (PE, ELF, Mach-O) whatever the extension says.
- File names are sanitised and never used as storage paths. Storage paths are built from identifiers and checked to stay inside the evidence directory.
- Files are encrypted at rest with AES-256-GCM. A fresh nonce is used per file and the evidence id is bound as associated data, so a blob moved to another record fails authentication.
- The retention job (`app/services/retention.py`) deletes evidence older than the organization's `evidence_retention_days` (default 365), removes the files, and writes an audit entry. It is idempotent and processes each organization in its own tenant session. Scheduling is added with the worker in Phase 11.
- Uploaded files are only ever read as data. No code path executes them.

## Website observation (SSRF protection)

`app/core/urlguard.py` accepts a URL only if all of the following hold:

1. Scheme is `http` or `https`, no credentials in the URL, port in `OBSERVATION_ALLOWED_PORTS`.
2. The host is on `OBSERVATION_ALLOWED_HOSTS` (exact names or `*.suffix`, never the bare apex for a wildcard).
3. The host is resolved on the server and every returned address is safe: loopback, link local (including cloud metadata), multicast, unspecified and reserved addresses are always refused; private ranges are accepted only inside `OBSERVATION_ALLOWED_NETWORKS` (the demo network); IPv4 mapped IPv6 addresses are unwrapped first.

The resolved addresses are returned so the runner connects to them without a second lookup (no DNS rebinding window), and redirects must be validated again. The API only registers the URL; the `rea-browser` runner validates again immediately before connecting.

## Runner isolation

`docker-compose.yml` (profile `runners`). Both runners are called by the worker over HTTP with a shared token (`x-runner-token`, compared in constant time) on the private `runners` network, which is declared `internal: true`.

| Setting | rea-offline | rea-browser |
|---|---|---|
| Networks | `runners` (internal) | `runners` and `estate` (both internal) |
| Route to the internet | none | none |
| User | 10001, non root | 10002, non root |
| Root file system | read only; `/tmp` and `/work` are `noexec` tmpfs | read only; `/tmp` and `/work` are `noexec` tmpfs |
| Evidence | volume `rea_input`, mounted read only | volume `rea_input`, mounted read only |
| Capabilities | all dropped, `no-new-privileges` | all dropped, `no-new-privileges` |
| Limits | 1 CPU, 1 GB, 128 processes | 1.5 CPU, 2 GB, 256 processes |
| Time limit | per call (`REA_TIMEOUT_SECONDS`) | hard timeout `REA_BROWSER_TIMEOUT_SECONDS`, browser killed |
| Commands | HAR, SQLite, JavaScript | website observation only |

Checked against the built images: the container runs as the unprivileged user, a request for `https://example.com` fails to resolve, writes to `/input` and to the application directory fail with "read only file system", path traversal in a request is refused, and a command that belongs to the other role is refused.

The wrapper (`rea-runner/`) adds its own limits:

- A fixed set of four commands, each with validated options; unknown options are rejected. REA is started without a shell, with a minimal environment.
- Paths are relative to the input directory and are resolved with symbolic links followed; anything that leaves the directory is refused.
- Output is capped (256 MiB by default); an oversized result is an error, not a truncation.
- Website observation: a URL is checked again with the same rules as the API (`urlguard`): http or https, no credentials, allowlisted host, allowed port, every resolved address public or inside the demo network, and the validated address pinned in the browser (`--host-resolver-rules`). For a saved page the browser can resolve nothing except loopback. Chromium runs without its own sandbox (`--no-sandbox`) because the container is the boundary; the profile directory is deleted afterwards and the browser is killed on timeout.
- Uploaded files are analysed as data. Nothing is executed.

## Audit log

Written in the same transaction as the action. Currently recorded: login (success and failure, lockout, refresh reuse), logout, system create, update and delete, evidence upload, rejected upload, URL registration and rejection, retention purge, settings changes, discovery runs and reads of stored extractor output. Approval, export and request handling entries are added with those features using the same `write_audit` helper. The table is append only for the application role. Details never contain e-mail addresses or file contents; failed logins record the account id only when the account exists.

## Known limitations

- Stored discovery output keeps no sample values, but names of fields, columns, hosts and paths are kept and can themselves be sensitive in a real estate. Access to the raw output is limited to administrators and analysts and is audited.
- Rate limit counters are per process until Redis arrives.
- Access tokens cannot be revoked before they expire (15 minutes), but the database check on every request makes membership and account changes immediate.
- The JWT secret is symmetric. Rotation requires a restart and signs everyone out.
- The password policy is length only, as specified. There is no breached password check.
