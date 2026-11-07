"""v3_004_account_balance_date — fecha del saldo inicial de cuenta.

Permite fijar «saldo X a fecha Y» y calcular el saldo solo con movimientos
desde esa fecha.

Revision ID: v3_004_account_balance_date
Revises: v3_003_asset_tx_tipo
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_004_account_balance_date"
down_revision: str | None = "v3_003_asset_tx_tipo"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "balance_inicial_fecha" not in _columns(bind, "accounts"):
        op.add_column(
            "accounts",
            sa.Column("balance_inicial_fecha", sa.Date(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "balance_inicial_fecha" in _columns(bind, "accounts"):
        op.drop_column("accounts", "balance_inicial_fecha")
