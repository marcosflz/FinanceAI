"""Utilidades de la taxonomía de dos niveles.

La taxonomía tiene como máximo una raíz y una subcategoría (dos niveles): una
categoría con hijas es una **agrupadora** y no se puede asignar directamente a
un movimiento. La asignación se resuelve contra su hija ``Otros``
(``es_default=True``) o, en su defecto, la primera hija activa. Las hojas sí
son asignables.

Los nombres pueden repetirse en raíces distintas; la identidad pública es el
``path`` completo (por ejemplo ``Compras › Alimentación``). El decisor y el
LLM reciben paths, no nombres sueltos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models import Categoria, Classification, ClassificationMemory


class DefaultSubcategoryMissing(RuntimeError):
    """Una agrupadora no tiene una subcategoría por defecto."""


@dataclass(frozen=True)
class CategoryChoice:
    id: int
    path: str
    nombre: str
    parent_id: int | None


# Dos niveles: raíz (0) y subcategoría (1). No se admiten nietos.
MAX_CATEGORY_DEPTH = 1


def category_root(session: Session, category: Categoria | int) -> Categoria | None:
    """Devuelve la raíz de una categoría (o ``None`` si no existe)."""
    current = (
        category
        if isinstance(category, Categoria)
        else session.query(Categoria).filter(Categoria.id == category).first()
    )
    guard = 0
    while current is not None and current.parent_id is not None and guard < 32:
        current = (
            session.query(Categoria)
            .filter(Categoria.id == current.parent_id)
            .first()
        )
        guard += 1
    return current


def assert_two_level_tree(session: Session) -> None:
    """Falla si algún nodo tiene un padre que a su vez tiene padre."""
    by_id = {category.id: category for category in session.query(Categoria).all()}
    invalid = [
        category
        for category in by_id.values()
        if category.parent_id is not None
        and (
            by_id.get(category.parent_id) is None
            or by_id[category.parent_id].parent_id is not None
        )
    ]
    if invalid:
        paths = ", ".join(
            f"{category.id}:{category.nombre}" for category in invalid
        )
        raise ValueError(f"Taxonomía con más de dos niveles: {paths}")


def category_paths(session: Session) -> dict[int, str]:
    """Devuelve ``{id: path}`` para todas las categorías."""
    categories = session.query(Categoria).all()
    by_id = {category.id: category for category in categories}
    cache: dict[int, str] = {}

    def build(category: Categoria, guard: int = 0) -> str:
        if category.id in cache:
            return cache[category.id]
        if guard > 32:
            return category.nombre
        parent = by_id.get(category.parent_id)
        value = (
            f"{build(parent, guard + 1)} › {category.nombre}"
            if parent is not None
            else category.nombre
        )
        cache[category.id] = value
        return value

    return {category.id: build(category) for category in categories}


def category_path(session: Session, category: Categoria | int) -> str:
    category_id = category if isinstance(category, int) else category.id
    return category_paths(session).get(category_id, "")


def _children(session: Session, category_id: int, *, active_only: bool = True) -> list[Categoria]:
    query = session.query(Categoria).filter(Categoria.parent_id == category_id)
    if active_only:
        query = query.filter(Categoria.activa.is_(True))
    return query.order_by(Categoria.orden, Categoria.nombre).all()


def default_child(
    session: Session, category: Categoria | int, *, active_only: bool = True
) -> Categoria | None:
    category_id = category if isinstance(category, int) else category.id
    children = _children(session, category_id, active_only=active_only)
    if not children:
        return None
    marked = [child for child in children if child.es_default]
    if marked:
        return marked[0]
    named = [child for child in children if child.nombre.strip().lower() == "otros"]
    return named[0] if named else None


def category_by_path(session: Session, path: str) -> Categoria | None:
    parts = [
        part.strip()
        for part in re.split(r"\s*(?:›|>|/)\s*", path)
        if part.strip()
    ]
    if not parts:
        return None
    parent_id: int | None = None
    current: Categoria | None = None
    for part in parts:
        query = session.query(Categoria).filter(
            func.lower(Categoria.nombre) == part.lower()
        )
        if parent_id is None:
            query = query.filter(Categoria.parent_id.is_(None))
        else:
            query = query.filter(Categoria.parent_id == parent_id)
        current = query.first()
        if current is None:
            return None
        parent_id = current.id
    return current


def resolve_category_reference(
    session: Session, reference: int | str | Categoria | None
) -> Categoria | None:
    if reference is None:
        return None
    if isinstance(reference, Categoria):
        return session.query(Categoria).filter(Categoria.id == reference.id).first()
    if isinstance(reference, int):
        return session.query(Categoria).filter(Categoria.id == reference).first()
    value = str(reference).strip()
    if not value:
        return None
    if "›" in value or ">" in value or "/" in value:
        return category_by_path(session, value)
    root = (
        session.query(Categoria)
        .filter(
            func.lower(Categoria.nombre) == value.lower(),
            Categoria.parent_id.is_(None),
        )
        .first()
    )
    if root is not None:
        return root
    matches = (
        session.query(Categoria)
        .filter(func.lower(Categoria.nombre) == value.lower())
        .limit(2)
        .all()
    )
    return matches[0] if len(matches) == 1 else None


def resolve_assignable_category(
    session: Session, reference: int | str | Categoria | None
) -> Categoria | None:
    """Resuelve una referencia al nodo hoja que debe recibir el movimiento.

    Con dos niveles, una subcategoría es siempre hoja; una raíz con hijas se
    resuelve a su hija por defecto y una raíz sin hijas se asigna directamente.
    """
    category = resolve_category_reference(session, reference)
    if category is None:
        return None
    if category.parent_id is not None:
        if _children(session, category.id, active_only=True):
            raise DefaultSubcategoryMissing(
                f"La subcategoría {category.nombre!r} no puede tener hijas"
            )
        return category
    children = _children(session, category.id, active_only=True)
    if not children:
        return category
    child = default_child(session, category, active_only=True)
    if child is None:
        raise DefaultSubcategoryMissing(
            f"La categoría {category.nombre!r} no tiene subcategoría por defecto"
        )
    return child


def category_choices(session: Session, *, active_only: bool = True) -> list[CategoryChoice]:
    """Hojas asignables, con su path completo."""
    categories = session.query(Categoria).all()
    paths = category_paths(session)
    by_parent: dict[int, list[Categoria]] = {}
    for category in categories:
        if category.parent_id is not None:
            by_parent.setdefault(category.parent_id, []).append(category)
    choices: list[CategoryChoice] = []
    for category in categories:
        if active_only and not category.activa:
            continue
        active_children = [
            child for child in by_parent.get(category.id, []) if child.activa
        ]
        if active_children:
            continue
        choices.append(
            CategoryChoice(
                id=category.id,
                path=paths.get(category.id, category.nombre),
                nombre=category.nombre,
                parent_id=category.parent_id,
            )
        )
    return sorted(choices, key=lambda item: item.path.lower())


def category_choices_paths(session: Session) -> list[str]:
    return [choice.path for choice in category_choices(session)]


def move_direct_classifications(
    session: Session,
    source: Categoria,
    target: Categoria,
    *,
    reason: str,
    origen: str = "user",
) -> int:
    """Mueve las clasificaciones vigentes directas de ``source`` a ``target``.

    Versiona la anterior (``vigente=False``), crea una nueva y actualiza la
    memoria de clasificación. Pensado para cuando una categoría pasa a tener
    subcategorías y sus movimientos deben caer en la subcategoría por defecto.
    """
    # Las sesiones tienen autoflush=False: sin este flush se volverían a mover
    # clasificaciones que el llamador acaba de versionar.
    session.flush()
    rows = (
        session.query(Classification)
        .filter(
            Classification.categoria_id == source.id,
            Classification.vigente.is_(True),
        )
        .all()
    )
    for old in rows:
        old.vigente = False
        session.add(
            Classification(
                movement_id=old.movement_id,
                categoria_id=target.id,
                subtipo=old.subtipo,
                origen=origen,
                confianza=Decimal("1.000"),
                explicacion=reason[:500],
                vigente=True,
            )
        )
    session.query(ClassificationMemory).filter(
        ClassificationMemory.categoria_id == source.id
    ).update(
        {ClassificationMemory.categoria_id: target.id},
        synchronize_session=False,
    )
    session.flush()
    return len(rows)


def ensure_default_child(
    session: Session,
    parent: Categoria,
    *,
    reassign_direct: bool = False,
) -> Categoria:
    """Garantiza que una raíz tenga su hija por defecto ``Otros``."""
    if parent.parent_id is not None:
        raise DefaultSubcategoryMissing(
            f"La subcategoría {parent.nombre!r} no puede tener hijas"
        )
    children = _children(session, parent.id, active_only=False)
    existing = next((child for child in children if child.es_default), None)
    if existing is None:
        existing = next(
            (
                child
                for child in children
                if child.nombre.strip().lower() == "otros"
            ),
            None,
        )
    if existing is not None:
        if not existing.activa or not existing.es_default:
            existing.activa = True
            existing.es_default = True
            session.flush()
        if reassign_direct:
            move_direct_classifications(
                session,
                parent,
                existing,
                reason=(
                    "Subcategoría por defecto: "
                    f"{category_path(session, parent)} → "
                    f"{category_path(session, existing)}"
                ),
            )
        return existing
    child = Categoria(
        nombre="Otros",
        parent_id=parent.id,
        aplica_a=parent.aplica_a,
        tratamiento=parent.tratamiento,
        color=parent.color or "#6366f1",
        excluir_kpis=bool(parent.excluir_kpis),
        orden=999,
        es_default=True,
        activa=True,
        descripcion="Categoría por defecto cuando no se especifica otra.",
    )
    session.add(child)
    session.flush()
    if reassign_direct:
        move_direct_classifications(
            session,
            parent,
            child,
            reason=(
                "Subcategoría por defecto: "
                f"{category_path(session, parent)} → "
                f"{category_path(session, child)}"
            ),
        )
    return child


__all__ = [
    "CategoryChoice",
    "DefaultSubcategoryMissing",
    "MAX_CATEGORY_DEPTH",
    "assert_two_level_tree",
    "category_by_path",
    "category_choices",
    "category_choices_paths",
    "category_path",
    "category_paths",
    "category_root",
    "default_child",
    "ensure_default_child",
    "move_direct_classifications",
    "resolve_assignable_category",
    "resolve_category_reference",
]
