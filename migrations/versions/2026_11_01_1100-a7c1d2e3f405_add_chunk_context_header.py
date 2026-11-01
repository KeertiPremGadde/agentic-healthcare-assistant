"""add chunk context header

Revision ID: a7c1d2e3f405
Revises: 0035bd336cac
Create Date: 2026-11-01 11:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a7c1d2e3f405"
down_revision: str | Sequence[str] | None = "0035bd336cac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace_tsv(expression: str) -> None:
    # A generated column's expression cannot be altered: drop and re-add (index goes with it).
    op.drop_index("ix_kb_chunks_tsv", table_name="kb_chunks", postgresql_using="gin")
    op.drop_column("kb_chunks", "tsv")
    op.add_column(
        "kb_chunks",
        sa.Column(
            "tsv",
            postgresql.TSVECTOR(),
            sa.Computed(expression, persisted=True),
            nullable=False,
        ),
    )
    op.create_index("ix_kb_chunks_tsv", "kb_chunks", ["tsv"], unique=False, postgresql_using="gin")


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "kb_chunks",
        sa.Column("context_header", sa.Text(), server_default="", nullable=False),
    )
    _replace_tsv("to_tsvector('english', context_header || ' ' || content)")


def downgrade() -> None:
    """Downgrade schema."""
    _replace_tsv("to_tsvector('english', content)")
    op.drop_column("kb_chunks", "context_header")
