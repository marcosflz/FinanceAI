"""
Clasificación por reglas deterministas.

Ejecuta ``classification_rules`` contra movimientos pendientes. El motor
``RuleEngine`` carga y compila las reglas UNA vez (y opcionalmente los nombres
de categoría) para evaluar en memoria, sin abrir sesión ni hacer commit por
cada movimiento.

``run_rule_for_movement`` mantiene la API histórica: devuelve una
``Classification`` no persistida + un dict de acciones.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

from ..db.session import _session
from ..models import Classification
from ..taxonomy import category_paths


@dataclass(frozen=True)
class RuleData:
    """Regla compilada, independiente del ORM y de la sesión."""

    id: int
    prioridad: int
    campo: str
    operador: str
    valor: str
    set_categoria_id: int | None = None
    set_subtipo: str | None = None
    set_merchant: str | None = None
    set_kind: str | None = None
    auto_aprobar: bool = False


@dataclass(frozen=True)
class RuleHit:
    rule_id: int
    categoria_id: int | None
    categoria_nombre: str | None
    subtipo: str | None
    set_merchant: str | None
    set_kind: str | None
    auto_aprobar: bool
    explicacion: str

    @property
    def actions(self) -> dict:
        actions = {}
        if self.set_kind:
            actions["set_kind"] = self.set_kind
        if self.set_merchant:
            actions["set_merchant"] = self.set_merchant
        if self.auto_aprobar:
            actions["auto_aprobar"] = True
        return actions


class RuleEngine:
    """Motor de reglas precompilado y reutilizable."""

    def __init__(
        self,
        rules: Iterable[RuleData] = (),
        category_names: dict[int, str] | None = None,
    ):
        self.rules: list[RuleData] = sorted(
            rules, key=lambda r: (r.prioridad if r.prioridad is not None else 100, r.id)
        )
        self.category_names: dict[int, str] = category_names or {}
        self._compiled: list[tuple[RuleData, object]] = [
            (rule, self._compile(rule)) for rule in self.rules
        ]

    @classmethod
    def from_session(cls, session) -> RuleEngine:
        """Carga reglas activas y nombres de categoría desde una sesión."""
        rules = _load_rules(session)
        return cls(rules=rules, category_names=category_paths(session))

    def evaluate(
        self,
        merchant: str | None,
        kind: str | None,
        description_clean: str | None,
        mcc_code: str | None,
        broker_type: str | None,
        counterparty_name: str | None = None,
        counterparty_iban: str | None = None,
    ) -> RuleHit | None:
        """Devuelve la primera regla que casa (orden de prioridad)."""
        for rule, matcher in self._compiled:
            field_value = _get_field(
                merchant, kind, description_clean, mcc_code, broker_type,
                counterparty_name, counterparty_iban, rule.campo,
            )
            if field_value is None:
                continue
            if not _apply_matcher(matcher, field_value):
                continue

            category_name = self.category_names.get(rule.set_categoria_id)
            if rule.set_categoria_id and category_name is None:
                # Categoría borrada/inexistente: la regla no clasifica, pero
                # sus acciones (kind/merchant/autoaprobar) siguen aplicando.
                categoria_id = None
            else:
                categoria_id = rule.set_categoria_id

            if categoria_id:
                explicacion = (
                    f"Regla: {rule.campo} {rule.operador} {rule.valor} "
                    f"→ {category_name}"
                )
            else:
                explicacion = (
                    f"Regla: {rule.campo} {rule.operador} {rule.valor}"
                )

            return RuleHit(
                rule_id=rule.id,
                categoria_id=categoria_id,
                categoria_nombre=category_name,
                subtipo=rule.set_subtipo,
                set_merchant=rule.set_merchant,
                set_kind=rule.set_kind,
                auto_aprobar=bool(rule.auto_aprobar),
                explicacion=explicacion,
            )
        return None

    @staticmethod
    def _compile(rule: RuleData):
        operator = (rule.operador or "").lower()
        value = rule.valor or ""
        if operator == "regex":
            return re.compile(value, re.IGNORECASE)
        if operator == "mcc_in":
            return {v.strip() for v in value.split(",") if v.strip()}
        if operator in ("equals", "contains"):
            return value.upper()
        return None


def _load_rules(session) -> list[RuleData]:
    """Carga reglas tolerando esquemas antiguos sin ``auto_aprobar``."""
    bind = session.get_bind()
    try:
        inspector = sa_inspect(bind)
        if "classification_rules" not in inspector.get_table_names():
            return []
        columns = {c["name"] for c in inspector.get_columns("classification_rules")}
    except Exception:
        return []

    selectable = [
        "id", "prioridad", "campo", "operador", "valor",
        "set_categoria_id", "set_subtipo", "set_merchant", "set_kind",
    ]
    has_auto = "auto_aprobar" in columns
    if has_auto:
        selectable.append("auto_aprobar")

    sql = (
        f"SELECT {', '.join(selectable)} FROM classification_rules "
        "WHERE activa ORDER BY prioridad, id"
    )
    try:
        rows = session.execute(text(sql)).mappings().all()
    except Exception:
        return []

    return [
        RuleData(
            id=row["id"],
            prioridad=row["prioridad"],
            campo=row["campo"],
            operador=row["operador"],
            valor=row["valor"],
            set_categoria_id=row.get("set_categoria_id"),
            set_subtipo=row.get("set_subtipo"),
            set_merchant=row.get("set_merchant"),
            set_kind=row.get("set_kind"),
            auto_aprobar=bool(row.get("auto_aprobar")) if has_auto else False,
        )
        for row in rows
    ]


def _apply_matcher(matcher, field_value: str) -> bool:
    if matcher is None:
        return False
    if isinstance(matcher, re.Pattern):
        return bool(matcher.search(field_value))
    if isinstance(matcher, set):
        return field_value in matcher
    return matcher in field_value.upper()


def run_rule_for_movement(
    mov_id: int,
    merchant: str | None,
    kind: str,
    description_clean: str,
    mcc_code: str | None,
    broker_type: str | None,
    counterparty_name: str | None = None,
    counterparty_iban: str | None = None,
    engine: RuleEngine | None = None,
    rules: Iterable | None = None,
) -> tuple[Classification | None, dict]:
    """Evalúa reglas activas y devuelve ``(Classification, actions)``.

    ``engine`` permite reutilizar reglas ya cargadas. ``rules`` acepta tanto
    ``RuleData`` como ``ClassificationRule`` para compatibilidad.
    """
    if engine is None:
        if rules is not None:
            engine = RuleEngine(rules=[_coerce_rule(r) for r in rules])
        else:
            with _session() as s:
                engine = RuleEngine.from_session(s)

    hit = engine.evaluate(
        merchant=merchant,
        kind=kind,
        description_clean=description_clean,
        mcc_code=mcc_code,
        broker_type=broker_type,
        counterparty_name=counterparty_name,
        counterparty_iban=counterparty_iban,
    )
    if hit is None:
        return None, {}

    cl = None
    if hit.categoria_id:
        cl = Classification(
            movement_id=mov_id,
            categoria_id=hit.categoria_id,
            subtipo=hit.subtipo,
            origen="rule",
            confianza=Decimal("0.99"),
            explicacion=hit.explicacion,
            vigente=True,
        )
    return cl, hit.actions


def _coerce_rule(rule) -> RuleData:
    if isinstance(rule, RuleData):
        return rule
    return RuleData(
        id=rule.id,
        prioridad=rule.prioridad,
        campo=rule.campo,
        operador=rule.operador,
        valor=rule.valor,
        set_categoria_id=rule.set_categoria_id,
        set_subtipo=rule.set_subtipo,
        set_merchant=rule.set_merchant,
        set_kind=rule.set_kind,
        auto_aprobar=bool(getattr(rule, "auto_aprobar", False)),
    )


def _get_field(
    merchant: str | None, kind: str | None,
    description_clean: str | None, mcc_code: str | None,
    broker_type: str | None,
    counterparty_name: str | None, counterparty_iban: str | None,
    campo: str,
) -> str | None:
    if campo == "merchant":
        return merchant
    if campo == "kind":
        return kind
    if campo == "description_clean":
        return description_clean
    if campo == "mcc_code":
        return mcc_code
    if campo == "broker_type":
        return broker_type
    if campo == "counterparty_name":
        return counterparty_name
    if campo == "counterparty_iban":
        return counterparty_iban
    return None


def _match(operador: str, field: str, valor: str) -> bool:
    """Compatibilidad con consumidores externos de la API antigua."""
    return _apply_matcher(RuleEngine._compile(
        RuleData(
            id=0, prioridad=0, campo="", operador=operador, valor=valor,
        )
    ), field)
