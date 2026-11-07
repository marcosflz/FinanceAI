"""Tests del árbol de categorías y de la subcategoría por defecto."""

from __future__ import annotations

from decimal import Decimal

from src.db.lookups import get_categorias_nombres
from src.db.session import _session
from src.models import Categoria, Classification
from src.taxonomy import (
    category_by_path,
    category_choices_paths,
    ensure_default_child,
    resolve_assignable_category,
)

from .helpers import make_movement


def _root(session, name: str) -> Categoria:
    category = Categoria(
        nombre=name,
        aplica_a="gasto",
        tratamiento="normal",
        color="#6366f1",
        excluir_kpis=False,
        orden=100,
        activa=True,
    )
    session.add(category)
    session.flush()
    return category


def test_default_child_and_path_resolution(db):
    with _session() as s:
        root = _root(s, "Prueba raíz")
        other = _root(s, "Otra raíz")
        child = Categoria(
            nombre="Otros",
            parent_id=root.id,
            aplica_a="gasto",
            tratamiento="normal",
            color="#6366f1",
            excluir_kpis=False,
            orden=999,
            es_default=True,
            activa=True,
        )
        other_child = Categoria(
            nombre="Otros",
            parent_id=other.id,
            aplica_a="gasto",
            tratamiento="normal",
            color="#6366f1",
            excluir_kpis=False,
            orden=999,
            es_default=True,
            activa=True,
        )
        s.add_all([child, other_child])
        s.flush()

        assert resolve_assignable_category(s, root.id).id == child.id
        assert category_by_path(s, "Prueba raíz › Otros").id == child.id
        paths = category_choices_paths(s)
        assert "Prueba raíz › Otros" in paths
        assert "Otra raíz › Otros" in paths
        assert "Prueba raíz" not in paths

    classifier_paths = get_categorias_nombres()
    assert "Prueba raíz › Otros" in classifier_paths
    assert "Prueba raíz" not in classifier_paths


def test_ensure_default_child_moves_direct_classifications(db):
    movement_id, _ = make_movement(merchant="TIENDA")
    with _session() as s:
        root = _root(s, "Raíz con movimientos")
        old = Classification(
            movement_id=movement_id,
            categoria_id=root.id,
            origen="user",
            confianza=Decimal("1.0"),
            vigente=True,
        )
        s.add(old)
        s.flush()

        child = ensure_default_child(s, root, reassign_direct=True)
        s.flush()
        assert child.nombre == "Otros"
        assert child.es_default is True
        assert old.vigente is False
        current = (
            s.query(Classification)
            .filter_by(movement_id=movement_id, vigente=True)
            .one()
        )
        assert current.categoria_id == child.id
