"""v3_008_income_group — agrupa Nómina y Beneficios bajo Ingresos.

Crea la raíz ``Ingresos`` (con su ``Otros`` por defecto), renombra ``Salario``
a ``Nómina`` y cuelga tanto Nómina como Beneficios de Ingresos.

No mueve clasificaciones: las dos ramas no tenían movimientos directos en la
raíz. Las etiquetas y la jerarquía de Beneficios se conservan.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = "v3_008_income_group"
down_revision: Union[str, None] = "v3_007_default_subcategories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    if table not in _tables(bind):
        return set()
    return {column["name"] for column in inspect(bind).get_columns(table)}


def _find(bind, nombre: str, parent_id: int | None) -> int | None:
    row = bind.execute(
        sa.text(
            "SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre) "
            "AND COALESCE(parent_id, 0)=COALESCE(:parent_id, 0)"
        ),
        {"nombre": nombre, "parent_id": parent_id},
    ).first()
    return int(row[0]) if row else None


def _find_any(bind, nombre: str) -> int | None:
    row = bind.execute(
        sa.text("SELECT id FROM categorias WHERE lower(nombre)=lower(:nombre)"),
        {"nombre": nombre},
    ).first()
    return int(row[0]) if row else None


def _ensure_ingresos(bind) -> int:
    ingresos_id = _find(bind, "Ingresos", None)
    if ingresos_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                "VALUES ('Ingresos', NULL, 'ingreso', 'normal', '#22c55e', false, "
                "        10, 'ingresos', 'Ingresos agrupados: nómina y beneficios.', "
                "        false, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        ingresos_id = _find(bind, "Ingresos", None)
    if ingresos_id is None:
        raise RuntimeError("No se pudo crear la categoría Ingresos")
    bind.execute(
        sa.text(
            "UPDATE categorias SET aplica_a='ingreso', tratamiento='normal', "
            "color=COALESCE(color, '#22c55e'), excluir_kpis=false, activa=true, "
            "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
        ),
        {"id": ingresos_id},
    )

    otros_id = _find(bind, "Otros", ingresos_id)
    if otros_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                "VALUES ('Otros', :parent_id, 'ingreso', 'normal', '#22c55e', false, "
                "        999, NULL, 'Categoría por defecto cuando no se especifica otra.', "
                "        true, true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"parent_id": ingresos_id},
        )
    else:
        bind.execute(
            sa.text(
                "UPDATE categorias SET es_default=true, activa=true, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": otros_id},
        )
    return ingresos_id


def upgrade() -> None:
    bind = op.get_bind()
    if "categorias" not in _tables(bind):
        return

    ingresos_id = _ensure_ingresos(bind)
    salario_id = _find_any(bind, "Salario")
    nomina_id = _find(bind, "Nómina", ingresos_id)
    if salario_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET nombre='Nómina', parent_id=:parent_id, "
                "aplica_a='ingreso', tratamiento='normal', color='#22c55e', "
                "excluir_kpis=false, orden=10, system_key='nomina', activa=true, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": salario_id, "parent_id": ingresos_id},
        )
        nomina_id = salario_id
    elif nomina_id is None:
        bind.execute(
            sa.text(
                "INSERT INTO categorias "
                "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
                " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
                "VALUES ('Nómina', :parent_id, 'ingreso', 'normal', '#22c55e', false, "
                "        10, 'nomina', 'Sueldo, salario y pagas.', false, true, "
                "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"parent_id": ingresos_id},
        )
        nomina_id = _find(bind, "Nómina", ingresos_id)

    if nomina_id is not None:
        # Nómina es una hoja: el Otros que creó v3_007 ya no aplica.
        bind.execute(
            sa.text(
                "UPDATE categorias SET activa=false, es_default=false, "
                "actualizado_en=CURRENT_TIMESTAMP "
                "WHERE parent_id=:parent_id AND lower(nombre)='otros'"
            ),
            {"parent_id": nomina_id},
        )

    beneficios_id = _find(bind, "Beneficios", None)
    if beneficios_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET parent_id=:parent_id, orden=20, "
                "aplica_a='ingreso', tratamiento='normal', excluir_kpis=false, "
                "activa=true, actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": beneficios_id, "parent_id": ingresos_id},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "categorias" not in _tables(bind):
        return

    ingresos_id = _find(bind, "Ingresos", None)
    if ingresos_id is None:
        return

    nomina_id = _find(bind, "Nómina", ingresos_id)
    beneficios_id = _find(bind, "Beneficios", ingresos_id)
    if beneficios_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET parent_id=NULL, orden=30, "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {"id": beneficios_id},
        )
    if nomina_id is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET nombre='Salario', parent_id=NULL, "
                "orden=10, system_key='salario', actualizado_en=CURRENT_TIMESTAMP "
                "WHERE id=:id"
            ),
            {"id": nomina_id},
        )
        bind.execute(
            sa.text(
                "UPDATE categorias SET activa=true, es_default=true, "
                "actualizado_en=CURRENT_TIMESTAMP "
                "WHERE parent_id=:parent_id AND lower(nombre)='otros'"
            ),
            {"parent_id": nomina_id},
        )
    bind.execute(
        sa.text(
            "UPDATE categorias SET activa=false, actualizado_en=CURRENT_TIMESTAMP "
            "WHERE id=:id OR parent_id=:id"
        ),
        {"id": ingresos_id},
    )
