"""v3_006_taxonomy_tree_tags — árbol de categorías y etiquetas agrupadas.

Añade la jerarquía de categorías (``parent_id``), la tipología de aplicación
(``gasto``/``ingreso``/``ambos``), el tratamiento de transferencia/inversión y
los metadatos editables desde Ajustes. También crea los grupos de etiquetas y
la relación entre etiquetas y movimientos v3.

La migración no reasigna clasificaciones existentes: solo reorganiza el árbol
y crea el catálogo de etiquetas. Las reasignaciones de movimientos se harán
después, con preview y confirmación.

Revision ID: v3_006_taxonomy
Revises: v3_005_user_profile
Create Date: 2026-11-01
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "v3_006_taxonomy"
down_revision: Union[str, None] = "v3_005_user_profile"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
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


def _create_index(
    bind, name: str, table: str, columns: list[str], *, unique: bool = False
) -> None:
    if table in _tables(bind) and name not in _indexes(bind, table):
        op.create_index(name, table, columns, unique=unique)


def _ref_column(bind, name: str, target: str, *, ondelete: str) -> sa.Column:
    """SQLite no permite añadir una FK con ALTER ADD COLUMN."""
    if bind.dialect.name == "sqlite":
        return sa.Column(name, sa.Integer(), nullable=True)
    return sa.Column(
        name,
        sa.Integer(),
        sa.ForeignKey(target, ondelete=ondelete),
        nullable=True,
    )


def _bool_default(bind, value: bool) -> sa.TextClause:
    if bind.dialect.name == "sqlite":
        return sa.text("1" if value else "0")
    return sa.text("true" if value else "false")


def _category_id(bind, nombre: str) -> int | None:
    row = bind.execute(
        sa.text("SELECT id FROM categorias WHERE nombre=:nombre"),
        {"nombre": nombre},
    ).first()
    return int(row[0]) if row else None


def _ensure_category(
    bind,
    *,
    nombre: str,
    aplica_a: str,
    tratamiento: str,
    color: str,
    excluir_kpis: bool,
    orden: int,
    system_key: str | None = None,
    parent_id: int | None = None,
    descripcion: str | None = None,
) -> int:
    category_id = _category_id(bind, nombre)
    values = {
        "nombre": nombre,
        "parent_id": parent_id,
        "aplica_a": aplica_a,
        "tratamiento": tratamiento,
        "color": color,
        "excluir_kpis": excluir_kpis,
        "orden": orden,
        "system_key": system_key,
        "descripcion": descripcion,
    }
    if category_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, activa, creado_en, actualizado_en) "
                "VALUES (:nombre, :parent_id, :aplica_a, :tratamiento, :color, "
                "        :excluir_kpis, :orden, :system_key, :descripcion, "
                "        :activa, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {**values, "activa": True},
        )
        category_id = _category_id(bind, nombre)
    else:
        bind.execute(
            sa.text(
                "UPDATE categorias SET parent_id=:parent_id, aplica_a=:aplica_a, "
                "tratamiento=:tratamiento, color=:color, excluir_kpis=:excluir_kpis, "
                "orden=:orden, system_key=:system_key, "
                "descripcion=COALESCE(:descripcion, descripcion), "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {**values, "id": category_id},
        )
    if category_id is None:
        raise RuntimeError(f"No se pudo crear la categoría {nombre!r}")
    return category_id


def _ensure_tag_group(bind, nombre: str, color: str, orden: int) -> int:
    row = bind.execute(
        sa.text("SELECT id FROM tag_groups WHERE nombre=:nombre"),
        {"nombre": nombre},
    ).first()
    if row:
        return int(row[0])
    bind.execute(
        sa.text(
            "INSERT INTO tag_groups (nombre, color, orden, creado_en) "
            "VALUES (:nombre, :color, :orden, CURRENT_TIMESTAMP)"
        ),
        {"nombre": nombre, "color": color, "orden": orden},
    )
    row = bind.execute(
        sa.text("SELECT id FROM tag_groups WHERE nombre=:nombre"),
        {"nombre": nombre},
    ).first()
    if not row:
        raise RuntimeError(f"No se pudo crear el grupo de etiquetas {nombre!r}")
    return int(row[0])


def _ensure_tag(
    bind,
    *,
    nombre: str,
    color: str,
    group_id: int | None,
    orden: int,
    descripcion: str | None = None,
) -> None:
    row = bind.execute(
        sa.text("SELECT id FROM etiquetas WHERE nombre=:nombre"),
        {"nombre": nombre},
    ).first()
    if row:
        bind.execute(
            sa.text(
                "UPDATE etiquetas SET color=:color, group_id=:group_id, "
                "orden=:orden, descripcion=COALESCE(descripcion, :descripcion), "
                "activa=:activa WHERE id=:id"
            ),
            {
                "id": row[0],
                "color": color,
                "group_id": group_id,
                "orden": orden,
                "descripcion": descripcion,
                "activa": True,
            },
        )
        return
    bind.execute(
        sa.text(
            "INSERT INTO etiquetas "
            "(nombre, color, descripcion, group_id, orden, activa, creado_en) "
            "VALUES (:nombre, :color, :descripcion, :group_id, :orden, "
            "        :activa, CURRENT_TIMESTAMP)"
        ),
        {
            "nombre": nombre,
            "color": color,
            "descripcion": descripcion,
            "group_id": group_id,
            "orden": orden,
            "activa": True,
        },
    )


def _seed_taxonomy(bind) -> None:
    # Metadatos de las categorías que ya existían. Los nombres no cambian y
    # los IDs se conservan, así que las clasificaciones históricas siguen
    # apuntando a la misma fila.
    _ensure_category(
        bind,
        nombre="Alimentación",
        aplica_a="gasto",
        tratamiento="normal",
        color="#16a34a",
        excluir_kpis=False,
        orden=10,
    )
    _ensure_category(
        bind,
        nombre="Supermercado",
        aplica_a="gasto",
        tratamiento="normal",
        color="#22c55e",
        excluir_kpis=False,
        orden=10,
        parent_id=_category_id(bind, "Alimentación"),
    )
    _ensure_category(
        bind,
        nombre="Bares y Restaurantes",
        aplica_a="gasto",
        tratamiento="normal",
        color="#f97316",
        excluir_kpis=False,
        orden=20,
        parent_id=_category_id(bind, "Alimentación"),
    )
    _ensure_category(
        bind,
        nombre="Vivienda",
        aplica_a="gasto",
        tratamiento="normal",
        color="#0ea5e9",
        excluir_kpis=False,
        orden=20,
    )
    _ensure_category(
        bind,
        nombre="Facturas",
        aplica_a="gasto",
        tratamiento="normal",
        color="#38bdf8",
        excluir_kpis=False,
        orden=10,
        parent_id=_category_id(bind, "Vivienda"),
    )
    _ensure_category(
        bind,
        nombre="Transporte",
        aplica_a="gasto",
        tratamiento="normal",
        color="#f59e0b",
        excluir_kpis=False,
        orden=30,
    )
    _ensure_category(
        bind,
        nombre="Servicios",
        aplica_a="gasto",
        tratamiento="normal",
        color="#8b5cf6",
        excluir_kpis=False,
        orden=40,
    )
    _ensure_category(
        bind,
        nombre="Suscripciones",
        aplica_a="gasto",
        tratamiento="normal",
        color="#ec4899",
        excluir_kpis=False,
        orden=10,
        parent_id=_category_id(bind, "Servicios"),
    )
    _ensure_category(
        bind,
        nombre="Telecomunicaciones",
        aplica_a="gasto",
        tratamiento="normal",
        color="#a78bfa",
        excluir_kpis=False,
        orden=20,
        parent_id=_category_id(bind, "Servicios"),
    )
    _ensure_category(
        bind,
        nombre="Ocio",
        aplica_a="gasto",
        tratamiento="normal",
        color="#a855f7",
        excluir_kpis=False,
        orden=50,
    )
    _ensure_category(
        bind,
        nombre="Compras",
        aplica_a="gasto",
        tratamiento="normal",
        color="#8b5cf6",
        excluir_kpis=False,
        orden=60,
    )
    _ensure_category(
        bind,
        nombre="Salud",
        aplica_a="gasto",
        tratamiento="normal",
        color="#ef4444",
        excluir_kpis=False,
        orden=70,
    )
    _ensure_category(
        bind,
        nombre="Salario",
        aplica_a="ingreso",
        tratamiento="normal",
        color="#22c55e",
        excluir_kpis=False,
        orden=10,
        system_key="salario",
    )
    _ensure_category(
        bind,
        nombre="Otros ingresos",
        aplica_a="ingreso",
        tratamiento="normal",
        color="#0ea5e9",
        excluir_kpis=False,
        orden=20,
        system_key="otros_ingresos",
    )
    _ensure_category(
        bind,
        nombre="Cashback",
        aplica_a="ingreso",
        tratamiento="normal",
        color="#34d399",
        excluir_kpis=False,
        orden=10,
        system_key="cashback",
        parent_id=_category_id(bind, "Otros ingresos"),
    )
    _ensure_category(
        bind,
        nombre="Transferencias",
        aplica_a="ambos",
        tratamiento="transferencia",
        color="#64748b",
        excluir_kpis=True,
        orden=90,
        system_key="transferencias",
    )
    _ensure_category(
        bind,
        nombre="Inversiones",
        aplica_a="ambos",
        tratamiento="inversion",
        color="#0f766e",
        excluir_kpis=True,
        orden=100,
        system_key="inversiones",
    )
    _ensure_category(
        bind,
        nombre="Otros",
        aplica_a="ambos",
        tratamiento="normal",
        color="#94a3b8",
        excluir_kpis=False,
        orden=110,
        system_key="otros",
    )
    # Se conserva temporalmente como raíz hasta decidir su reasignación.
    _ensure_category(
        bind,
        nombre="Revolut",
        aplica_a="gasto",
        tratamiento="normal",
        color="#6366f1",
        excluir_kpis=False,
        orden=120,
    )

    # Grupos y etiquetas iniciales. Fijo/Variable dejan de ser subtipos y
    # pasan a ser etiquetas libres.
    recurrencia = _ensure_tag_group(bind, "Recurrencia", "#6366f1", 10)
    viajes = _ensure_tag_group(bind, "Viajes", "#14b8a6", 20)
    _ensure_tag(
        bind,
        nombre="Fijo",
        color="#64748b",
        group_id=recurrencia,
        orden=10,
        descripcion="Gasto recurrente o periódico.",
    )
    _ensure_tag(
        bind,
        nombre="Variable",
        color="#94a3b8",
        group_id=recurrencia,
        orden=20,
        descripcion="Gasto no recurrente o puntual.",
    )
    _ensure_tag(
        bind,
        nombre="Korea 2026",
        color="#14b8a6",
        group_id=viajes,
        orden=10,
    )

    # La etiqueta "Vivienda" duplicaba la categoría y no tenía uso.
    tables = _tables(bind)
    guards = []
    if "movement_tags" in tables:
        guards.append(
            "NOT EXISTS (SELECT 1 FROM movement_tags mt WHERE mt.tag_id=etiquetas.id)"
        )
    if "movimiento_etiquetas" in tables:
        guards.append(
            "NOT EXISTS (SELECT 1 FROM movimiento_etiquetas me WHERE me.etiqueta_id=etiquetas.id)"
        )
    delete_sql = "DELETE FROM etiquetas WHERE nombre='Vivienda'"
    if guards:
        delete_sql += " AND " + " AND ".join(guards)
    bind.execute(sa.text(delete_sql))


def upgrade() -> None:
    bind = op.get_bind()

    # ── Categorías: metadatos + jerarquía ─────────────────────────────────
    _add_column(
        bind,
        "categorias",
        _ref_column(bind, "parent_id", "categorias.id", ondelete="SET NULL"),
    )
    _add_column(
        bind,
        "categorias",
        sa.Column("aplica_a", sa.String(length=10), nullable=False, server_default="gasto"),
    )
    _add_column(
        bind,
        "categorias",
        sa.Column(
            "tratamiento", sa.String(length=20), nullable=False, server_default="normal"
        ),
    )
    _add_column(
        bind,
        "categorias",
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#6366f1"),
    )
    _add_column(
        bind,
        "categorias",
        sa.Column(
            "excluir_kpis",
            sa.Boolean(),
            nullable=False,
            server_default=_bool_default(bind, False),
        ),
    )
    _add_column(
        bind,
        "categorias",
        sa.Column("orden", sa.Integer(), nullable=False, server_default="100"),
    )
    _add_column(bind, "categorias", sa.Column("system_key", sa.String(length=40), nullable=True))
    _add_column(bind, "categorias", sa.Column("actualizado_en", sa.DateTime(), nullable=True))
    _create_index(bind, "ix_categorias_parent_id", "categorias", ["parent_id"])
    _create_index(
        bind, "uq_categorias_system_key", "categorias", ["system_key"], unique=True
    )

    # ── Grupos de etiquetas ────────────────────────────────────────────────
    if "tag_groups" not in _tables(bind):
        op.create_table(
            "tag_groups",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("nombre", sa.String(length=100), nullable=False),
            sa.Column("color", sa.String(length=20), nullable=False, server_default="#6366f1"),
            sa.Column("orden", sa.Integer(), nullable=False, server_default="100"),
            sa.Column(
                "creado_en",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("nombre"),
        )

    _add_column(
        bind,
        "etiquetas",
        _ref_column(bind, "group_id", "tag_groups.id", ondelete="SET NULL"),
    )
    _add_column(
        bind,
        "etiquetas",
        sa.Column("orden", sa.Integer(), nullable=False, server_default="100"),
    )
    _add_column(
        bind,
        "etiquetas",
        sa.Column(
            "activa",
            sa.Boolean(),
            nullable=False,
            server_default=_bool_default(bind, True),
        ),
    )
    _create_index(bind, "ix_etiquetas_group_id", "etiquetas", ["group_id"])

    # ── Etiquetas ↔ movimientos v3 ────────────────────────────────────────
    if "movement_tags" not in _tables(bind):
        op.create_table(
            "movement_tags",
            sa.Column("movement_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.Column("origen", sa.String(length=10), nullable=False, server_default="user"),
            sa.Column(
                "creado_en",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["movement_id"], ["financial_movements.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tag_id"], ["etiquetas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("movement_id", "tag_id"),
        )
        _create_index(bind, "ix_movement_tags_tag_id", "movement_tags", ["tag_id"])

    if "classification_rule_tags" not in _tables(bind):
        op.create_table(
            "classification_rule_tags",
            sa.Column("rule_id", sa.Integer(), nullable=False),
            sa.Column("tag_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(
                ["rule_id"], ["classification_rules.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["tag_id"], ["etiquetas.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("rule_id", "tag_id"),
        )
        _create_index(
            bind, "ix_classification_rule_tags_tag_id", "classification_rule_tags", ["tag_id"]
        )

    _seed_taxonomy(bind)


def downgrade() -> None:
    bind = op.get_bind()

    for table in ("classification_rule_tags", "movement_tags"):
        if table in _tables(bind):
            op.drop_table(table)

    if "etiquetas" in _tables(bind):
        for index in ("ix_etiquetas_group_id",):
            if index in _indexes(bind, "etiquetas"):
                op.drop_index(index, table_name="etiquetas")
        with op.batch_alter_table("etiquetas") as batch:
            for column in ("group_id", "orden", "activa"):
                if column in _columns(bind, "etiquetas"):
                    batch.drop_column(column)

    if "tag_groups" in _tables(bind):
        op.drop_table("tag_groups")

    if "categorias" in _tables(bind):
        for index in ("ix_categorias_parent_id", "uq_categorias_system_key"):
            if index in _indexes(bind, "categorias"):
                op.drop_index(index, table_name="categorias")
        with op.batch_alter_table("categorias") as batch:
            for column in (
                "parent_id",
                "aplica_a",
                "tratamiento",
                "color",
                "excluir_kpis",
                "orden",
                "system_key",
                "actualizado_en",
            ):
                if column in _columns(bind, "categorias"):
                    batch.drop_column(column)
