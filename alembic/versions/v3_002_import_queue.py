"""v3_002_import_queue — cola persistente de importaciones.

Revision ID: v3_002_import_queue
Revises: v3_001_agentic_meta
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_002_import_queue"
down_revision: str | None = "v3_001_agentic_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "source_files")
    for name, column in (
        ("queued_at", sa.Column("queued_at", sa.DateTime(), nullable=True)),
        ("started_at", sa.Column("started_at", sa.DateTime(), nullable=True)),
        ("finished_at", sa.Column("finished_at", sa.DateTime(), nullable=True)),
        ("attempts", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0")),
    ):
        if name not in existing:
            op.add_column("source_files", column)


def downgrade() -> None:
    bind = op.get_bind()
    existing = _columns(bind, "source_files")
    for name in ("attempts", "finished_at", "started_at", "queued_at"):
        if name in existing:
            op.drop_column("source_files", name)
