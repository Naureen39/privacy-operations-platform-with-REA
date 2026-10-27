# Database and Tenancy

## Running locally

```
docker compose up -d db
cd backend
uv sync
uv run alembic upgrade head      # connects as the owner role (MIGRATION_DATABASE_URL)
uv run pytest                    # starts its own throwaway PostgreSQL container
```

Migrations:

| Revision | Content |
|---|---|
| 0001 | `CREATE EXTENSION vector`, all tables from the data model, HNSW indexes (`vector_cosine_ops`) on `data_elements`, `document_chunks`, `regulation_chunks`, generated `tsvector` columns with GIN indexes |
| 0002 | Application role, `app_current_org()` and `app_current_user()`, Row Level Security policies, grants |
| 0003 | `organizations.settings`, `refresh_tokens.session_org_id` (Phase 2) |
| 0004 | `context` on `data_elements`, `recipients` and `technologies`; `source_kind` on `data_elements`; `raw_sha256` and `raw_truncated` on `discovery_evidence` (Phase 4) |
| 0005 | `taxonomy_entries`: the embedded taxonomy for the classifier (HNSW cosine index, read only for the application role) (Phase 5) |
| 0006 | `regulation_chunks.chunk_key` (stable citation key), `documents.evidence_item_id`, full text vectors that include the heading or article title (Phase 6) |
| 0007 | `dpia_screenings`: the result of scoring an activity against the impact assessment criteria (tenant table with Row Level Security) (Phase 9) |
| 0008 | `access_requests`: `identifier_type`, `reference` (unique per organisation), `identity_checklist`, `rejection_reason`, `searched_at`, `responded_at` (Phase 10) |
| 0009 | `jobs`, `job_events` (ordered by an identity column, for the progress stream), `notifications`, and `tasks.dedupe_key` (tenant tables with Row Level Security) (Phase 11) |
| 0010 | Seeds the three plans; adds `paying_accounts`, `arpa_cents`, `nrr_bp`, `gross_churn_bp` to `daily_metrics` and an index on `invoices (org_id, period_start)` (Phase 12) |

Both directions are tested: upgrade, downgrade to 0001, downgrade to base, upgrade again, plus a check that the models and the migrated schema have no drift.

## Tenancy model

- Two roles. The owner role runs migrations and provisioning (creating organizations, seeding). The application connects as `processledger_app`: not a superuser, no `BYPASSRLS`, owns no tables.
- Each request runs in a transaction that sets `app.org_id` and `app.user_id` (transaction local). `TenantSession` re-applies them at the start of every transaction, so a commit inside a unit of work cannot drop the tenant.
- Every tenant table has `org_id`, `ENABLE` and `FORCE ROW LEVEL SECURITY`, and the policy `org_id = app_current_org()` for reads and writes. With no tenant set the function returns NULL and nothing matches. `org_id` defaults from the setting, so inserts need not pass it, and inserting for another organization is rejected by the policy.
- Repositories do not filter by tenant. The database is the authority.

Exceptions, all deliberate and covered by tests:

| Table | Treatment |
|---|---|
| `organizations` | Policy on `id`. The application role can read and update its own row, but cannot insert or delete organizations. |
| `memberships` | A user can read their own memberships in any organization (to choose an organization). Writes are limited to the current organization. |
| `audit_log` | Append only (no UPDATE or DELETE privilege). Events without an organization can be inserted but are not readable by tenants. |
| `users`, `refresh_tokens` | Identity records looked up by email or by hashed secret before the tenant is known. No policy. Phase 2 must keep queries on them lookup-only. |
| `plans`, `regulation_chunks`, `daily_metrics` | Shared. Read only for the application role. |

## Known limitations

- Foreign keys between tenant tables are single column. PostgreSQL checks them without row security, so a row could reference another organization's row if its identifier were known. Composite `(org_id, id)` keys are a possible hardening.
- `daily_metrics` holds platform wide revenue aggregates and `compliance_daily_metrics` is per tenant. Cross-organization revenue reads (Phase 12) need a dedicated privileged path rather than the tenant role.
