"""v3_012_reclassify_investment_cashback — ajusta datos ya importados.

La migración ``v3_011`` creó las subcategorías nuevas, pero las clasificaciones
deterministas que ya existían seguían apuntando a ``Inversiones › Otros`` o a
``Ingresos › Cashback``. Esta migración versiona esas clasificaciones:

- ``inversion_compra`` → ``Inversiones › Compras``.
- ``aporte_activo`` → ``Inversiones › Aportaciones``.
- ``cashback`` → ``Inversiones › Cashback`` (saveback en activo).

Solo toca clasificaciones ``origen='broker'`` vigentes. No pisa decisiones
humanas ni reglas manuales.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v3_012_reclass_inv_cashback"
down_revision: Union[str, None] = "v3_011_two_level_taxonomy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _find_category(bind, nombre: str, parent_id: int | None) -> int | None:
    row = bind.execute(
        sa.text(
            "SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre) "
            "AND COALESCE(parent_id, 0)=COALESCE(:parent_id, 0)"
        ),
        {"nombre": nombre, "parent_id": parent_id},
    ).first()
    return int(row[0]) if row else None


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    if not {"categorias", "classifications", "financial_movements"} <= tables:
        return

    inversiones_id = _find_category(bind, "Inversiones", None)
    if inversiones_id is None:
        return
    compras_id = _find_category(bind, "Compras", inversiones_id)
    aportaciones_id = _find_category(bind, "Aportaciones", inversiones_id)
    cashback_id = _find_category(bind, "Cashback", inversiones_id)
    if compras_id is None or aportaciones_id is None or cashback_id is None:
        return

    rows = bind.execute(
        sa.text(
            "SELECT cl.id, cl.movement_id, cl.subtipo, cl.categoria_id, "
            "       c.nombre AS categoria, p.nombre AS raiz, m.kind "
            "FROM classifications cl "
            "JOIN financial_movements m ON m.id=cl.movement_id "
            "JOIN categorias c ON c.id=cl.categoria_id "
            "LEFT JOIN categorias p ON p.id=c.parent_id "
            "WHERE cl.vigente=true AND cl.origen='broker'"
        )
    ).fetchall()

    for row in rows:
        target_id = None
        target_name = None
        if (
            row.kind == "inversion_compra"
            and row.categoria == "Otros"
            and row.raiz == "Inversiones"
        ):
            target_id, target_name = compras_id, "Inversiones › Compras"
        elif (
            row.kind == "aporte_activo"
            and row.categoria == "Otros"
            and row.raiz == "Inversiones"
        ):
            target_id, target_name = aportaciones_id, "Inversiones › Aportaciones"
        elif row.kind == "cashback" and row.categoria_id != cashback_id:
            target_id, target_name = cashback_id, "Inversiones › Cashback"

        if target_id is None or target_id == row.categoria_id:
            continue

        bind.execute(
            sa.text(
                "UPDATE classifications SET vigente=false WHERE id=:id"
            ),
            {"id": row.id},
        )
        bind.execute(
            sa.text(
                "INSERT INTO classifications "
                "(movement_id, categoria_id, subtipo, origen, confianza, "
                " explicacion, vigente, creado_en) "
                "VALUES (:movement_id, :categoria_id, :subtipo, 'broker', 0.99, "
                "        :explicacion, true, CURRENT_TIMESTAMP)"
            ),
            {
                "movement_id": row.movement_id,
                "categoria_id": target_id,
                "subtipo": row.subtipo,
                "explicacion": (
                    "Reclasificación de taxonomía v3_012: "
                    f"{row.raiz} › {row.categoria} → {target_name}"
                ),
            },
        )


def downgrade() -> None:
    # No se revierten clasificaciones ya versionadas.
    pass
