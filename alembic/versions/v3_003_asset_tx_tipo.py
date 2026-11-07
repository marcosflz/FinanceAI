"""v3_003_asset_tx_tipo — amplía asset_transactions.tipo.

`dividendo_accion` ocupa 16 caracteres y la columna era VARCHAR(15); esto hacía
fallar imports con dividendos en PostgreSQL y dejaba el import en `failed`.

Revision ID: v3_003_asset_tx_tipo
Revises: v3_002_import_queue
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_003_asset_tx_tipo"
down_revision: str | None = "v3_002_import_queue"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> dict[str, dict]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return {}
    return {column["name"]: column for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    column = _columns(bind, "asset_transactions").get("tipo")
    if column is None:
        return
    current_length = getattr(column.get("type"), "length", None)
    if current_length is not None and current_length >= 30:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("asset_transactions") as batch:
            batch.alter_column(
                "tipo",
                existing_type=sa.String(length=current_length or 15),
                type_=sa.String(length=30),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "asset_transactions",
            "tipo",
            existing_type=sa.String(length=current_length or 15),
            type_=sa.String(length=30),
            existing_nullable=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    column = _columns(bind, "asset_transactions").get("tipo")
    if column is None:
        return
    current_length = getattr(column.get("type"), "length", None)
    if current_length is not None and current_length <= 15:
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("asset_transactions") as batch:
            batch.alter_column(
                "tipo",
                existing_type=sa.String(length=current_length or 30),
                type_=sa.String(length=15),
                existing_nullable=False,
            )
    else:
        op.alter_column(
            "asset_transactions",
            "tipo",
            existing_type=sa.String(length=current_length or 30),
            type_=sa.String(length=15),
            existing_nullable=False,
        )
