"""v2 003 add auto_aprobar to classification_rules

Revision ID: 3e7a1d9f8c5c
Revises: d787632656f2
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = "3e7a1d9f8c5c"
down_revision: Union[str, None] = "d787632656f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("classification_rules")}
    if "auto_aprobar" not in columns:
        op.add_column(
            "classification_rules",
            sa.Column(
                "auto_aprobar",
                sa.Boolean(),
                server_default=sa.false(),
                nullable=False,
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in inspect(bind).get_columns("classification_rules")}
    if "auto_aprobar" in columns:
        op.drop_column("classification_rules", "auto_aprobar")
