"""v3_011_two_level_taxonomy — taxonomía de dos niveles y Ventas en Inversiones.

- Aplana cualquier nodo de tercer nivel: todas las subcategorías cuelgan
  directamente de su raíz.
- Mueve ``Ingresos › Beneficios`` a ``Inversiones › Ventas`` conservando el id
  para no romper clasificaciones históricas.
- Crea ``Inversiones › Compras``, ``Inversiones › Aportaciones`` e
  ``Inversiones › Cashback`` (duplicado de ``Ingresos › Cashback``).
- Propaga el tratamiento y la exclusión de KPIs de cada raíz a sus hijas.

No cambia el esquema. Es idempotente y se apoya en SQL portable SQLite/PostgreSQL.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v3_011_two_level_taxonomy"
down_revision: Union[str, None] = "v3_010_reimport_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CATEGORY_TABLES = (
    ("classifications", "categoria_id"),
    ("classification_memory", "categoria_id"),
    ("classification_rules", "set_categoria_id"),
)


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table)}


def _find_category(bind, nombre: str, parent_id: int | None) -> int | None:
    row = bind.execute(
        sa.text(
            "SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre) "
            "AND COALESCE(parent_id, 0)=COALESCE(:parent_id, 0)"
        ),
        {"nombre": nombre, "parent_id": parent_id},
    ).first()
    return int(row[0]) if row else None


def _category_row(bind, category_id: int):
    return bind.execute(
        sa.text(
            "SELECT id, nombre, parent_id, aplica_a, tratamiento, excluir_kpis, "
            "es_default, activa, color, orden, system_key "
            "FROM categorias WHERE id=:id"
        ),
        {"id": category_id},
    ).first()


def _ensure_child(
    bind,
    *,
    parent_id: int,
    nombre: str,
    aplica_a: str,
    orden: int,
    color: str,
    system_key: str,
    descripcion: str,
) -> int:
    existing = _find_category(bind, nombre, parent_id)
    if existing is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET aplica_a=:aplica_a, tratamiento='inversion', "
                "excluir_kpis=true, es_default=false, activa=true, orden=:orden, "
                "color=:color, system_key=COALESCE(system_key, :system_key), "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {
                "id": existing,
                "aplica_a": aplica_a,
                "orden": orden,
                "color": color,
                "system_key": system_key,
            },
        )
        return existing

    system_key_used = bind.execute(
        sa.text("SELECT id FROM categorias WHERE system_key=:system_key"),
        {"system_key": system_key},
    ).first()
    insert_key = None if system_key_used else system_key
    bind.execute(
        sa.text(
            "INSERT INTO categorias "
            "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
            " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
            "VALUES (:nombre, :parent_id, :aplica_a, 'inversion', :color, true, "
            "        :orden, :system_key, :descripcion, false, true, "
            "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "nombre": nombre,
            "parent_id": parent_id,
            "aplica_a": aplica_a,
            "color": color,
            "orden": orden,
            "system_key": insert_key,
            "descripcion": descripcion,
        },
    )
    child_id = _find_category(bind, nombre, parent_id)
    if child_id is None:
        raise RuntimeError(f"No se pudo crear la categoría {nombre!r}")
    return child_id


def _update_category_refs(bind, source_id: int, target_id: int) -> None:
    tables = _tables(bind)
    for table, column in CATEGORY_TABLES:
        if table not in tables:
            continue
        bind.execute(
            sa.text(
                f"UPDATE {table} SET {column}=:target WHERE {column}=:source"
            ),
            {"target": target_id, "source": source_id},
        )
    # Los hijos del nodo que se fusiona pasan al destino; después el aplanado
    # los sube a la raíz si hace falta.
    bind.execute(
        sa.text("UPDATE categorias SET parent_id=:target WHERE parent_id=:source"),
        {"target": target_id, "source": source_id},
    )


def _merge_category(bind, source_id: int, target_id: int) -> None:
    if source_id == target_id:
        return
    _update_category_refs(bind, source_id, target_id)
    bind.execute(
        sa.text("DELETE FROM categorias WHERE id=:id"),
        {"id": source_id},
    )


def _move_beneficios_to_inversiones(bind, *, ingresos_id: int, inversiones_id: int) -> None:
    beneficios_id = _find_category(bind, "Beneficios", ingresos_id)
    ventas_id = _find_category(bind, "Ventas", inversiones_id)

    if beneficios_id is None:
        if ventas_id is None:
            bind.execute(
                sa.text(
                    "INSERT INTO categorias "
                    "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                    " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                    "VALUES ('Ventas', :parent_id, 'ingreso', 'inversion', '#0f766e', true, "
                    "        20, 'inversion_ventas', "
                    "        'Venta de un activo; el importe bruto no es ingreso corriente.', "
                    "        false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"parent_id": inversiones_id},
            )
        return

    if ventas_id is not None:
        _merge_category(bind, beneficios_id, ventas_id)
        return

    # Renombrar/mover el nodo existente conserva su id y sus clasificaciones.
    row = _category_row(bind, beneficios_id)
    system_key = row.system_key if row is not None else None
    if system_key is None or system_key == "beneficios_venta":
        used = bind.execute(
            sa.text("SELECT id FROM categorias WHERE system_key='inversion_ventas'")
        ).first()
        system_key = None if used else "inversion_ventas"
    bind.execute(
        sa.text(
            "UPDATE categorias SET nombre='Ventas', parent_id=:parent_id, "
            "aplica_a='ingreso', tratamiento='inversion', excluir_kpis=true, "
            "es_default=false, activa=true, orden=20, system_key=:system_key, "
            "descripcion=:descripcion, actualizado_en=CURRENT_TIMESTAMP "
            "WHERE id=:id"
        ),
        {
            "id": beneficios_id,
            "parent_id": inversiones_id,
            "system_key": system_key,
            "descripcion": (
                "Venta de un activo; el importe bruto no es ingreso corriente."
            ),
        },
    )


def _flatten_tree(bind) -> None:
    """Sube cualquier nieto a su raíz, fusionando nombres duplicados."""
    for _ in range(100):
        rows = bind.execute(
            sa.text(
                "SELECT id, nombre, parent_id, aplica_a, tratamiento, excluir_kpis, "
                "es_default, activa FROM categorias"
            )
        ).fetchall()
        by_id = {int(row.id): row for row in rows}
        moved = 0
        for row in rows:
            category_id = int(row.id)
            parent_id = row.parent_id
            if parent_id is None:
                continue
            parent = by_id.get(int(parent_id))
            if parent is None or parent.parent_id is None:
                continue

            root_id = int(parent.parent_id)
            duplicate_id = _find_category(bind, row.nombre, root_id)
            if duplicate_id is not None and duplicate_id != category_id:
                _merge_category(bind, category_id, duplicate_id)
            else:
                bind.execute(
                    sa.text(
                        "UPDATE categorias SET parent_id=:root_id, es_default=false, "
                        "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
                    ),
                    {"root_id": root_id, "id": category_id},
                )
            moved += 1

        if moved == 0:
            return

    raise RuntimeError("No se pudo aplanar la taxonomía a dos niveles")


def _inherit_treatment(bind) -> None:
    rows = bind.execute(
        sa.text(
            "SELECT id, parent_id, tratamiento, excluir_kpis FROM categorias"
        )
    ).fetchall()
    by_id = {int(row.id): row for row in rows}
    for row in rows:
        if row.parent_id is None:
            continue
        parent = by_id.get(int(row.parent_id))
        if parent is None:
            continue
        excluded = bool(parent.excluir_kpis) or parent.tratamiento in {
            "transferencia",
            "inversion",
        }
        bind.execute(
            sa.text(
                "UPDATE categorias SET tratamiento=:tratamiento, "
                "excluir_kpis=:excluir, actualizado_en=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {
                "id": int(row.id),
                "tratamiento": parent.tratamiento,
                "excluir": excluded,
            },
        )


def _assert_two_levels(bind) -> None:
    rows = bind.execute(
        sa.text("SELECT id, nombre, parent_id FROM categorias")
    ).fetchall()
    by_id = {int(row.id): row for row in rows}
    invalid = [
        row for row in rows
        if row.parent_id is not None
        and (
            int(row.parent_id) not in by_id
            or by_id[int(row.parent_id)].parent_id is not None
        )
    ]
    if invalid:
        names = ", ".join(f"{row.id}:{row.nombre}" for row in invalid)
        raise RuntimeError(f"Taxonomía con más de dos niveles: {names}")


def upgrade() -> None:
    bind = op.get_bind()
    if "categorias" not in _tables(bind):
        return

    ingresos_id = _find_category(bind, "Ingresos", None)
    inversiones_id = _find_category(bind, "Inversiones", None)
    if inversiones_id is None:
        return

    color = "#0f766e"
    _ensure_child(
        bind,
        parent_id=inversiones_id,
        nombre="Compras",
        aplica_a="gasto",
        orden=10,
        color=color,
        system_key="inversion_compras",
        descripcion="Compras de acciones, fondos, ETFs y criptoactivos.",
    )
    _ensure_child(
        bind,
        parent_id=inversiones_id,
        nombre="Aportaciones",
        aplica_a="ambos",
        orden=30,
        color=color,
        system_key="inversion_aportaciones",
        descripcion="Entregas de activos sin contraprestación en efectivo.",
    )
    # Duplicado deliberado: el saveback se paga en valor de activo y no debe
    # contar como ingreso fiat. Ingresos › Cashback queda para cashback fiat.
    _ensure_child(
        bind,
        parent_id=inversiones_id,
        nombre="Cashback",
        aplica_a="ingreso",
        orden=40,
        color=color,
        system_key="inversion_cashback",
        descripcion="Saveback o cashback entregado en valor de activo.",
    )

    if ingresos_id is not None:
        _move_beneficios_to_inversiones(
            bind, ingresos_id=ingresos_id, inversiones_id=inversiones_id
        )

    _flatten_tree(bind)
    _inherit_treatment(bind)
    _assert_two_levels(bind)


def downgrade() -> None:
    # La migración es de datos y no reconstruye la jerarquía de tres niveles.
    # Se deja documentada como no reversible para no borrar decisiones.
    pass
