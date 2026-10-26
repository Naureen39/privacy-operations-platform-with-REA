"""background jobs, job events, notifications and task de-duplication

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-24 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "processledger_app"
NEW_TABLES = ["jobs", "job_events", "notifications"]


def _org_id() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        "org_id",
        sa.Uuid(),
        server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
        nullable=False,
    )


def _jsonb(name: str, default: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name, postgresql.JSONB(astext_type=sa.Text()), server_default=default, nullable=False
    )


def _now(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=40), server_default="onboarding", nullable=False),
        sa.Column("state", sa.String(length=32), server_default="queued", nullable=False),
        _jsonb("stages", "{}"),
        _jsonb("params", "{}"),
        _jsonb("result", "{}"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _now("created_at"),
        _now("updated_at"),
        _org_id(),
        sa.CheckConstraint(
            "state IN ('queued','running','succeeded','failed','cancelled')",
            name=op.f("ck_jobs_jobstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_jobs_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_jobs_created_by_users"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_jobs_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
    )
    op.create_index(op.f("ix_jobs_org_id"), "jobs", ["org_id"])
    op.create_index(op.f("ix_jobs_system_id"), "jobs", ["system_id"])

    op.create_table(
        "job_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=True),
        sa.Column("event", sa.String(length=30), nullable=False),
        _jsonb("detail", "{}"),
        _now("created_at"),
        _org_id(),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"], name=op.f("fk_job_events_job_id_jobs"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_job_events_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_job_events_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_job_events")),
    )
    op.create_index(op.f("ix_job_events_org_id"), "job_events", ["org_id"])
    op.create_index(op.f("ix_job_events_job_id"), "job_events", ["job_id"])

    op.create_table(
        "notifications",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        _now("created_at"),
        _org_id(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_notifications_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "org_id",
            "user_id",
            "dedupe_key",
            name=op.f("uq_notifications_org_id_user_id_dedupe_key"),
        ),
    )
    op.create_index(op.f("ix_notifications_org_id"), "notifications", ["org_id"])
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            "USING (org_id = app_current_org()) WITH CHECK (org_id = app_current_org())"
        )
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE job_events_seq_seq TO {APP_ROLE}")

    op.add_column("tasks", sa.Column("dedupe_key", sa.String(length=200), nullable=True))
    op.create_unique_constraint(
        op.f("uq_tasks_org_id_dedupe_key"), "tasks", ["org_id", "dedupe_key"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_tasks_org_id_dedupe_key"), "tasks", type_="unique")
    op.drop_column("tasks", "dedupe_key")
    for table in reversed(NEW_TABLES):
        op.execute(f"DROP POLICY tenant_isolation ON {table}")
        op.drop_table(table)
