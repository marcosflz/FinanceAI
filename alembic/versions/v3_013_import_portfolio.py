"""v3_013 — importación automática, multidivisa y snapshots de cartera.

Revision ID: v3_013_import_portfolio
Revises: v3_012_reclass_inv_cashback
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_013_import_portfolio"
down_revision: str | None = "v3_012_reclass_inv_cashback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    for column in (
        sa.Column("amount_eur", sa.Numeric(18, 4), nullable=True),
        sa.Column("fx_rate_to_eur", sa.Numeric(24, 12), nullable=True),
        sa.Column("fx_source", sa.String(length=20), nullable=True),
        sa.Column("fx_date", sa.Date(), nullable=True),
    ):
        if column.name not in _columns(bind, "financial_movements"):
            op.add_column("financial_movements", column)

    for column in (
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("source_file_id", sa.Integer(), nullable=True),
    ):
        if column.name not in _columns(bind, "asset_transactions"):
            op.add_column("asset_transactions", column)

    if "account_currency_balances" not in tables:
        op.create_table(
            "account_currency_balances",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False),
            sa.Column("balance_inicial", sa.Numeric(18, 4), nullable=True),
            sa.Column("balance_inicial_eur", sa.Numeric(18, 4), nullable=True),
            sa.Column("balance_inicial_fecha", sa.Date(), nullable=True),
            sa.Column("last_reconciled_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "account_id", "currency", name="uq_account_currency_balance"
            ),
        )
        op.create_index(
            "ix_acb_account_currency",
            "account_currency_balances",
            ["account_id", "currency"],
        )

    # La tabla de snapshots debe admitir una fila por divisa y fecha. SQLite no
    # permite eliminar la constraint antigua sin recrear la tabla.
    columns = _columns(bind, "account_balance_snapshots")
    if "currency" not in columns:
        with op.batch_alter_table("account_balance_snapshots") as batch:
            batch.add_column(
                sa.Column("source_file_id", sa.Integer(), nullable=True)
            )
            batch.add_column(
                sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR")
            )
            batch.drop_constraint(
                "uq_balance_snapshot_account_fecha", type_="unique"
            )
            batch.create_unique_constraint(
                "uq_balance_snapshot_account_currency_fecha",
                ["account_id", "currency", "fecha"],
            )
            batch.create_foreign_key(
                "fk_abs_source_file",
                "source_files",
                ["source_file_id"],
                ["id"],
                ondelete="SET NULL",
            )

    if "portfolio_snapshots" not in tables:
        op.create_table(
            "portfolio_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("source_file_id", sa.Integer(), nullable=True),
            sa.Column("snapshot_date", sa.Date(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
            sa.Column("custody_ref", sa.String(length=80), nullable=True),
            sa.Column("cash_declared", sa.Numeric(18, 4), nullable=True),
            sa.Column("total_declared", sa.Numeric(18, 4), nullable=True),
            sa.Column("securities_value", sa.Numeric(18, 4), nullable=True),
            sa.Column("crypto_value", sa.Numeric(18, 4), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "account_id", "snapshot_date", "custody_ref",
                name="uq_portfolio_snapshot_account_date_custody",
            ),
        )
        op.create_index(
            "ix_portfolio_snapshot_account_date",
            "portfolio_snapshots",
            ["account_id", "snapshot_date"],
        )

    if "portfolio_snapshot_positions" not in tables:
        op.create_table(
            "portfolio_snapshot_positions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("snapshot_id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("quantity", sa.Numeric(24, 10), nullable=False),
            sa.Column("price", sa.Numeric(18, 6), nullable=False),
            sa.Column("price_date", sa.Date(), nullable=True),
            sa.Column("value", sa.Numeric(18, 4), nullable=False),
            sa.Column("cost_total", sa.Numeric(18, 4), nullable=True),
            sa.Column("pnl_declared", sa.Numeric(18, 4), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default="EUR"),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["snapshot_id"], ["portfolio_snapshots.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "snapshot_id", "asset_id", name="uq_portfolio_snapshot_asset"
            ),
        )
        op.create_index(
            "ix_psp_snapshot_asset",
            "portfolio_snapshot_positions",
            ["snapshot_id", "asset_id"],
        )

    if "asset_opening_positions" not in tables:
        op.create_table(
            "asset_opening_positions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("asset_id", sa.Integer(), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("quantity", sa.Numeric(24, 10), nullable=False),
            sa.Column("cost_total", sa.Numeric(18, 4), nullable=True),
            sa.Column("cost_status", sa.String(length=20), nullable=False, server_default="unknown"),
            sa.Column("source", sa.String(length=40), nullable=False, server_default="derived"),
            sa.Column("source_file_id", sa.Integer(), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["source_file_id"], ["source_files.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "account_id", "asset_id", "as_of_date",
                name="uq_asset_opening_account_asset_date",
            ),
        )
        op.create_index(
            "ix_aop_account_asset_date",
            "asset_opening_positions",
            ["account_id", "asset_id", "as_of_date"],
        )

    # Backfill seguro: los movimientos existentes son EUR y el apunte ya es el
    # valor en euros. No se recalculan comisiones históricas en esta migración.
    op.execute(
        "UPDATE financial_movements "
        "SET amount_eur = amount, fx_rate_to_eur = 1, fx_source = 'statement', "
        "fx_date = value_date "
        "WHERE currency = 'EUR' AND amount_eur IS NULL"
    )
    op.execute(
        "INSERT INTO account_currency_balances "
        "(account_id, currency, balance_inicial, balance_inicial_eur, "
        "balance_inicial_fecha, created_at, updated_at) "
        "SELECT id, COALESCE(moneda, 'EUR'), balance_inicial, "
        "CASE WHEN COALESCE(moneda, 'EUR') = 'EUR' THEN balance_inicial ELSE NULL END, "
        "balance_inicial_fecha, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP FROM accounts "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM account_currency_balances b WHERE b.account_id = accounts.id"
        ")"
    )


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for table in (
        "asset_opening_positions",
        "portfolio_snapshot_positions",
        "portfolio_snapshots",
    ):
        if table in tables:
            op.drop_table(table)
    if "account_currency_balances" in tables:
        op.drop_index("ix_acb_account_currency", table_name="account_currency_balances")
        op.drop_table("account_currency_balances")

    if "currency" in _columns(bind, "account_balance_snapshots"):
        with op.batch_alter_table("account_balance_snapshots") as batch:
            batch.drop_constraint(
                "uq_balance_snapshot_account_currency_fecha", type_="unique"
            )
            batch.drop_constraint("fk_abs_source_file", type_="foreignkey")
            batch.drop_column("currency")
            batch.drop_column("source_file_id")
            batch.create_unique_constraint(
                "uq_balance_snapshot_account_fecha", ["account_id", "fecha"]
            )

    for table, column in (
        ("asset_transactions", "source_file_id"),
        ("asset_transactions", "account_id"),
        ("financial_movements", "fx_date"),
        ("financial_movements", "fx_source"),
        ("financial_movements", "fx_rate_to_eur"),
        ("financial_movements", "amount_eur"),
    ):
        if column in _columns(bind, table):
            op.drop_column(table, column)
