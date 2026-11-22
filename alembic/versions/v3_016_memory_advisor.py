"""v3_016 — memoria del asistente y recomendaciones del asesor de cartera.

Revision ID: v3_016_memory_advisor
Revises: v3_015_skills
Create Date: 2026-11-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v3_016_memory_advisor"
down_revision: str | None = "v3_015_skills"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    tables = _tables()
    if "agent_memories" not in tables:
        op.create_table(
            "agent_memories",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("key", sa.String(128), nullable=False, unique=True),
            sa.Column("value", sa.Text(), nullable=False),
            sa.Column("category", sa.String(20), nullable=False, server_default="fact"),
            sa.Column("source", sa.String(20), nullable=False, server_default="assistant"),
            sa.Column(
                "source_thread_id",
                sa.Integer(),
                sa.ForeignKey("chat_threads.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if "advisor_recommendations" not in tables:
        op.create_table(
            "advisor_recommendations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "thread_id",
                sa.Integer(),
                sa.ForeignKey("chat_threads.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("run_id", sa.Integer(), nullable=True),
            sa.Column(
                "asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("symbol", sa.String(30), nullable=False),
            sa.Column("name", sa.String(255), nullable=True),
            sa.Column("horizon", sa.String(10), nullable=False),
            sa.Column("action", sa.String(10), nullable=False),
            sa.Column("confidence", sa.String(10), nullable=False, server_default="media"),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("sources_json", sa.Text(), nullable=True),
            sa.Column("price", sa.Numeric(18, 6), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_advisor_recommendations_created_at", "advisor_recommendations", ["created_at"]
        )
        op.create_index(
            "ix_advisor_symbol_created", "advisor_recommendations", ["symbol", "created_at"]
        )


def downgrade() -> None:
    op.drop_index("ix_advisor_symbol_created", table_name="advisor_recommendations")
    op.drop_index("ix_advisor_recommendations_created_at", table_name="advisor_recommendations")
    op.drop_table("advisor_recommendations")
    op.drop_table("agent_memories")
