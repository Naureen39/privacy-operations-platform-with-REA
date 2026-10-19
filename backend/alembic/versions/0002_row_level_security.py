"""row level security, application role, and grants

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19 16:00:00

Tenancy model
-------------
The application connects as the restricted role `processledger_app` (no superuser,
no BYPASSRLS, not the table owner). Each request sets two transaction local settings:

    app.org_id   the organization the request acts for
    app.user_id  the authenticated user (used by the memberships policy)

Every tenant table has a policy comparing org_id with app_current_org(). When the
setting is missing, app_current_org() is NULL and no row matches, so the default is
"see nothing". FORCE ROW LEVEL SECURITY applies the policies to the table owner too.

Tables intentionally outside the tenant policy:
  users, refresh_tokens   identity records looked up by unique secret or email
  plans, regulation_chunks, daily_metrics   shared, read only for the application role
"""

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "processledger_app"

# Tables with a non-null org_id and the standard policy.
TENANT_TABLES = [
    "systems",
    "evidence_items",
    "discovery_runs",
    "discovery_evidence",
    "data_elements",
    "recipients",
    "technologies",
    "processing_activities",
    "activity_versions",
    "activity_systems",
    "dpias",
    "dpia_risks",
    "findings",
    "tasks",
    "approvals",
    "comments",
    "access_requests",
    "request_results",
    "request_responses",
    "documents",
    "document_chunks",
    "llm_cache",
    "llm_calls",
    "subscriptions",
    "usage_events",
    "invoices",
    "invoice_lines",
    "compliance_daily_metrics",
    "leads",
]

# Tables with a custom policy set (see below).
SPECIAL_TABLES = ["organizations", "memberships", "audit_log"]

ALL_RLS_TABLES = TENANT_TABLES + SPECIAL_TABLES

FULL_ACCESS = ["users", "refresh_tokens"]
READ_ONLY = ["plans", "regulation_chunks", "daily_metrics"]


def _sql_literal(value: str) -> str:
    # exec_driver_sql passes the string to psycopg, so '%' must be doubled.
    return "'" + value.replace("'", "''").replace("%", "%%") + "'"


def upgrade() -> None:
    password = os.environ.get("APP_DB_PASSWORD", "processledger_app_dev")
    op.get_bind().exec_driver_sql(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
            END IF;
        END
        $$
        """)
    op.get_bind().exec_driver_sql(
        f"ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS "
        f"PASSWORD {_sql_literal(password)}"
    )

    op.execute("""
        CREATE FUNCTION app_current_org() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('app.org_id', true), '')::uuid $$
        """)
    op.execute("""
        CREATE FUNCTION app_current_user() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$
        """)

    for table in ALL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    for table in TENANT_TABLES:
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org())"
        )

    # organizations: a tenant sees and updates only its own row. Rows are created and
    # deleted by the provisioning role (table owner), never by the application role.
    op.execute(
        "CREATE POLICY tenant_isolation ON organizations "
        "USING (id = app_current_org()) WITH CHECK (id = app_current_org())"
    )

    # memberships: a user may read their own memberships in any organization (needed to
    # choose or switch organizations). Writes are limited to the current organization.
    op.execute(
        "CREATE POLICY membership_select ON memberships FOR SELECT "
        "USING (org_id = app_current_org() OR user_id = app_current_user())"
    )
    op.execute(
        "CREATE POLICY membership_insert ON memberships FOR INSERT "
        "WITH CHECK (org_id = app_current_org())"
    )
    op.execute(
        "CREATE POLICY membership_update ON memberships FOR UPDATE "
        "USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org())"
    )
    op.execute(
        "CREATE POLICY membership_delete ON memberships FOR DELETE "
        "USING (org_id = app_current_org())"
    )

    # audit_log: append only. Events without an organization (for example a failed login
    # for an unknown account) may be inserted but are not readable by tenants.
    op.execute(
        "CREATE POLICY audit_select ON audit_log FOR SELECT USING (org_id = app_current_org())"
    )
    op.execute(
        "CREATE POLICY audit_insert ON audit_log FOR INSERT "
        "WITH CHECK (org_id IS NULL OR org_id = app_current_org())"
    )

    # Grants for the application role.
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    for table in TENANT_TABLES + ["memberships"] + FULL_ACCESS:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, UPDATE ON organizations TO {APP_ROLE}")
    op.execute(f"GRANT SELECT, INSERT ON audit_log TO {APP_ROLE}")
    for table in READ_ONLY:
        op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")

    for table in TENANT_TABLES:
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
    op.execute("DROP POLICY tenant_isolation ON organizations")
    for policy in (
        "membership_select",
        "membership_insert",
        "membership_update",
        "membership_delete",
    ):
        op.execute(f"DROP POLICY {policy} ON memberships")
    op.execute("DROP POLICY audit_select ON audit_log")
    op.execute("DROP POLICY audit_insert ON audit_log")

    for table in ALL_RLS_TABLES:
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP FUNCTION app_current_user()")
    op.execute("DROP FUNCTION app_current_org()")
