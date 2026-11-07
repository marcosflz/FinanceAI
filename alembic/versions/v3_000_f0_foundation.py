"""v3_000_f0_foundation — auth, conciliación y columnas de trazabilidad.

Revision ID: v3_000_f0
Revises: 3e7a1d9f8c5c
Create Date: 2026-10-31

Migración idempotente y compatible con SQLite/PostgreSQL. Todos los pasos
comprueban tablas/columnas/índices antes de actuar para poder aplicarse
sobre bases ya migradas por ``create_all`` o por scripts ad-hoc.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "v3_000_f0"
down_revision: Union[str, None] = "3e7a1d9f8c5c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    """Índices reales, incluidos los basados en expresiones.

    ``inspect.get_indexes`` omite índices de expresión en SQLite (por
    ejemplo ``uq_cm_pattern_mcc_broker``); consultamos el catálogo para que
    upgrade/downgrade sean idempotentes también en ese caso.
    """
    if table not in _tables(bind):
        return set()
    if bind.dialect.name == "sqlite":
        rows = bind.execute(
            sa.text(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=:table"
            ),
            {"table": table},
        )
        return {row[0] for row in rows}
    if bind.dialect.name == "postgresql":
        rows = bind.execute(
            sa.text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename=:table"
            ),
            {"table": table},
        )
        return {row[0] for row in rows}
    return {index["name"] for index in inspect(bind).get_indexes(table)}


def _add_column(bind, table: str, column: sa.Column) -> None:
    if table in _tables(bind) and column.name not in _columns(bind, table):
        op.add_column(table, column)


def _account_reference(bind, name: str) -> sa.Column:
    """FK solo donde ALTER ADD COLUMN la soporta (SQLite no lo permite)."""
    if bind.dialect.name == "sqlite":
        return sa.Column(name, sa.Integer(), nullable=True)
    return sa.Column(name, sa.Integer(), sa.ForeignKey("accounts.id"), nullable=True)


def _create_index(bind, name: str, table: str, columns: list, *, unique: bool = False) -> None:
    if table in _tables(bind) and name not in _indexes(bind, table):
        op.create_index(name, table, columns, unique=unique)


def _create_auth_tables(bind) -> None:
    tables = _tables(bind)

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="admin"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    if "sessions" not in tables:
        op.create_table(
            "sessions",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("ip", sa.String(length=45), nullable=True),
            sa.Column("user_agent", sa.String(length=500), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
        op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
        op.create_index("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"])
        op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])

    if "login_attempts" not in tables:
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("email", sa.String(length=255), nullable=True),
            sa.Column("ip", sa.String(length=45), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])
        op.create_index(
            "ix_login_attempts_email_created", "login_attempts", ["email", "created_at"]
        )
        op.create_index(
            "ix_login_attempts_ip_created", "login_attempts", ["ip", "created_at"]
        )

    if "account_balance_snapshots" not in tables:
        op.create_table(
            "account_balance_snapshots",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("account_id", sa.Integer(), nullable=False),
            sa.Column("fecha", sa.Date(), nullable=False),
            sa.Column("saldo_declarado", sa.Numeric(18, 4), nullable=True),
            sa.Column("saldo_calculado", sa.Numeric(18, 4), nullable=True),
            sa.Column("diferencia", sa.Numeric(18, 4), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "account_id", "fecha", name="uq_balance_snapshot_account_fecha"
            ),
        )
        op.create_index(
            "ix_balance_snapshot_account_fecha",
            "account_balance_snapshots",
            ["account_id", "fecha"],
        )


def _add_traceability_columns(bind) -> None:
    # source_files
    _add_column(bind, "source_files", sa.Column("mime_type", sa.String(length=100), nullable=True))
    _add_column(bind, "source_files", sa.Column("page_count", sa.Integer(), nullable=True))
    _add_column(bind, "source_files", _account_reference(bind, "account_id"))
    _add_column(bind, "source_files", sa.Column("balance_start", sa.Numeric(18, 4), nullable=True))
    _add_column(bind, "source_files", sa.Column("balance_end", sa.Numeric(18, 4), nullable=True))

    # raw_rows
    _add_column(bind, "raw_rows", sa.Column("page", sa.Integer(), nullable=True))
    _add_column(bind, "raw_rows", sa.Column("line_start", sa.Integer(), nullable=True))
    _add_column(bind, "raw_rows", sa.Column("line_end", sa.Integer(), nullable=True))
    _add_column(bind, "raw_rows", sa.Column("unit_type", sa.String(length=30), nullable=True))

    # normalized_events
    _add_column(
        bind, "normalized_events", _account_reference(bind, "source_account_id")
    )
    _add_column(bind, "normalized_events", sa.Column("dedup_key", sa.String(length=128), nullable=True))
    _add_column(
        bind,
        "normalized_events",
        sa.Column(
            "occurrence_index", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
    )
    _add_column(bind, "normalized_events", sa.Column("extraction_confidence", sa.Numeric(4, 3), nullable=True))
    _add_column(bind, "normalized_events", sa.Column("raw_text", sa.Text(), nullable=True))
    _create_index(bind, "ix_ne_dedup_key", "normalized_events", ["dedup_key"])

    # accounts
    _add_column(bind, "accounts", sa.Column("balance_inicial", sa.Numeric(18, 4), nullable=True))

    # classification_rules
    _add_column(bind, "classification_rules", sa.Column("nombre", sa.String(length=255), nullable=True))
    _add_column(bind, "classification_rules", sa.Column("descripcion", sa.Text(), nullable=True))
    _add_column(
        bind,
        "classification_rules",
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )
    _add_column(bind, "classification_rules", sa.Column("last_hit_at", sa.DateTime(), nullable=True))

    # classification_memory
    _add_column(bind, "classification_memory", sa.Column("embedding_model", sa.String(length=60), nullable=True))
    if "classification_memory" in _tables(bind):
        # La unicidad lógica incluye NULLs; deduplicamos antes por si acaso.
        bind.execute(
            sa.text(
                "DELETE FROM classification_memory WHERE id NOT IN ("
                "SELECT MIN(id) FROM classification_memory "
                "GROUP BY pattern_key, COALESCE(mcc_code, ''), COALESCE(broker_type, '')"
                ")"
            )
        )
        _create_index(
            bind,
            "uq_cm_pattern_mcc_broker",
            "classification_memory",
            [
                "pattern_key",
                sa.text("COALESCE(mcc_code, '')"),
                sa.text("COALESCE(broker_type, '')"),
            ],
            unique=True,
        )

    # dedup_candidates
    _add_column(bind, "dedup_candidates", sa.Column("resolved_by", sa.String(length=100), nullable=True))
    _add_column(bind, "dedup_candidates", sa.Column("resolution_note", sa.Text(), nullable=True))
    if "dedup_candidates" in _tables(bind):
        bind.execute(
            sa.text(
                "DELETE FROM dedup_candidates WHERE id NOT IN ("
                "SELECT MIN(id) FROM dedup_candidates GROUP BY movement_a, movement_b"
                ")"
            )
        )
        _create_index(
            bind,
            "uq_dedup_pair",
            "dedup_candidates",
            ["movement_a", "movement_b"],
            unique=True,
        )

    # asset_transactions
    _add_column(bind, "asset_transactions", sa.Column("lote_id", sa.String(length=64), nullable=True))
    _add_column(bind, "asset_transactions", sa.Column("tax", sa.Numeric(18, 4), nullable=True))
    _add_column(bind, "asset_transactions", sa.Column("fx_rate", sa.Numeric(18, 8), nullable=True))

    # financial_movements (índices compuestos)
    _create_index(
        bind, "ix_fm_estado_value_date", "financial_movements", ["estado", "value_date"]
    )
    _create_index(
        bind, "ix_fm_account_value_date", "financial_movements", ["account_id", "value_date"]
    )


def upgrade() -> None:
    bind = op.get_bind()
    _create_auth_tables(bind)
    _add_traceability_columns(bind)


def downgrade() -> None:
    bind = op.get_bind()

    for name, table in (
        ("ix_fm_account_value_date", "financial_movements"),
        ("ix_fm_estado_value_date", "financial_movements"),
        ("uq_dedup_pair", "dedup_candidates"),
        ("uq_cm_pattern_mcc_broker", "classification_memory"),
        ("ix_ne_dedup_key", "normalized_events"),
    ):
        if table in _tables(bind) and name in _indexes(bind, table):
            op.drop_index(name, table_name=table)

    for table, columns in (
        ("asset_transactions", ["fx_rate", "tax", "lote_id"]),
        ("dedup_candidates", ["resolution_note", "resolved_by"]),
        ("classification_memory", ["embedding_model"]),
        ("classification_rules", ["last_hit_at", "hit_count", "descripcion", "nombre"]),
        ("accounts", ["balance_inicial"]),
        ("normalized_events", ["raw_text", "extraction_confidence", "occurrence_index", "dedup_key", "source_account_id"]),
        ("raw_rows", ["unit_type", "line_end", "line_start", "page"]),
        ("source_files", ["balance_end", "balance_start", "account_id", "page_count", "mime_type"]),
    ):
        existing = _columns(bind, table)
        for column in columns:
            if column in existing:
                op.drop_column(table, column)

    for table in ("account_balance_snapshots", "login_attempts", "sessions", "users"):
        if table in _tables(bind):
            op.drop_table(table)
