"""taxonomy entries: embedded personal data taxonomy for the classifier

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-20 19:00:00
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "processledger_app"


def upgrade() -> None:
    op.create_table(
        "taxonomy_entries",
        sa.Column("category_id", sa.String(length=60), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "special_category", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("source_version", sa.String(length=32), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.vector.VECTOR(dim=384), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_taxonomy_entries")),
    )
    op.create_index(
        op.f("ix_taxonomy_entries_category_id"), "taxonomy_entries", ["category_id"], unique=False
    )
    op.create_index(
        "ix_taxonomy_entries_embedding_hnsw",
        "taxonomy_entries",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    # Shared reference data: read only for the application role, like regulation_chunks.
    op.execute(f"GRANT SELECT ON taxonomy_entries TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON taxonomy_entries FROM {APP_ROLE}")
    op.drop_index(
        "ix_taxonomy_entries_embedding_hnsw",
        table_name="taxonomy_entries",
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.drop_index(op.f("ix_taxonomy_entries_category_id"), table_name="taxonomy_entries")
    op.drop_table("taxonomy_entries")
