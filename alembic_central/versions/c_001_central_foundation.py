"""c_001: BD central (auth, enrutado a tenants, cola y concesiones de clave).

Idempotente: en ``TENANT_MODE=single`` la BD central es la misma que la de
datos y ``users``/``sessions``/``login_attempts`` ya existen por la cadena
``alembic/`` (v3_000). Aquí solo se añaden columnas y tablas que falten.

Revision ID: c_001_central_foundation
Revises:
Create Date: 2026-11-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c_001_central_foundation"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_USER_COLUMNS = [
    sa.Column("tenant_id", sa.String(32), nullable=True),
    sa.Column("kdf_salt", sa.String(64), nullable=True),
    sa.Column("kdf_params", sa.String(255), nullable=True),
    sa.Column("dek_wrapped_pw", sa.Text(), nullable=True),
    sa.Column("dek_wrapped_recovery", sa.Text(), nullable=True),
    sa.Column("recovery_salt", sa.String(64), nullable=True),
    sa.Column("keys_created_at", sa.DateTime(), nullable=True),
    sa.Column("automation_until", sa.DateTime(), nullable=True),
    sa.Column("invite_token_hash", sa.String(64), nullable=True),
    sa.Column("invite_expires_at", sa.DateTime(), nullable=True),
]


def _tables() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade() -> None:
    tables = _tables()

    if "users" not in tables:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), nullable=False),
            sa.Column("name", sa.String(120), nullable=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(20), nullable=False, server_default="admin"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            *[c.copy() for c in _USER_COLUMNS],
        )
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    else:
        existing = _columns("users")
        missing = [c.copy() for c in _USER_COLUMNS if c.name not in existing]
        if missing:
            with op.batch_alter_table("users") as batch:
                for column in missing:
                    batch.add_column(column)
    user_indexes = _indexes("users")
    if "ix_users_tenant_id" not in user_indexes:
        op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=True)
    if "ix_users_invite_token_hash" not in user_indexes:
        op.create_index(
            "ix_users_invite_token_hash", "users", ["invite_token_hash"], unique=True
        )

    if "sessions" not in tables:
        op.create_table(
            "sessions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("ip", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.String(500), nullable=True),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("dek_wrapped", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
        op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
        op.create_index("ix_sessions_user_revoked", "sessions", ["user_id", "revoked_at"])
        op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])
    elif "dek_wrapped" not in _columns("sessions"):
        with op.batch_alter_table("sessions") as batch:
            batch.add_column(sa.Column("dek_wrapped", sa.Text(), nullable=True))

    if "login_attempts" not in tables:
        op.create_table(
            "login_attempts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("ip", sa.String(45), nullable=True),
            sa.Column("ok", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])
        op.create_index(
            "ix_login_attempts_email_created", "login_attempts", ["email", "created_at"]
        )
        op.create_index("ix_login_attempts_ip_created", "login_attempts", ["ip", "created_at"])

    if "central_jobs" not in tables:
        op.create_table(
            "central_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("ref_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("run_at", sa.DateTime(), nullable=False),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("locked_until", sa.DateTime(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_central_jobs_user_id", "central_jobs", ["user_id"])
        op.create_index("ix_central_jobs_status_run_at", "central_jobs", ["status", "run_at"])

    if "worker_keys" not in tables:
        op.create_table(
            "worker_keys",
            sa.Column("id", sa.String(32), primary_key=True),
            sa.Column("public_key", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_seen_at", sa.DateTime(), nullable=False),
        )

    if "key_leases" not in tables:
        op.create_table(
            "key_leases",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("worker_key_id", sa.String(32), nullable=False),
            sa.Column("purpose", sa.String(20), nullable=False),
            sa.Column("sealed_dek", sa.Text(), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["worker_key_id"], ["worker_keys.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("user_id", "worker_key_id", "purpose", name="uq_key_lease"),
        )
        op.create_index("ix_key_leases_user_id", "key_leases", ["user_id"])


def downgrade() -> None:
    tables = _tables()
    for table in ("key_leases", "worker_keys", "central_jobs"):
        if table in tables:
            op.drop_table(table)
    # Las columnas añadidas a users/sessions se conservan: en modo single son
    # tablas compartidas con la cadena de datos.
