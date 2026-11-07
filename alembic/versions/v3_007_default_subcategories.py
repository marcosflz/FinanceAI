"""v3_007_default_subcategories — subcategoría «Otros» por defecto.

Cambia la unicidad de ``categorias.nombre`` de global a por padre (para poder
tener un ``Otros`` debajo de cada categoría), añade ``es_default`` y crea la
rama de ingresos ``Beneficios`` con Cashback, Intereses, Beneficios y
Dividendos.

La migración es estructural: crea el árbol y los ``Otros`` por defecto. El
movimiento de clasificaciones existentes a esos ``Otros`` se hace después con
``scripts/apply_default_subcategories.py`` y preview previo.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "v3_007_default_subcategories"
down_revision: Union[str, None] = "v3_006_taxonomy"
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


def _sqlite_rebuild_categories_without_unique(bind) -> None:
    """SQLite no permite borrar un UNIQUE inline; recreamos la tabla."""
    meta = sa.MetaData()
    copy_from = sa.Table(
        "categorias",
        meta,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("nombre", sa.String(length=255), nullable=False),
        sa.Column("descripcion", sa.String(length=500), nullable=True),
        sa.Column("activa", sa.Boolean(), nullable=True),
        sa.Column("creado_en", sa.DateTime(), nullable=True),
        sa.Column("parent_id", sa.Integer(), nullable=True),
        sa.Column("aplica_a", sa.String(length=10), nullable=False, server_default="gasto"),
        sa.Column("tratamiento", sa.String(length=20), nullable=False, server_default="normal"),
        sa.Column("color", sa.String(length=20), nullable=False, server_default="#6366f1"),
        sa.Column(
            "excluir_kpis",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("system_key", sa.String(length=40), nullable=True),
        sa.Column(
            "es_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("actualizado_en", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["parent_id"], ["categorias.id"], ondelete="SET NULL"),
    )
    with op.batch_alter_table(
        "categorias", copy_from=copy_from, recreate="always"
    ) as _batch:
        pass


def _create_taxonomy_indexes(bind) -> None:
    indexes = _indexes(bind, "categorias")
    if "ix_categorias_parent_id" not in indexes:
        op.create_index("ix_categorias_parent_id", "categorias", ["parent_id"])
    if "uq_categorias_system_key" not in indexes:
        op.create_index(
            "uq_categorias_system_key", "categorias", ["system_key"], unique=True
        )
    if "ix_categorias_parent_default" not in indexes:
        op.create_index(
            "ix_categorias_parent_default", "categorias", ["parent_id", "es_default"]
        )
    if "uq_categorias_parent_nombre" not in indexes:
        bind.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_categorias_parent_nombre "
                "ON categorias (COALESCE(parent_id, 0), lower(nombre))"
            )
        )


def _find_category(bind, nombre: str, parent_id: int | None) -> int | None:
    row = bind.execute(
        sa.text(
            "SELECT id FROM categorias "
            "WHERE lower(nombre)=lower(:nombre) "
            "AND COALESCE(parent_id, 0)=COALESCE(:parent_id, 0)"
        ),
        {"nombre": nombre, "parent_id": parent_id},
    ).first()
    return int(row[0]) if row else None


def _find_any_category(bind, nombre: str) -> int | None:
    row = bind.execute(
        sa.text("SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre)"),
        {"nombre": nombre},
    ).first()
    return int(row[0]) if row else None


def _upsert_category(
    bind,
    *,
    nombre: str,
    parent_id: int | None,
    aplica_a: str,
    tratamiento: str,
    color: str,
    excluir_kpis: bool,
    orden: int,
    system_key: str | None = None,
    descripcion: str | None = None,
    es_default: bool = False,
    activa: bool = True,
) -> int:
    category_id = _find_category(bind, nombre, parent_id)
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
        "es_default": es_default,
        "activa": activa,
    }
    if category_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                "VALUES (:nombre, :parent_id, :aplica_a, :tratamiento, :color, "
                "        :excluir_kpis, :orden, :system_key, :descripcion, "
                "        :es_default, :activa, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            values,
        )
        category_id = _find_category(bind, nombre, parent_id)
    else:
        bind.execute(
            sa.text(
                "UPDATE categorias SET parent_id=:parent_id, aplica_a=:aplica_a, "
                "tratamiento=:tratamiento, color=:color, excluir_kpis=:excluir_kpis, "
                "orden=:orden, system_key=COALESCE(:system_key, system_key), "
                "descripcion=COALESCE(:descripcion, descripcion), "
                "es_default=:es_default, activa=:activa, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {**values, "id": category_id},
        )
    if category_id is None:
        raise RuntimeError(f"No se pudo crear la categoría {nombre!r}")
    return category_id


def _upsert_default_child(
    bind,
    parent: dict,
    *,
    orden: int = 999,
) -> int:
    return _upsert_category(
        bind,
        nombre="Otros",
        parent_id=parent["id"],
        aplica_a=parent["aplica_a"],
        tratamiento=parent["tratamiento"],
        color=parent["color"] or "#6366f1",
        excluir_kpis=bool(parent["excluir_kpis"]),
        orden=orden,
        descripcion="Categoría por defecto cuando no se especifica otra.",
        es_default=True,
        activa=True,
    )


def _category_row(bind, category_id: int) -> dict:
    row = bind.execute(
        sa.text(
            "SELECT id, nombre, parent_id, aplica_a, tratamiento, color, "
            "excluir_kpis, activa FROM categorias WHERE id=:id"
        ),
        {"id": category_id},
    ).mappings().first()
    if row is None:
        raise RuntimeError(f"Categoría {category_id} no encontrada")
    return dict(row)


def _seed_default_tree(bind) -> None:
    # 1. Beneficios y sus hijas.
    beneficios_id = _upsert_category(
        bind,
        nombre="Beneficios",
        parent_id=None,
        aplica_a="ingreso",
        tratamiento="normal",
        color="#10b981",
        excluir_kpis=False,
        orden=30,
        system_key="beneficios",
        descripcion="Ingresos por cashback, intereses, dividendos y ventas.",
    )
    cashback_id = _find_any_category(bind, "Cashback")
    if cashback_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET parent_id=:parent_id, aplica_a='ingreso', "
                "tratamiento='normal', color='#34d399', excluir_kpis=false, "
                "orden=10, system_key='cashback', activa=true, "
                "descripcion=COALESCE(descripcion, :descripcion), "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {
                "id": cashback_id,
                "parent_id": beneficios_id,
                "descripcion": "Cashback, saveback y devoluciones de compras.",
            },
        )
    else:
        _upsert_category(
            bind,
            nombre="Cashback",
            parent_id=beneficios_id,
            aplica_a="ingreso",
            tratamiento="normal",
            color="#34d399",
            excluir_kpis=False,
            orden=10,
            system_key="cashback",
            descripcion="Cashback, saveback y devoluciones de compras.",
        )
    _upsert_category(
        bind,
        nombre="Intereses",
        parent_id=beneficios_id,
        aplica_a="ingreso",
        tratamiento="normal",
        color="#22d3ee",
        excluir_kpis=False,
        orden=20,
        system_key="intereses",
        descripcion="Intereses de cuentas, depósitos y activos.",
    )
    _upsert_category(
        bind,
        nombre="Beneficios",
        parent_id=beneficios_id,
        aplica_a="ingreso",
        tratamiento="normal",
        color="#14b8a6",
        excluir_kpis=False,
        orden=30,
        system_key="beneficios_venta",
        descripcion="Resultado de vender un activo.",
    )
    _upsert_category(
        bind,
        nombre="Dividendos",
        parent_id=beneficios_id,
        aplica_a="ingreso",
        tratamiento="normal",
        color="#0ea5e9",
        excluir_kpis=False,
        orden=40,
        system_key="dividendos",
        descripcion="Dividendos de acciones, fondos y ETFs.",
    )
    _upsert_default_child(bind, _category_row(bind, beneficios_id))

    # 2. «Otros» por defecto en cada categoría raíz activa.
    root_rows = bind.execute(
        sa.text(
            "SELECT id, nombre, parent_id, aplica_a, tratamiento, color, "
            "excluir_kpis, activa FROM categorias "
            "WHERE parent_id IS NULL AND activa=true ORDER BY orden, id"
        )
    ).mappings().all()
    for row in root_rows:
        if row["nombre"] in {"Otros", "Otros ingresos"}:
            continue
        _upsert_default_child(bind, dict(row))

    # 3. Las antiguas categorías comodín desaparecen de la vista activa.
    for name in ("Otros", "Otros ingresos"):
        category_id = _find_any_category(bind, name)
        if category_id is not None:
            bind.execute(
                sa.text(
                    "UPDATE categorias SET activa=false, actualizado_en=CURRENT_TIMESTAMP "
                    "WHERE id=:id"
                ),
                {"id": category_id},
            )


def upgrade() -> None:
    bind = op.get_bind()
    _add_column(
        bind,
        "categorias",
        sa.Column(
            "es_default",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false" if bind.dialect.name != "sqlite" else "0"),
        ),
    )

    if bind.dialect.name == "sqlite":
        _sqlite_rebuild_categories_without_unique(bind)
    else:
        unique_constraints = {
            item["name"] for item in inspect(bind).get_unique_constraints("categorias")
        }
        if "categorias_nombre_key" in unique_constraints:
            op.drop_constraint("categorias_nombre_key", "categorias", type_="unique")

    _create_taxonomy_indexes(bind)
    _seed_default_tree(bind)


def downgrade() -> None:
    bind = op.get_bind()
    indexes = _indexes(bind, "categorias")
    for index in (
        "uq_categorias_parent_nombre",
        "ix_categorias_parent_default",
    ):
        if index in indexes:
            op.drop_index(index, table_name="categorias")
    if "es_default" in _columns(bind, "categorias"):
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("categorias") as batch:
                batch.drop_column("es_default")
        else:
            op.drop_column("categorias", "es_default")
