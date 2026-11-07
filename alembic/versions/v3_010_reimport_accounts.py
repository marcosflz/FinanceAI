"""v3_010_reimport_accounts — fecha de saldo inicial y transferencias Revolut/Bizum.

- Añade ``source_files.balance_start_date`` para poder inicializar una cuenta con
  la fecha del saldo de apertura del extracto.
- Crea ``Transferencias › Revolut`` y ``Transferencias › Bizum``.
- Archiva la raíz histórica ``Revolut`` y su ``Otros``.

No mueve clasificaciones: el reset de reimportación las reconstruye.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v3_010_reimport_accounts"
down_revision: Union[str, None] = "v3_009_income_children"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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


def _ensure_child(
    bind,
    *,
    parent_id: int,
    nombre: str,
    orden: int,
    color: str,
    system_key: str,
) -> int:
    existing = _find_category(bind, nombre, parent_id)
    if existing is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET aplica_a='ambos', tratamiento='transferencia', "
                "excluir_kpis=true, es_default=false, activa=true, orden=:orden, "
                "color=:color, system_key=COALESCE(system_key, :system_key), "
                "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
            ),
            {
                "id": existing,
                "orden": orden,
                "color": color,
                "system_key": system_key,
            },
        )
        return existing

    bind.execute(
        sa.text(
            "INSERT INTO categorias "
            "(nombre, parent_id, aplica_a, tratamiento, color, excluir_kpis, "
            " orden, system_key, descripcion, es_default, activa, creado_en, actualizado_en) "
            "VALUES (:nombre, :parent_id, 'ambos', 'transferencia', :color, true, "
            "        :orden, :system_key, :descripcion, false, true, "
            "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "nombre": nombre,
            "parent_id": parent_id,
            "color": color,
            "orden": orden,
            "system_key": system_key,
            "descripcion": (
                "Transferencias realizadas con Revolut."
                if nombre == "Revolut"
                else "Transferencias persona a persona por Bizum."
            ),
        },
    )
    child_id = _find_category(bind, nombre, parent_id)
    if child_id is None:
        raise RuntimeError(f"No se pudo crear la categoría {nombre!r}")
    return child_id


def upgrade() -> None:
    bind = op.get_bind()
    if "source_files" in _tables(bind):
        if "balance_start_date" not in _columns(bind, "source_files"):
            op.add_column(
                "source_files",
                sa.Column("balance_start_date", sa.Date(), nullable=True),
            )

    if "categorias" not in _tables(bind):
        return

    transfer_id = _find_category(bind, "Transferencias", None)
    if transfer_id is None:
        return

    _ensure_child(
        bind,
        parent_id=transfer_id,
        nombre="Revolut",
        orden=10,
        color="#00B4D8",
        system_key="transferencias_revolut",
    )
    _ensure_child(
        bind,
        parent_id=transfer_id,
        nombre="Bizum",
        orden=20,
        color="#F4A261",
        system_key="transferencias_bizum",
    )

    # La raíz histórica Revolut deja de ser asignable; sus movimientos se
    # reconstruyen en Transferencias › Revolut durante la reimportación.
    historica = _find_category(bind, "Revolut", None)
    if historica is not None:
        bind.execute(
            sa.text(
                "UPDATE categorias SET activa=false, es_default=false, "
                "actualizado_en=CURRENT_TIMESTAMP "
                "WHERE id=:id OR parent_id=:id"
            ),
            {"id": historica},
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "categorias" in _tables(bind):
        transfer_id = _find_category(bind, "Transferencias", None)
        if transfer_id is not None:
            for nombre in ("Revolut", "Bizum"):
                child_id = _find_category(bind, nombre, transfer_id)
                if child_id is None:
                    continue
                refs = 0
                for table, column in (
                    ("classifications", "categoria_id"),
                    ("classification_memory", "categoria_id"),
                    ("classification_rules", "set_categoria_id"),
                ):
                    if table not in _tables(bind):
                        continue
                    row = bind.execute(
                        sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column}=:id"),
                        {"id": child_id},
                    ).first()
                    refs += int(row[0]) if row else 0
                if refs:
                    bind.execute(
                        sa.text(
                            "UPDATE categorias SET activa=false, es_default=false, "
                            "actualizado_en=CURRENT_TIMESTAMP WHERE id=:id"
                        ),
                        {"id": child_id},
                    )
                else:
                    bind.execute(
                        sa.text("DELETE FROM categorias WHERE id=:id"),
                        {"id": child_id},
                    )
        historica = _find_category(bind, "Revolut", None)
        if historica is not None:
            bind.execute(
                sa.text(
                    "UPDATE categorias SET activa=true, actualizado_en=CURRENT_TIMESTAMP "
                    "WHERE id=:id OR parent_id=:id"
                ),
                {"id": historica},
            )

    if "source_files" in _tables(bind) and "balance_start_date" in _columns(
        bind, "source_files"
    ):
        op.drop_column("source_files", "balance_start_date")
