"""v1_existing — esquema actual tras ad-hoc migrations de database.py

Baseline que captura el estado del esquema existente y elimina la
columna 'tipo_gasto' (renombrada a 'subtipo' en el modelo) y añade
el índice para movimiento_id en operaciones.

Los pasos son idempotentes: una base vacía (por ejemplo, un PostgreSQL
nuevo) no tiene ``movimientos``/``operaciones``. En ese caso la baseline
crea las tablas mínimas que las migraciones v2 necesitan como padres
(``categorias``, ``etiquetas``, ``subtipos`` y ``app_config``). Así
``alembic upgrade head`` funciona tanto sobre una copia de la base local
como desde cero, sin reescribir el esquema histórico.

Revision ID: c3064480f926
Revises:
Create Date: 2026-07-26 19:14:10.731928

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'c3064480f926'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _create_base_tables_if_missing(bind) -> None:
    """Crea solo las tablas legadas necesarias para las FKs de v2."""
    tables = _tables(bind)

    if "categorias" not in tables:
        op.create_table(
            "categorias",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=255), nullable=False),
            sa.Column("descripcion", sa.String(length=500), nullable=True),
            sa.Column("activa", sa.Boolean(), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nombre"),
        )

    if "etiquetas" not in tables:
        op.create_table(
            "etiquetas",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("color", sa.String(length=20), nullable=False),
            sa.Column("descripcion", sa.String(length=500), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nombre"),
        )

    if "subtipos" not in tables:
        op.create_table(
            "subtipos",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("tipo", sa.String(length=20), nullable=False),
            sa.Column("descripcion", sa.String(length=500), nullable=True),
            sa.Column("activo", sa.Boolean(), nullable=True),
            sa.Column("creado_en", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nombre", "tipo", name="uq_subtipo_nombre_tipo"),
        )

    if "app_config" not in tables:
        op.create_table(
            "app_config",
            sa.Column("key", sa.String(length=200), nullable=False),
            sa.Column("value", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("key"),
        )


def upgrade() -> None:
    bind = op.get_bind()

    # Base vacía: crear padres mínimos para las FKs de v2_001.
    _create_base_tables_if_missing(bind)

    # Remover columna sobrante del rename ad-hoc tipo_gasto → subtipo
    if "movimientos" in _tables(bind) and "tipo_gasto" in _columns(bind, "movimientos"):
        with op.batch_alter_table('movimientos') as batch_op:
            batch_op.drop_column('tipo_gasto')

    # Añadir índice para movimiento_id en operaciones
    if "operaciones" in _tables(bind) and "movimiento_id" in _columns(bind, "operaciones"):
        indexes = {i["name"] for i in inspect(bind).get_indexes("operaciones")}
        if "ix_operaciones_movimiento_id" not in indexes:
            op.create_index(
                'ix_operaciones_movimiento_id',
                'operaciones', ['movimiento_id'],
                unique=False,
            )


def downgrade() -> None:
    bind = op.get_bind()
    if "operaciones" in _tables(bind):
        indexes = {i["name"] for i in inspect(bind).get_indexes("operaciones")}
        if "ix_operaciones_movimiento_id" in indexes:
            op.drop_index(
                'ix_operaciones_movimiento_id',
                table_name='operaciones',
            )
    if "movimientos" in _tables(bind) and "tipo_gasto" not in _columns(bind, "movimientos"):
        with op.batch_alter_table('movimientos') as batch_op:
            batch_op.add_column(
                sa.Column('tipo_gasto', sa.VARCHAR(length=50), nullable=True)
            )
