"""v3_001_agentic_meta — metadatos de extracción agéntica.

Revision ID: v3_001_agentic_meta
Revises: v3_000_f0
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_001_agentic_meta"
down_revision: str | None = "v3_000_f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "extraction_meta" not in _columns(bind, "source_files"):
        op.add_column(
            "source_files",
            sa.Column("extraction_meta", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "extraction_meta" in _columns(bind, "source_files"):
        op.drop_column("source_files", "extraction_meta")
