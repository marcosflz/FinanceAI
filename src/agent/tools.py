"""Herramientas financieras del asistente.

Todas operan sobre la BD del tenant del contexto actual (``FunctionTool``
ejecuta las funciones síncronas con ``asyncio.to_thread``, que copia el
contexto). Reutilizan los handlers de la API para no duplicar reglas de
negocio: KPIs (``_apply_kpi_filters``), resolución raíz→hoja de categorías,
versionado de clasificaciones y memoria de comercios.

- ``READ_TOOLS``: se ejecutan sin preguntar.
- ``WRITE_TOOLS``: la política (:mod:`src.agent.policy`) las detiene para que
  el usuario las apruebe en una tarjeta.
- ``UI_TOOLS``: solo presentan un widget en el chat.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from pydantic.fields import FieldInfo

MAX_ROWS = 50


class ToolError(Exception):
    pass


def _invoke(fn: Callable[..., Any], **kwargs: Any) -> Any:
    """Llama a un handler FastAPI resolviendo los ``Query(...)`` por defecto."""
    target = inspect.unwrap(fn)
    for name, param in inspect.signature(target).parameters.items():
        if name in kwargs:
            continue
        if isinstance(param.default, FieldInfo):
            kwargs[name] = param.default.default if param.default.default is not ... else None
    return fn(**kwargs)


def _safe(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Convierte errores de negocio en ``{"error": …}`` para el modelo."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except HTTPException as exc:
            return {"error": str(exc.detail)}
        except (ToolError, ValueError) as exc:
            return {"error": str(exc)}

    return wrapper


def _parse_date(value: str | None, field: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ToolError(f"{field} debe tener formato AAAA-MM-DD") from exc


def _compact_movement(item: dict) -> dict:
    cl = item.get("classification") or item.get("clasificacion") or {}
    return {
        "id": item.get("id"),
        "date": item.get("value_date"),
        "amount": item.get("amount"),
        "currency": item.get("currency"),
        "merchant": item.get("merchant") or item.get("description"),
        "kind": item.get("kind"),
        "estado": item.get("estado"),
        "category": cl.get("categoria_path") or cl.get("categoria"),
        "account": (item.get("account") or {}).get("nombre"),
    }


# ── Lectura ──────────────────────────────────────────────────────────────────


@_safe
def get_overview(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Resumen de ingresos, gastos, ahorro y patrimonio en un periodo (fechas AAAA-MM-DD).

    Sin fechas usa todo el histórico. Respeta las exclusiones de KPIs: compras/ventas
    de inversión y transferencias internas no cuentan como gasto ni ingreso.
    """
    from ..api_v3_data import analytics_summary

    return analytics_summary(
        desde=_parse_date(date_from, "date_from"), hasta=_parse_date(date_to, "date_to")
    )


@_safe
def search_movements(
    text: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    estado: Literal["pendiente", "aprobado", "rechazado"] | None = None,
    kind: str | None = None,
    account_id: int | None = None,
    category_id: int | None = None,
    limit: int = Field(default=25, ge=1, le=MAX_ROWS),
) -> dict:
    """Busca movimientos por texto (comercio/descripción), fechas, estado, tipo, cuenta o categoría.

    Devuelve como mucho ``limit`` filas compactas ordenadas de más reciente a más antigua
    y el total de coincidencias.
    """
    from ..v2_api import list_movements

    result = _invoke(
        list_movements,
        q=text,
        desde=date_from,
        hasta=date_to,
        estado=estado,
        kind=kind,
        account_id=account_id,
        categoria_id=category_id,
        page=1,
        page_size=limit,
    )
    items = result.get("items", []) if isinstance(result, dict) else result
    return {
        "total": result.get("total", len(items)) if isinstance(result, dict) else len(items),
        "items": [_compact_movement(item) for item in items],
    }


@_safe
def get_movement(movement_id: int) -> dict:
    """Detalle completo de un movimiento: evento original, clasificación, fuentes y enlaces."""
    from ..v2_api import get_movement_detail

    return get_movement_detail(movement_id)


@_safe
def spending_by_category(date_from: str | None = None, date_to: str | None = None) -> dict:
    """Gastos e ingresos agregados por categoría en el periodo indicado (AAAA-MM-DD)."""
    from ..api_v3_data import analytics_by_category

    return _invoke(
        analytics_by_category,
        desde=_parse_date(date_from, "date_from"),
        hasta=_parse_date(date_to, "date_to"),
    )


@_safe
def cashflow(
    months: int = Field(default=6, ge=1, le=36),
    granularity: Literal["week", "month"] = "month",
) -> dict:
    """Serie de ingresos, gastos y neto de los últimos ``months`` meses."""
    from ..api_v3_data import analytics_cashflow

    return _invoke(analytics_cashflow, months=months, granularity=granularity)


@_safe
def top_merchants(limit: int = Field(default=15, ge=1, le=50)) -> dict:
    """Comercios con más gasto acumulado."""
    from ..api_v3_data import analytics_by_merchant

    return _invoke(analytics_by_merchant, limit=limit)


@_safe
def list_accounts() -> dict:
    """Cuentas del usuario con su tipo, moneda y saldo calculado."""
    from ..api_v3_data import list_accounts as handler

    return _invoke(handler)


@_safe
def get_portfolio() -> dict:
    """Cartera de inversión: posiciones, coste, valor, P&L y estado del coste."""
    from ..api_v3_data import portfolio_summary

    return portfolio_summary()


@_safe
def list_categories() -> dict:
    """Taxonomía de dos niveles (raíz › subcategoría) con su tratamiento en KPIs."""
    from ..db.session import _session
    from ..models import Categoria
    from ..taxonomy import category_paths

    with _session() as s:
        paths = category_paths(s)
        rows = s.query(Categoria).filter(Categoria.activa.is_(True)).all()
        return {
            "items": [
                {
                    "id": c.id,
                    "path": paths.get(c.id, c.nombre),
                    "tratamiento": getattr(c, "tratamiento", None),
                    "assignable": c.parent_id is not None
                    or not any(o.parent_id == c.id for o in rows),
                }
                for c in sorted(rows, key=lambda c: paths.get(c.id, c.nombre))
            ]
        }


@_safe
def list_rules() -> dict:
    """Reglas deterministas de clasificación (campo, operador, valor y categoría destino)."""
    from ..v2_api import list_rules as handler

    return {"items": handler()}


@_safe
def pending_review(limit: int = Field(default=25, ge=1, le=MAX_ROWS)) -> dict:
    """Movimientos pendientes de revisar, con su categoría propuesta."""
    return search_movements(estado="pendiente", limit=limit)


# ── Escritura (requieren aprobación) ─────────────────────────────────────────


class CategoryChange(BaseModel):
    movement_id: int
    category: str = Field(description="Ruta 'Raíz › Subcategoría', nombre o id de categoría")


@_safe
def recategorize_movements(changes: list[CategoryChange]) -> dict:
    """Cambia la categoría de uno o varios movimientos (máx. 50). Requiere aprobación.

    Cada cambio indica ``movement_id`` y ``category`` (ruta "Raíz › Subcategoría" o nombre).
    Una raíz se resuelve a su subcategoría por defecto. La corrección alimenta la memoria
    de comercios.
    """
    from ..db.session import _session
    from ..taxonomy import resolve_assignable_category
    from ..v2_api import V2MovementUpdate, update_movement

    if len(changes) > MAX_ROWS:
        raise ToolError(f"Como mucho {MAX_ROWS} cambios por llamada")
    applied, errors = [], []
    for change in changes:
        with _session() as s:
            category = resolve_assignable_category(s, _category_ref(change.category))
            category_id = category.id if category is not None else None
        if category_id is None:
            errors.append({"movement_id": change.movement_id, "error": "Categoría no encontrada"})
            continue
        try:
            update_movement(change.movement_id, V2MovementUpdate(categoria_id=category_id))
            applied.append(change.movement_id)
        except HTTPException as exc:
            errors.append({"movement_id": change.movement_id, "error": str(exc.detail)})
    return {"applied": applied, "errors": errors}


@_safe
def update_movement_fields(
    movement_id: int,
    merchant: str | None = None,
    note: str | None = None,
    estado: Literal["pendiente", "aprobado", "rechazado"] | None = None,
) -> dict:
    """Edita comercio, nota o estado (aprobar/rechazar) de un movimiento. Requiere aprobación."""
    from ..v2_api import V2MovementUpdate, update_movement

    fields: dict[str, Any] = {}
    if merchant is not None:
        fields["merchant"] = merchant
    if note is not None:
        fields["nota"] = note
    if estado is not None:
        fields["estado"] = estado
    if not fields:
        raise ToolError("No hay cambios")
    return _compact_movement(update_movement(movement_id, V2MovementUpdate(**fields)))


@_safe
def create_rule(
    field: Literal[
        "merchant",
        "description_clean",
        "counterparty_name",
        "counterparty_iban",
        "mcc_code",
        "broker_type",
        "kind",
    ],
    operator: Literal["contains", "equals", "regex"],
    value: str,
    category: str,
    priority: int = 100,
    auto_approve: bool = False,
) -> dict:
    """Crea una regla de clasificación determinista. Requiere aprobación.

    Ejemplo: field=merchant, operator=contains, value=MERCADONA, category="Alimentación › Supermercado".
    """
    from ..db.session import _session
    from ..taxonomy import resolve_assignable_category
    from ..v2_api import RuleCreate
    from ..v2_api import create_rule as handler

    with _session() as s:
        resolved = resolve_assignable_category(s, _category_ref(category))
        category_id = resolved.id if resolved is not None else None
    if category_id is None:
        raise ToolError("Categoría no encontrada")
    return handler(
        RuleCreate(
            prioridad=priority,
            campo=field,
            operador=operator,
            valor=value,
            set_categoria_id=category_id,
            auto_aprobar=auto_approve,
        )
    )


@_safe
def create_category(name: str, parent: str | None = None) -> dict:
    """Crea una categoría raíz o una subcategoría dentro de ``parent``. Requiere aprobación."""
    from ..api_v3_data import CategoryCreate, create_category_v3
    from ..db.session import _session
    from ..taxonomy import resolve_category_reference

    parent_id = None
    if parent:
        with _session() as s:
            root = resolve_category_reference(s, _category_ref(parent))
            parent_id = root.id if root is not None else None
        if parent_id is None:
            raise ToolError("Categoría padre no encontrada")
    return create_category_v3(CategoryCreate(nombre=name, parent_id=parent_id))


def _category_ref(value: str) -> int | str:
    value = (value or "").strip()
    return int(value) if value.isdigit() else value


# ── Presentación ─────────────────────────────────────────────────────────────


class ChartSeries(BaseModel):
    name: str
    values: list[float]


def show_chart(
    title: str,
    kind: Literal["bar", "line", "pie"],
    labels: list[str],
    series: list[ChartSeries],
) -> dict:
    """Muestra un gráfico en el chat. Úsalo tras consultar los datos con otras herramientas."""
    if not labels or not series:
        return {"error": "El gráfico necesita etiquetas y al menos una serie"}
    if any(len(item.values) != len(labels) for item in series):
        return {"error": "Cada serie debe tener tantos valores como etiquetas"}
    return {"shown": True, "points": len(labels)}


# ── Registro ─────────────────────────────────────────────────────────────────

READ_TOOLS: tuple[Callable[..., Any], ...] = (
    get_overview,
    search_movements,
    get_movement,
    spending_by_category,
    cashflow,
    top_merchants,
    list_accounts,
    get_portfolio,
    list_categories,
    list_rules,
    pending_review,
)
WRITE_TOOLS: tuple[Callable[..., Any], ...] = (
    recategorize_movements,
    update_movement_fields,
    create_rule,
    create_category,
)
UI_TOOLS: tuple[Callable[..., Any], ...] = (show_chart,)

ALL_TOOLS = READ_TOOLS + WRITE_TOOLS + UI_TOOLS
TOOLS_BY_NAME = {fn.__name__: fn for fn in ALL_TOOLS}
READ_NAMES = frozenset(fn.__name__ for fn in READ_TOOLS + UI_TOOLS)
WRITE_NAMES = frozenset(fn.__name__ for fn in WRITE_TOOLS)


def preview(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    """Datos para la tarjeta de aprobación (estado actual vs propuesto)."""
    if tool != "recategorize_movements":
        return {"kind": "simple"}
    from ..db.session import _session
    from ..taxonomy import category_paths, resolve_assignable_category
    from ..v2_api import get_movement_detail

    rows = []
    with _session() as s:
        paths = category_paths(s)
        targets = {}
        for change in args.get("changes", []):
            try:
                resolved = resolve_assignable_category(s, _category_ref(str(change.get("category", ""))))
            except Exception:
                resolved = None
            targets[change.get("movement_id")] = (
                paths.get(resolved.id, resolved.nombre) if resolved is not None else None
            )
    for movement_id, target in targets.items():
        try:
            item = _compact_movement(get_movement_detail(int(movement_id)))
        except Exception:
            item = {"id": movement_id}
        rows.append({**item, "new_category": target, "valid": target is not None})
    return {"kind": "recategorize", "rows": rows}


def default_period() -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=30)).isoformat(), today.isoformat()
