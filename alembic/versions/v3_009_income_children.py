"""v3_009_income_children — sube las ramas de Beneficios a Ingresos.

Deja ``Cashback``, ``Intereses``, ``Beneficios`` y ``Dividendos`` directamente
colgando de ``Ingresos`` y elimina la agrupadora intermedia ``Beneficios`` (que
no tenía clasificaciones propias). ``Ingresos › Otros`` sigue siendo el fallback.

No mueve clasificaciones: los hijos conservan sus IDs y sus movimientos.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "v3_009_income_children"
down_revision: Union[str, None] = "v3_008_income_group"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _find(bind, nombre: str, parent_id: int | None) -> int | None:
    row = bind.execute(
        sa.text(
            "SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre) "
            "AND COALESCE(parent_id, 0)=COALESCE(:parent_id, 0)"
        ),
        {"nombre": nombre, "parent_id": parent_id},
    ).first()
    return int(row[0]) if row else None


def _count_references(bind, category_id: int) -> int:
    total = 0
    for table, column in (
        ("classifications", "categoria_id"),
        ("classification_memory", "categoria_id"),
        ("classification_rules", "set_categoria_id"),
    ):
        if table not in _tables(bind):
            continue
        row = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column}=:id"),
            {"id": category_id},
        ).first()
        total += int(row[0]) if row else 0
    return total


def upgrade() -> None:
    bind = op.get_bind()
    if "categorias" not in _tables(bind):
        return

    ingresos_id = _find(bind, "Ingresos", None)
    if ingresos_id is None:
        return
    group_id = _find(bind, "Beneficios", ingresos_id)
    if group_id is None:
        return

    # Evita el choque de nombre con la hoja Beneficios al subirla.
    bind.execute(
        sa.text(
            "UPDATE categorias SET nombre='Beneficios (agrupadora temporal)', "
            "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
        ),
        {"id": group_id},
    )

    order_map = {
        "cashback": 20,
        "intereses": 30,
        "beneficios": 40,
        "dividendos": 50,
    }
    for nombre, orden in order_map.items():
        child_id = _find(bind, nombre, group_id)
        if child_id is not None:
            bind.execute(
                sa.text(
                    "UPDATE categorias SET parent_id=:parent_id, orden=:orden, "
                    "activa=true, actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": child_id, "parent_id": ingresos_id, "orden": orden},
            )

    # Cualquier hijo extra (no previsto) se sube también antes de borrar el grupo.
    bind.execute(
        sa.text(
            "UPDATE categorias SET parent_id=:parent_id, orden=100, "
            "actualizado_en=CURRENT_TIMESTAMP "
            "WHERE parent_id=:group_id AND lower(nombre) <> 'otros'"
        ),
        {"parent_id": ingresos_id, "group_id": group_id},
    )

    other_id = _find(bind, "Otros", group_id)
    if other_id is not None:
        if _count_references(bind, other_id):
            bind.execute(
                sa.text(
                    "UPDATE categorias SET parent_id=:parent_id, activa=false, "
                    "es_default=false, actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": other_id, "parent_id": ingresos_id},
            )
        else:
            bind.execute(sa.text("DELETE FROM categorias WHERE id=:id"), {"id": other_id})

    if _count_references(bind, group_id):
        # No debería ocurrir: el grupo no tenía clasificaciones propias.
        bind.execute(
            sa.text(
                "UPDATE categorias SET activa=false, es_default=false, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": group_id},
        )
    else:
        bind.execute(sa.text("DELETE FROM categorias WHERE id=:id"), {"id": group_id})


def downgrade() -> None:
    bind = op.get_bind()
    if "categorias" not in _tables(bind):
        return

    ingresos_id = _find(bind, "Ingresos", None)
    if ingresos_id is None:
        return
    existing_group = _find(bind, "Beneficios", ingresos_id)
    if existing_group is not None and _find(bind, "Cashback", existing_group) is not None:
        return  # ya está en el estado agrupado de v3_008

    # La hoja Beneficios (venta) ocupa el nombre que necesita la agrupadora.
    sale_id = _find(bind, "Beneficios", ingresos_id)
    if sale_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET nombre='Beneficios (venta temporal)', "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": sale_id},
        )

    bind.execute(
        sa.text(
            "INSERT INTO categorias "
            "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
            " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
            "VALUES ('Beneficios', :parent_id, 'ingreso', 'normal', '#10b981', false, "
            "        20, 'beneficios', "
            "        'Ingresos por cashback, intereses, dividendos y ventas.', "
            "        false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"parent_id": ingresos_id},
    )
    group_id = _find(bind, "Beneficios", ingresos_id)
    if group_id is None:
        return

    for nombre, orden in (
        ("Cashback", 10),
        ("Intereses", 20),
        ("Dividendos", 40),
    ):
        child_id = _find(bind, nombre, ingresos_id)
        if child_id is not None:
            bind.execute(
                sa.text(
                    "UPDATE categorias SET parent_id=:parent_id, orden=:orden, "
                    "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
                ),
                {"id": child_id, "parent_id": group_id, "orden": orden},
            )
    sale_id = _find(bind, "Beneficios (venta temporal)", ingresos_id)
    if sale_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET nombre='Beneficios', parent_id=:parent_id, "
                "orden=30, actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": sale_id, "parent_id": group_id},
        )

    other_id = _find(bind, "Otros", group_id)
    if other_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                "VALUES ('Otros', :parent_id, 'ingreso', 'normal', '#10b981', false, "
                "        999, NULL, 'Categoría por defecto cuando no se especifica otra.', "
                "        true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"parent_id": group_id},
        )
