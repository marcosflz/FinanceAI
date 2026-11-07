"""Consultas de solo lectura compartidas por el clasificador y la config LLM.

Sustituye a las funciones que quedaban vivas del antiguo ``src/database.py``.
"""

from __future__ import annotations

from ..models import AppConfig, Subtipo
from .session import _DEFAULT_CATEGORIAS, _session


def get_all_app_config() -> dict:
    """Todas las claves de ``app_config`` como ``{key: value}``."""
    with _session() as s:
        return {row.key: row.value for row in s.query(AppConfig).all()}


def get_subtipo_descriptions() -> dict:
    """Descripciones de subtipos activos: ``{tipo: {nombre: descripcion}}``."""
    with _session() as s:
        rows = s.query(Subtipo).filter_by(activo=True).all()
        result: dict = {}
        for row in rows:
            result.setdefault(row.tipo, {})[row.nombre] = row.descripcion or ""
        return result


def get_categorias_nombres() -> list:
    """Paths de categorías hoja activas (``Compras › Otros``) para el LLM."""
    from ..taxonomy import category_choices_paths

    with _session() as s:
        choices = category_choices_paths(s)
        return choices if choices else list(_DEFAULT_CATEGORIAS)
