"""knowledge base: stable regulation chunk keys, document to evidence link, searchable headings

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21 13:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "to_tsvector('english', text)"
DOC_NEW = "to_tsvector('english', coalesce(heading, '') || ' ' || text)"
REG_NEW = "to_tsvector('english', coalesce(title, '') || ' ' || text)"


def _replace_tsv(table: str, index: str, expression: str) -> None:
    op.drop_index(index, table_name=table, postgresql_using="gin")
    op.drop_column(table, "tsv")
    op.execute(
        f"ALTER TABLE {table} ADD COLUMN tsv tsvector GENERATED ALWAYS AS ({expression}) STORED NOT NULL"
    )
    op.create_index(index, table, ["tsv"], unique=False, postgresql_using="gin")


def upgrade() -> None:
    op.add_column("regulation_chunks", sa.Column("chunk_key", sa.String(length=80), nullable=True))
    op.execute("UPDATE regulation_chunks SET chunk_key = id::text WHERE chunk_key IS NULL")
    op.alter_column("regulation_chunks", "chunk_key", nullable=False)
    op.create_unique_constraint(
        op.f("uq_regulation_chunks_chunk_key"), "regulation_chunks", ["chunk_key"]
    )

    op.add_column("documents", sa.Column("evidence_item_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_documents_evidence_item_id_evidence_items"),
        "documents",
        "evidence_items",
        ["evidence_item_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_documents_evidence_item_id"), "documents", ["evidence_item_id"], unique=False
    )

    _replace_tsv("document_chunks", "ix_document_chunks_tsv", DOC_NEW)
    _replace_tsv("regulation_chunks", "ix_regulation_chunks_tsv", REG_NEW)


def downgrade() -> None:
    _replace_tsv("regulation_chunks", "ix_regulation_chunks_tsv", OLD)
    _replace_tsv("document_chunks", "ix_document_chunks_tsv", OLD)
    op.drop_index(op.f("ix_documents_evidence_item_id"), table_name="documents")
    op.drop_constraint(
        op.f("fk_documents_evidence_item_id_evidence_items"), "documents", type_="foreignkey"
    )
    op.drop_column("documents", "evidence_item_id")
    op.drop_constraint(op.f("uq_regulation_chunks_chunk_key"), "regulation_chunks", type_="unique")
    op.drop_column("regulation_chunks", "chunk_key")
