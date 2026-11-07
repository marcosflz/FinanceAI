"""v3_005_user_profile — nombre visible editable en el perfil.

Añade ``users.name`` para que el administrador pueda editar su nombre desde
Ajustes sin depender del local-part del email. Es nullable para no romper
usuarios existentes; la API mantiene el fallback al local-part.

Revision ID: v3_005_user_profile
Revises: v3_004_account_balance_date
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision: str = "v3_005_user_profile"
down_revision: str | None = "v3_004_account_balance_date"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns(bind, table: str) -> set[str]:
    inspector = inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "name" not in _columns(bind, "users"):
        op.add_column("users", sa.Column("name", sa.String(length=120), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "name" in _columns(bind, "users"):
        with op.batch_alter_table("users") as batch:
            batch.drop_column("name")
