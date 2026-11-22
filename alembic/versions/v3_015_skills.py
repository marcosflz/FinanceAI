"""v3_015 — skills del asistente (biblioteca, versiones y borradores del creador).

Revision ID: v3_015_skills
Revises: v3_014_agent
Create Date: 2026-11-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "v3_015_skills"
down_revision: str | None = "v3_014_agent"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade() -> None:
    if "skills" in _tables():  # BD creada ya con create_all
        return
    op.create_table(
        "skills",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("current_version_id", sa.Integer(), nullable=True),
        sa.Column("enabled_in_chat", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source", sa.String(20), nullable=False, server_default="creator"),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "skill_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("package_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("skill_id", "version", name="uq_skill_version"),
    )
    op.create_index("ix_skill_versions_skill_id", "skill_versions", ["skill_id"])
    op.create_table(
        "skill_drafts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "skill_id", sa.Integer(), sa.ForeignKey("skills.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "thread_id",
            sa.Integer(),
            sa.ForeignKey("chat_threads.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_version_id", sa.Integer(), nullable=True),
        sa.Column("files_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("bots") as batch:
        batch.add_column(sa.Column("skill_ids_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bots") as batch:
        batch.drop_column("skill_ids_json")
    op.drop_table("skill_drafts")
    op.drop_index("ix_skill_versions_skill_id", table_name="skill_versions")
    op.drop_table("skill_versions")
    op.drop_table("skills")
