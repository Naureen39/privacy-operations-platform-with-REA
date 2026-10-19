"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-19 15:18:54.552024
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "daily_metrics",
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("mrr_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("new_mrr_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("expansion_mrr_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("contraction_mrr_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("churned_mrr_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("usage_revenue_cents", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("accounts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("systems", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requests", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "tokens_by_provider",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("failovers", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cache_hits", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.PrimaryKeyConstraint("metric_date", name=op.f("pk_daily_metrics")),
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("industry", sa.String(length=80), nullable=True),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
        sa.UniqueConstraint("slug", name=op.f("uq_organizations_slug")),
    )
    op.create_table(
        "plans",
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("monthly_fee_cents", sa.Integer(), nullable=False),
        sa.Column("included_systems", sa.Integer(), nullable=False),
        sa.Column("included_requests", sa.Integer(), nullable=False),
        sa.Column("extra_system_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extra_request_cents", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
        sa.UniqueConstraint("code", name=op.f("uq_plans_code")),
    )
    op.create_table(
        "regulation_chunks",
        sa.Column("regulation", sa.String(length=40), server_default="GDPR", nullable=False),
        sa.Column("chapter", sa.String(length=200), nullable=True),
        sa.Column("article", sa.Integer(), nullable=True),
        sa.Column("paragraph", sa.String(length=20), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_regulation_chunks")),
    )
    op.create_index(
        op.f("ix_regulation_chunks_article"), "regulation_chunks", ["article"], unique=False
    )
    op.create_index(
        "ix_regulation_chunks_embedding_hnsw",
        "regulation_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        "ix_regulation_chunks_tsv",
        "regulation_chunks",
        ["tsv"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_table(
        "users",
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.literal_column("lower(email)")], unique=True
    )
    op.create_table(
        "access_requests",
        sa.Column("subject_hash", sa.String(length=128), nullable=False),
        sa.Column("received_date", sa.Date(), nullable=False),
        sa.Column("deadline_date", sa.Date(), nullable=False),
        sa.Column("extended", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("extension_months", sa.Integer(), server_default="0", nullable=False),
        sa.Column("extension_reason", sa.Text(), nullable=True),
        sa.Column(
            "identity_verified", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "status",
            sa.Enum(
                "received",
                "identity_verification",
                "searching",
                "drafting",
                "awaiting_approval",
                "responded",
                "closed",
                "rejected",
                name="requeststatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="received",
            nullable=False,
        ),
        sa.Column("assigned_to", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('received', 'identity_verification', 'searching', 'drafting', 'awaiting_approval', 'responded', 'closed', 'rejected')",
            name=op.f("ck_access_requests_requeststatus"),
        ),
        sa.ForeignKeyConstraint(
            ["assigned_to"],
            ["users.id"],
            name=op.f("fk_access_requests_assigned_to_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_access_requests_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_access_requests")),
    )
    op.create_index(op.f("ix_access_requests_org_id"), "access_requests", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_access_requests_subject_hash"), "access_requests", ["subject_hash"], unique=False
    )
    op.create_table(
        "approvals",
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "approved",
                "rejected",
                name="approvalstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')",
            name=op.f("ck_approvals_approvalstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"],
            ["users.id"],
            name=op.f("fk_approvals_decided_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_approvals_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name=op.f("fk_approvals_requested_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approvals")),
    )
    op.create_index("ix_approvals_entity", "approvals", ["entity_type", "entity_id"], unique=False)
    op.create_index(op.f("ix_approvals_org_id"), "approvals", ["org_id"], unique=False)
    op.create_table(
        "audit_log",
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=True,
        ),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=80), nullable=False),
        sa.Column("entity_type", sa.String(length=80), nullable=True),
        sa.Column("entity_id", sa.String(length=80), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name=op.f("fk_audit_log_actor_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_audit_log_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_action", "audit_log", ["action"], unique=False)
    op.create_index(op.f("ix_audit_log_org_id"), "audit_log", ["org_id"], unique=False)
    op.create_index(
        "ix_audit_log_org_id_created_at", "audit_log", ["org_id", "created_at"], unique=False
    )
    op.create_table(
        "comments",
        sa.Column("entity_type", sa.String(length=80), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("author_user_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["author_user_id"],
            ["users.id"],
            name=op.f("fk_comments_author_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_comments_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index("ix_comments_entity", "comments", ["entity_type", "entity_id"], unique=False)
    op.create_index(op.f("ix_comments_org_id"), "comments", ["org_id"], unique=False)
    op.create_table(
        "compliance_daily_metrics",
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("approved_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column("stale_records", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "open_findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "assessments_by_status",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("requests_open", sa.Integer(), server_default="0", nullable=False),
        sa.Column("requests_overdue", sa.Integer(), server_default="0", nullable=False),
        sa.Column("discovery_confidence_avg", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("rea_run_duration_ms_avg", sa.Integer(), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_compliance_daily_metrics_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_compliance_daily_metrics")),
        sa.UniqueConstraint(
            "org_id", "metric_date", name=op.f("uq_compliance_daily_metrics_org_id_metric_date")
        ),
    )
    op.create_index(
        op.f("ix_compliance_daily_metrics_org_id"),
        "compliance_daily_metrics",
        ["org_id"],
        unique=False,
    )
    op.create_table(
        "leads",
        sa.Column(
            "kind",
            sa.Enum(
                "contact",
                "demo_request",
                name="leadkind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("company", sa.String(length=200), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint("kind IN ('contact', 'demo_request')", name=op.f("ck_leads_leadkind")),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_leads_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_leads")),
    )
    op.create_index(op.f("ix_leads_org_id"), "leads", ["org_id"], unique=False)
    op.create_table(
        "llm_cache",
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("response", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("hit_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_llm_cache_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_cache")),
        sa.UniqueConstraint(
            "org_id", "request_hash", name=op.f("uq_llm_cache_org_id_request_hash")
        ),
    )
    op.create_index(op.f("ix_llm_cache_org_id"), "llm_cache", ["org_id"], unique=False)
    op.create_table(
        "memberships",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "admin",
                "analyst",
                "system_owner",
                "viewer",
                name="role",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('admin', 'analyst', 'system_owner', 'viewer')",
            name=op.f("ck_memberships_role"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_memberships_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_memberships_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_memberships")),
        sa.UniqueConstraint("org_id", "user_id", name=op.f("uq_memberships_org_id_user_id")),
    )
    op.create_index(op.f("ix_memberships_org_id"), "memberships", ["org_id"], unique=False)
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"], unique=False)
    op.create_table(
        "processing_activities",
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column(
            "purposes", postgresql.ARRAY(sa.Text()), server_default=sa.text("'{}'"), nullable=False
        ),
        sa.Column(
            "data_subjects",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "data_categories",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "recipients",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "transfers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("retention", sa.Text(), nullable=True),
        sa.Column("security_measures", sa.Text(), nullable=True),
        sa.Column("lawful_basis", sa.String(length=80), nullable=True),
        sa.Column("special_category_condition", sa.String(length=200), nullable=True),
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "awaiting_review",
                "approved",
                "published",
                "archived",
                name="activitystatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("current_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_review_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'awaiting_review', 'approved', 'published', 'archived')",
            name=op.f("ck_processing_activities_activitystatus"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_processing_activities_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_processing_activities_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_processing_activities")),
    )
    op.create_index(
        op.f("ix_processing_activities_org_id"), "processing_activities", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_processing_activities_owner_user_id"),
        "processing_activities",
        ["owner_user_id"],
        unique=False,
    )
    op.create_table(
        "refresh_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_tokens_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_tokens_family_id"), "refresh_tokens", ["family_id"], unique=False
    )
    op.create_index(op.f("ix_refresh_tokens_user_id"), "refresh_tokens", ["user_id"], unique=False)
    op.create_table(
        "subscriptions",
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "canceled",
                name="subscriptionstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("base_fee_cents", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Date(), nullable=False),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'canceled')", name=op.f("ck_subscriptions_subscriptionstatus")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_subscriptions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["plans.id"],
            name=op.f("fk_subscriptions_plan_id_plans"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(op.f("ix_subscriptions_org_id"), "subscriptions", ["org_id"], unique=False)
    op.create_index(op.f("ix_subscriptions_plan_id"), "subscriptions", ["plan_id"], unique=False)
    op.create_table(
        "systems",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "CREATED",
                "EVIDENCE_ATTACHED",
                "DISCOVERING",
                "CLASSIFIED",
                "FUSED",
                "DRAFTED",
                "AWAITING_REVIEW",
                "APPROVED",
                "PUBLISHED",
                "FAILED",
                name="jobstate",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="CREATED",
            nullable=False,
        ),
        sa.Column("last_discovery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('CREATED', 'EVIDENCE_ATTACHED', 'DISCOVERING', 'CLASSIFIED', 'FUSED', 'DRAFTED', 'AWAITING_REVIEW', 'APPROVED', 'PUBLISHED', 'FAILED')",
            name=op.f("ck_systems_jobstate"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_systems_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_systems_owner_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_systems")),
        sa.UniqueConstraint("org_id", "slug", name=op.f("uq_systems_org_id_slug")),
    )
    op.create_index(op.f("ix_systems_org_id"), "systems", ["org_id"], unique=False)
    op.create_index(op.f("ix_systems_owner_user_id"), "systems", ["owner_user_id"], unique=False)
    op.create_table(
        "activity_systems",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["processing_activities.id"],
            name=op.f("fk_activity_systems_activity_id_processing_activities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_activity_systems_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_activity_systems_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("activity_id", "system_id", name=op.f("pk_activity_systems")),
    )
    op.create_index(
        op.f("ix_activity_systems_org_id"), "activity_systems", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_activity_systems_system_id"), "activity_systems", ["system_id"], unique=False
    )
    op.create_table(
        "activity_versions",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["processing_activities.id"],
            name=op.f("fk_activity_versions_activity_id_processing_activities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by"],
            ["users.id"],
            name=op.f("fk_activity_versions_approved_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_activity_versions_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_activity_versions_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activity_versions")),
        sa.UniqueConstraint(
            "activity_id", "version", name=op.f("uq_activity_versions_activity_id_version")
        ),
    )
    op.create_index(
        op.f("ix_activity_versions_activity_id"), "activity_versions", ["activity_id"], unique=False
    )
    op.create_index(
        op.f("ix_activity_versions_org_id"), "activity_versions", ["org_id"], unique=False
    )
    op.create_table(
        "discovery_runs",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "CREATED",
                "EVIDENCE_ATTACHED",
                "DISCOVERING",
                "CLASSIFIED",
                "FUSED",
                "DRAFTED",
                "AWAITING_REVIEW",
                "APPROVED",
                "PUBLISHED",
                "FAILED",
                name="jobstate",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="DISCOVERING",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('CREATED', 'EVIDENCE_ATTACHED', 'DISCOVERING', 'CLASSIFIED', 'FUSED', 'DRAFTED', 'AWAITING_REVIEW', 'APPROVED', 'PUBLISHED', 'FAILED')",
            name=op.f("ck_discovery_runs_jobstate"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_discovery_runs_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_runs_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_discovery_runs_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
    )
    op.create_index(op.f("ix_discovery_runs_org_id"), "discovery_runs", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_discovery_runs_system_id"), "discovery_runs", ["system_id"], unique=False
    )
    op.create_table(
        "documents",
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column(
            "doc_type",
            sa.Enum(
                "policy",
                "vendor_agreement",
                "questionnaire",
                "guidance",
                name="documenttype",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source_uri", sa.Text(), nullable=True),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "doc_type IN ('policy', 'vendor_agreement', 'questionnaire', 'guidance')",
            name=op.f("ck_documents_documenttype"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_documents_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_documents_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_org_id"), "documents", ["org_id"], unique=False)
    op.create_index(op.f("ix_documents_system_id"), "documents", ["system_id"], unique=False)
    op.create_table(
        "dpias",
        sa.Column("activity_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "in_review",
                "approved",
                "rejected",
                name="dpiastatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column(
            "trigger_scores",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("criteria_met", sa.Integer(), server_default="0", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("necessity_proportionality", sa.Text(), nullable=True),
        sa.Column("residual_risk", sa.String(length=40), nullable=True),
        sa.Column("officer_opinion", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'in_review', 'approved', 'rejected')",
            name=op.f("ck_dpias_dpiastatus"),
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["processing_activities.id"],
            name=op.f("fk_dpias_activity_id_processing_activities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_dpias_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_dpias_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dpias")),
    )
    op.create_index(op.f("ix_dpias_activity_id"), "dpias", ["activity_id"], unique=False)
    op.create_index(op.f("ix_dpias_org_id"), "dpias", ["org_id"], unique=False)
    op.create_table(
        "evidence_items",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "har",
                "website",
                "javascript_bundle",
                "sqlite_snapshot",
                "questionnaire",
                "privacy_policy",
                "vendor_agreement",
                name="evidencekind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "extractor",
            sa.Enum(
                "rea",
                "fallback",
                "document",
                name="extractor",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("uploaded_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "extractor IN ('rea', 'fallback', 'document')", name=op.f("ck_evidence_items_extractor")
        ),
        sa.CheckConstraint(
            "kind IN ('har', 'website', 'javascript_bundle', 'sqlite_snapshot', 'questionnaire', 'privacy_policy', 'vendor_agreement')",
            name=op.f("ck_evidence_items_evidencekind"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_evidence_items_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_evidence_items_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_evidence_items_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evidence_items")),
    )
    op.create_index(op.f("ix_evidence_items_org_id"), "evidence_items", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_evidence_items_system_id"), "evidence_items", ["system_id"], unique=False
    )
    op.create_table(
        "findings",
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("activity_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.String(length=80), nullable=False),
        sa.Column(
            "severity",
            sa.Enum(
                "low",
                "medium",
                "high",
                "critical",
                name="findingseverity",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "evidence_refs",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("suggested_fix", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "acknowledged",
                "resolved",
                "dismissed",
                name="findingstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=200), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high', 'critical')",
            name=op.f("ck_findings_findingseverity"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'acknowledged', 'resolved', 'dismissed')",
            name=op.f("ck_findings_findingstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["activity_id"],
            ["processing_activities.id"],
            name=op.f("fk_findings_activity_id_processing_activities"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_findings_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_findings_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_findings")),
        sa.UniqueConstraint("org_id", "dedupe_key", name=op.f("uq_findings_org_id_dedupe_key")),
    )
    op.create_index(op.f("ix_findings_activity_id"), "findings", ["activity_id"], unique=False)
    op.create_index(op.f("ix_findings_org_id"), "findings", ["org_id"], unique=False)
    op.create_index(
        "ix_findings_org_id_status_severity",
        "findings",
        ["org_id", "status", "severity"],
        unique=False,
    )
    op.create_index(op.f("ix_findings_system_id"), "findings", ["system_id"], unique=False)
    op.create_table(
        "invoices",
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.Column("number", sa.String(length=40), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "paid",
                "open",
                "overdue",
                "void",
                name="invoicestatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("total_cents", sa.BigInteger(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('paid', 'open', 'overdue', 'void')", name=op.f("ck_invoices_invoicestatus")
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_invoices_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"],
            ["subscriptions.id"],
            name=op.f("fk_invoices_subscription_id_subscriptions"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("org_id", "number", name=op.f("uq_invoices_org_id_number")),
    )
    op.create_index(op.f("ix_invoices_org_id"), "invoices", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_invoices_subscription_id"), "invoices", ["subscription_id"], unique=False
    )
    op.create_table(
        "request_responses",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("cover_note", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "approved",
                "sent",
                name="responsestatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'sent')",
            name=op.f("ck_request_responses_responsestatus"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_request_responses_created_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_request_responses_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["access_requests.id"],
            name=op.f("fk_request_responses_request_id_access_requests"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_responses")),
        sa.UniqueConstraint(
            "request_id", "version", name=op.f("uq_request_responses_request_id_version")
        ),
    )
    op.create_index(
        op.f("ix_request_responses_org_id"), "request_responses", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_request_responses_request_id"), "request_responses", ["request_id"], unique=False
    )
    op.create_table(
        "request_results",
        sa.Column("request_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("table_name", sa.String(length=200), nullable=False),
        sa.Column("column_name", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=False),
        sa.Column(
            "disclosure_approved", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_request_results_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["access_requests.id"],
            name=op.f("fk_request_results_request_id_access_requests"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_request_results_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_request_results")),
    )
    op.create_index(op.f("ix_request_results_org_id"), "request_results", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_request_results_request_id"), "request_results", ["request_id"], unique=False
    )
    op.create_table(
        "usage_events",
        sa.Column(
            "kind",
            sa.Enum(
                "active_systems",
                "requests_processed",
                "assessments_generated",
                "tokens_used",
                name="usagekind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("quantity", sa.BigInteger(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("is_simulated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('active_systems', 'requests_processed', 'assessments_generated', 'tokens_used')",
            name=op.f("ck_usage_events_usagekind"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_usage_events_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_usage_events_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_events")),
    )
    op.create_index(op.f("ix_usage_events_org_id"), "usage_events", ["org_id"], unique=False)
    op.create_index(
        "ix_usage_events_org_id_kind_occurred_at",
        "usage_events",
        ["org_id", "kind", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "discovery_evidence",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("evidence_item_id", sa.Uuid(), nullable=True),
        sa.Column(
            "extractor",
            sa.Enum(
                "rea",
                "fallback",
                "document",
                name="extractor",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("command", sa.Text(), nullable=True),
        sa.Column("rea_version", sa.String(length=40), nullable=True),
        sa.Column("raw_output", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="ok", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "extractor IN ('rea', 'fallback', 'document')",
            name=op.f("ck_discovery_evidence_extractor"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_item_id"],
            ["evidence_items.id"],
            name=op.f("fk_discovery_evidence_evidence_item_id_evidence_items"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_evidence_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["discovery_runs.id"],
            name=op.f("fk_discovery_evidence_run_id_discovery_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_evidence")),
    )
    op.create_index(
        op.f("ix_discovery_evidence_evidence_item_id"),
        "discovery_evidence",
        ["evidence_item_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_discovery_evidence_org_id"), "discovery_evidence", ["org_id"], unique=False
    )
    op.create_index(
        op.f("ix_discovery_evidence_run_id"), "discovery_evidence", ["run_id"], unique=False
    )
    op.create_table(
        "document_chunks",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=300), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('english', text)", persisted=True),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_chunks_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_document_chunks_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_document_chunks_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_chunks")),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"), "document_chunks", ["document_id"], unique=False
    )
    op.create_index(
        "ix_document_chunks_embedding_hnsw",
        "document_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(op.f("ix_document_chunks_org_id"), "document_chunks", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_document_chunks_system_id"), "document_chunks", ["system_id"], unique=False
    )
    op.create_index(
        "ix_document_chunks_tsv", "document_chunks", ["tsv"], unique=False, postgresql_using="gin"
    )
    op.create_table(
        "dpia_risks",
        sa.Column("dpia_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("likelihood", sa.Integer(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("mitigation", sa.Text(), nullable=True),
        sa.Column("residual_likelihood", sa.Integer(), nullable=True),
        sa.Column("residual_severity", sa.Integer(), nullable=True),
        sa.Column("citation", sa.String(length=200), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "likelihood BETWEEN 1 AND 5", name=op.f("ck_dpia_risks_likelihood_range")
        ),
        sa.CheckConstraint(
            "residual_likelihood IS NULL OR residual_likelihood BETWEEN 1 AND 5",
            name=op.f("ck_dpia_risks_residual_likelihood_range"),
        ),
        sa.CheckConstraint(
            "residual_severity IS NULL OR residual_severity BETWEEN 1 AND 5",
            name=op.f("ck_dpia_risks_residual_severity_range"),
        ),
        sa.CheckConstraint("severity BETWEEN 1 AND 5", name=op.f("ck_dpia_risks_severity_range")),
        sa.ForeignKeyConstraint(
            ["dpia_id"], ["dpias.id"], name=op.f("fk_dpia_risks_dpia_id_dpias"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_dpia_risks_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dpia_risks")),
    )
    op.create_index(op.f("ix_dpia_risks_dpia_id"), "dpia_risks", ["dpia_id"], unique=False)
    op.create_index(op.f("ix_dpia_risks_org_id"), "dpia_risks", ["org_id"], unique=False)
    op.create_table(
        "invoice_lines",
        sa.Column("invoice_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "base",
                "extra_systems",
                "extra_requests",
                name="invoicelinekind",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_cents", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('base', 'extra_systems', 'extra_requests')",
            name=op.f("ck_invoice_lines_invoicelinekind"),
        ),
        sa.CheckConstraint(
            "amount_cents = quantity * unit_cents", name=op.f("ck_invoice_lines_amount_matches")
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_lines_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_invoice_lines_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_lines")),
    )
    op.create_index(
        op.f("ix_invoice_lines_invoice_id"), "invoice_lines", ["invoice_id"], unique=False
    )
    op.create_index(op.f("ix_invoice_lines_org_id"), "invoice_lines", ["org_id"], unique=False)
    op.create_table(
        "llm_calls",
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("task", sa.String(length=80), nullable=False),
        sa.Column("tokens_in", sa.Integer(), server_default="0", nullable=False),
        sa.Column("tokens_out", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cached_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "ok",
                "error",
                "rate_limited",
                "schema_failure",
                "budget_blocked",
                name="llmcallstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("cache_hit", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("dpia_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ok', 'error', 'rate_limited', 'schema_failure', 'budget_blocked')",
            name=op.f("ck_llm_calls_llmcallstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["dpia_id"], ["dpias.id"], name=op.f("fk_llm_calls_dpia_id_dpias"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_llm_calls_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_llm_calls_system_id_systems"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_calls")),
    )
    op.create_index(op.f("ix_llm_calls_org_id"), "llm_calls", ["org_id"], unique=False)
    op.create_index(
        "ix_llm_calls_org_id_created_at", "llm_calls", ["org_id", "created_at"], unique=False
    )
    op.create_index(op.f("ix_llm_calls_system_id"), "llm_calls", ["system_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("assignee_user_id", sa.Uuid(), nullable=True),
        sa.Column("system_id", sa.Uuid(), nullable=True),
        sa.Column("finding_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "open",
                "in_progress",
                "done",
                "cancelled",
                name="taskstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="open",
            nullable=False,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('open', 'in_progress', 'done', 'cancelled')",
            name=op.f("ck_tasks_taskstatus"),
        ),
        sa.ForeignKeyConstraint(
            ["assignee_user_id"],
            ["users.id"],
            name=op.f("fk_tasks_assignee_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["finding_id"],
            ["findings.id"],
            name=op.f("fk_tasks_finding_id_findings"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_tasks_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_tasks_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_assignee_user_id"), "tasks", ["assignee_user_id"], unique=False)
    op.create_index(op.f("ix_tasks_org_id"), "tasks", ["org_id"], unique=False)
    op.create_index(op.f("ix_tasks_system_id"), "tasks", ["system_id"], unique=False)
    op.create_table(
        "data_elements",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("path", sa.Text(), nullable=True),
        sa.Column("data_type", sa.String(length=80), nullable=True),
        sa.Column("pattern_class", sa.String(length=80), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column(
            "special_category", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("special_category_label", sa.String(length=120), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column(
            "review_status",
            sa.Enum(
                "pending",
                "accepted",
                "overridden",
                name="reviewstatus",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("source_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'overridden')",
            name=op.f("ck_data_elements_reviewstatus"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1",
            name=op.f("ck_data_elements_confidence_range"),
        ),
        sa.CheckConstraint(
            "evidence_id IS NOT NULL OR source_chunk_id IS NOT NULL",
            name=op.f("ck_data_elements_has_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["discovery_evidence.id"],
            name=op.f("fk_data_elements_evidence_id_discovery_evidence"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_data_elements_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_data_elements_source_chunk_id_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_data_elements_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_elements")),
    )
    op.create_index(
        "ix_data_elements_embedding_hnsw",
        "data_elements",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_data_elements_evidence_id"), "data_elements", ["evidence_id"], unique=False
    )
    op.create_index(op.f("ix_data_elements_org_id"), "data_elements", ["org_id"], unique=False)
    op.create_index(
        op.f("ix_data_elements_system_id"), "data_elements", ["system_id"], unique=False
    )
    op.create_table(
        "recipients",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("vendor", sa.String(length=200), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "controller",
                "processor",
                "joint_controller",
                "unknown",
                name="recipientrole",
                native_enum=False,
                create_constraint=False,
                length=32,
            ),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("country", sa.String(length=80), nullable=True),
        sa.Column("purpose", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column(
            "agreement_on_file", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("safeguard", sa.String(length=200), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=True),
        sa.Column("source_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('controller', 'processor', 'joint_controller', 'unknown')",
            name=op.f("ck_recipients_recipientrole"),
        ),
        sa.CheckConstraint(
            "evidence_id IS NOT NULL OR source_chunk_id IS NOT NULL",
            name=op.f("ck_recipients_has_provenance"),
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["discovery_evidence.id"],
            name=op.f("fk_recipients_evidence_id_discovery_evidence"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_recipients_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_chunk_id"],
            ["document_chunks.id"],
            name=op.f("fk_recipients_source_chunk_id_document_chunks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_recipients_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recipients")),
    )
    op.create_index(op.f("ix_recipients_evidence_id"), "recipients", ["evidence_id"], unique=False)
    op.create_index(op.f("ix_recipients_org_id"), "recipients", ["org_id"], unique=False)
    op.create_index(op.f("ix_recipients_system_id"), "recipients", ["system_id"], unique=False)
    op.create_table(
        "technologies",
        sa.Column("system_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=True),
        sa.Column("version", sa.String(length=80), nullable=True),
        sa.Column("evidence_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "org_id",
            sa.Uuid(),
            server_default=sa.text("nullif(current_setting('app.org_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["discovery_evidence.id"],
            name=op.f("fk_technologies_evidence_id_discovery_evidence"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["org_id"],
            ["organizations.id"],
            name=op.f("fk_technologies_org_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["system_id"],
            ["systems.id"],
            name=op.f("fk_technologies_system_id_systems"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_technologies")),
    )
    op.create_index(
        op.f("ix_technologies_evidence_id"), "technologies", ["evidence_id"], unique=False
    )
    op.create_index(op.f("ix_technologies_org_id"), "technologies", ["org_id"], unique=False)
    op.create_index(op.f("ix_technologies_system_id"), "technologies", ["system_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_technologies_system_id"), table_name="technologies")
    op.drop_index(op.f("ix_technologies_org_id"), table_name="technologies")
    op.drop_index(op.f("ix_technologies_evidence_id"), table_name="technologies")
    op.drop_table("technologies")
    op.drop_index(op.f("ix_recipients_system_id"), table_name="recipients")
    op.drop_index(op.f("ix_recipients_org_id"), table_name="recipients")
    op.drop_index(op.f("ix_recipients_evidence_id"), table_name="recipients")
    op.drop_table("recipients")
    op.drop_index(op.f("ix_data_elements_system_id"), table_name="data_elements")
    op.drop_index(op.f("ix_data_elements_org_id"), table_name="data_elements")
    op.drop_index(op.f("ix_data_elements_evidence_id"), table_name="data_elements")
    op.drop_index(
        "ix_data_elements_embedding_hnsw",
        table_name="data_elements",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_table("data_elements")
    op.drop_index(op.f("ix_tasks_system_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_org_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_user_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_llm_calls_system_id"), table_name="llm_calls")
    op.drop_index("ix_llm_calls_org_id_created_at", table_name="llm_calls")
    op.drop_index(op.f("ix_llm_calls_org_id"), table_name="llm_calls")
    op.drop_table("llm_calls")
    op.drop_index(op.f("ix_invoice_lines_org_id"), table_name="invoice_lines")
    op.drop_index(op.f("ix_invoice_lines_invoice_id"), table_name="invoice_lines")
    op.drop_table("invoice_lines")
    op.drop_index(op.f("ix_dpia_risks_org_id"), table_name="dpia_risks")
    op.drop_index(op.f("ix_dpia_risks_dpia_id"), table_name="dpia_risks")
    op.drop_table("dpia_risks")
    op.drop_index("ix_document_chunks_tsv", table_name="document_chunks", postgresql_using="gin")
    op.drop_index(op.f("ix_document_chunks_system_id"), table_name="document_chunks")
    op.drop_index(op.f("ix_document_chunks_org_id"), table_name="document_chunks")
    op.drop_index(
        "ix_document_chunks_embedding_hnsw",
        table_name="document_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_index(op.f("ix_discovery_evidence_run_id"), table_name="discovery_evidence")
    op.drop_index(op.f("ix_discovery_evidence_org_id"), table_name="discovery_evidence")
    op.drop_index(op.f("ix_discovery_evidence_evidence_item_id"), table_name="discovery_evidence")
    op.drop_table("discovery_evidence")
    op.drop_index("ix_usage_events_org_id_kind_occurred_at", table_name="usage_events")
    op.drop_index(op.f("ix_usage_events_org_id"), table_name="usage_events")
    op.drop_table("usage_events")
    op.drop_index(op.f("ix_request_results_request_id"), table_name="request_results")
    op.drop_index(op.f("ix_request_results_org_id"), table_name="request_results")
    op.drop_table("request_results")
    op.drop_index(op.f("ix_request_responses_request_id"), table_name="request_responses")
    op.drop_index(op.f("ix_request_responses_org_id"), table_name="request_responses")
    op.drop_table("request_responses")
    op.drop_index(op.f("ix_invoices_subscription_id"), table_name="invoices")
    op.drop_index(op.f("ix_invoices_org_id"), table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(op.f("ix_findings_system_id"), table_name="findings")
    op.drop_index("ix_findings_org_id_status_severity", table_name="findings")
    op.drop_index(op.f("ix_findings_org_id"), table_name="findings")
    op.drop_index(op.f("ix_findings_activity_id"), table_name="findings")
    op.drop_table("findings")
    op.drop_index(op.f("ix_evidence_items_system_id"), table_name="evidence_items")
    op.drop_index(op.f("ix_evidence_items_org_id"), table_name="evidence_items")
    op.drop_table("evidence_items")
    op.drop_index(op.f("ix_dpias_org_id"), table_name="dpias")
    op.drop_index(op.f("ix_dpias_activity_id"), table_name="dpias")
    op.drop_table("dpias")
    op.drop_index(op.f("ix_documents_system_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_org_id"), table_name="documents")
    op.drop_table("documents")
    op.drop_index(op.f("ix_discovery_runs_system_id"), table_name="discovery_runs")
    op.drop_index(op.f("ix_discovery_runs_org_id"), table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_index(op.f("ix_activity_versions_org_id"), table_name="activity_versions")
    op.drop_index(op.f("ix_activity_versions_activity_id"), table_name="activity_versions")
    op.drop_table("activity_versions")
    op.drop_index(op.f("ix_activity_systems_system_id"), table_name="activity_systems")
    op.drop_index(op.f("ix_activity_systems_org_id"), table_name="activity_systems")
    op.drop_table("activity_systems")
    op.drop_index(op.f("ix_systems_owner_user_id"), table_name="systems")
    op.drop_index(op.f("ix_systems_org_id"), table_name="systems")
    op.drop_table("systems")
    op.drop_index(op.f("ix_subscriptions_plan_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_org_id"), table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index(op.f("ix_refresh_tokens_user_id"), table_name="refresh_tokens")
    op.drop_index(op.f("ix_refresh_tokens_family_id"), table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_index(
        op.f("ix_processing_activities_owner_user_id"), table_name="processing_activities"
    )
    op.drop_index(op.f("ix_processing_activities_org_id"), table_name="processing_activities")
    op.drop_table("processing_activities")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_org_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_llm_cache_org_id"), table_name="llm_cache")
    op.drop_table("llm_cache")
    op.drop_index(op.f("ix_leads_org_id"), table_name="leads")
    op.drop_table("leads")
    op.drop_index(op.f("ix_compliance_daily_metrics_org_id"), table_name="compliance_daily_metrics")
    op.drop_table("compliance_daily_metrics")
    op.drop_index(op.f("ix_comments_org_id"), table_name="comments")
    op.drop_index("ix_comments_entity", table_name="comments")
    op.drop_table("comments")
    op.drop_index("ix_audit_log_org_id_created_at", table_name="audit_log")
    op.drop_index(op.f("ix_audit_log_org_id"), table_name="audit_log")
    op.drop_index("ix_audit_log_action", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index(op.f("ix_approvals_org_id"), table_name="approvals")
    op.drop_index("ix_approvals_entity", table_name="approvals")
    op.drop_table("approvals")
    op.drop_index(op.f("ix_access_requests_subject_hash"), table_name="access_requests")
    op.drop_index(op.f("ix_access_requests_org_id"), table_name="access_requests")
    op.drop_table("access_requests")
    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
    op.drop_index(
        "ix_regulation_chunks_tsv", table_name="regulation_chunks", postgresql_using="gin"
    )
    op.drop_index(
        "ix_regulation_chunks_embedding_hnsw",
        table_name="regulation_chunks",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_regulation_chunks_article"), table_name="regulation_chunks")
    op.drop_table("regulation_chunks")
    op.drop_table("plans")
    op.drop_table("organizations")
    op.drop_table("daily_metrics")
    op.execute("DROP EXTENSION IF EXISTS vector")
