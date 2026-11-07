"""Precedentes compactos para la clasificación por lotes de Jev.

Jev no conserva contexto entre llamadas. El pipeline construye un bloque de
ejemplos aceptados por el usuario y lo inyecta en ``state.precedents``. El
bloque crece con los primeros lotes (10, 20, ...) y después se limita a los
ejemplos más similares al movimiento actual.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.orm import Session

from ..model_settings import MAX_REFERENCE_MAX, load_model_settings
from ..models import AppConfig, Classification, FinancialMovement, NormalizedEvent
from ..taxonomy import category_paths
from .redact import redact_text

DEFAULT_REFERENCE_LIMIT = 40
MAX_REFERENCE_CANDIDATES = 300


@dataclass(frozen=True)
class ReferenceExample:
    merchant: str | None
    description: str
    kind: str
    mcc_code: str | None
    broker_type: str | None
    counterparty: str | None
    amount_bucket: str
    categoria: str
    subtipo: str | None
    confidence: float


def _tokens(value: str | None) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", (value or "").lower())
        if token not in {"the", "and", "sl", "sa", "s.a", "de", "del", "la", "el"}
    }


def _bucket(amount: Decimal | None) -> str:
    if amount is None:
        return "sin_importe"
    value = abs(amount)
    sign = "ingreso" if amount > 0 else "gasto"
    if value < 10:
        band = "0-10"
    elif value < 50:
        band = "10-50"
    elif value < 200:
        band = "50-200"
    elif value < 1000:
        band = "200-1000"
    else:
        band = "1000+"
    return f"{sign}:{band}"


def _similarity(example: ReferenceExample, current: Mapping | None) -> float:
    if not current:
        return 0.0
    score = 0.0
    current_tokens = _tokens(str(current.get("merchant") or "")) | _tokens(
        str(current.get("descripcion") or "")
    )
    example_tokens = _tokens(example.merchant) | _tokens(example.description)
    if current_tokens and example_tokens:
        score += 3.0 * len(current_tokens & example_tokens) / len(
            current_tokens | example_tokens
        )
    if current.get("mcc_code") and current.get("mcc_code") == example.mcc_code:
        score += 2.0
    if current.get("kind") == example.kind:
        score += 1.0
    if current.get("broker_type") == example.broker_type:
        score += 0.5
    return score


def load_accepted_references(
    session: Session,
    *,
    literals: Iterable[str] | None = None,
    max_candidates: int = MAX_REFERENCE_CANDIDATES,
) -> list[ReferenceExample]:
    """Carga clasificaciones aceptadas por el usuario, sin autorreferencias."""
    if literals is None:
        row = session.query(AppConfig).filter_by(key="redact_literals").first()
        literals = [
            item.strip()
            for item in (row.value if row and row.value else "").splitlines()
            if item.strip() and len(item.strip()) >= 3
        ]
    redact_literals = list(literals or [])

    rows = (
        session.query(Classification, FinancialMovement, NormalizedEvent)
        .join(FinancialMovement, FinancialMovement.id == Classification.movement_id)
        .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
        .filter(
            Classification.origen == "user",
            Classification.vigente.is_(True),
            Classification.categoria_id.isnot(None),
            FinancialMovement.estado != "rechazado",
        )
        .order_by(Classification.creado_en.desc(), Classification.id.desc())
        .limit(max_candidates)
        .all()
    )

    categories = category_paths(session)
    examples: list[ReferenceExample] = []
    seen: set[tuple[str, str, str]] = set()
    for classification, movement, event in rows:
        category = categories.get(classification.categoria_id)
        if not category:
            continue
        merchant = redact_text(movement.merchant or "", redact_literals)[:160]
        description = redact_text(
            (event.description_clean if event else "") or "", redact_literals
        )[:220]
        key = (
            (merchant or description or "?").lower(),
            category,
            classification.subtipo or "",
        )
        if key in seen:
            continue
        seen.add(key)
        examples.append(
            ReferenceExample(
                merchant=merchant or None,
                description=description,
                kind=movement.kind or "gasto",
                mcc_code=event.mcc_code if event else None,
                broker_type=event.broker_type if event else None,
                counterparty=event.counterparty_name if event else None,
                amount_bucket=_bucket(movement.amount),
                categoria=category,
                subtipo=classification.subtipo,
                confidence=float(classification.confianza or 0),
            )
        )
    return examples


def select_references(
    examples: list[ReferenceExample],
    *,
    current: Mapping | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Selecciona ejemplos, priorizando similitud después del tope."""
    if limit is None:
        settings = load_model_settings()
        requested = settings.jev_reference_max
    else:
        requested = limit
    cap = max(0, min(requested, MAX_REFERENCE_MAX))
    if cap == 0:
        return []
    ranked = sorted(
        examples,
        key=lambda example: _similarity(example, current),
        reverse=True,
    )
    selected = ranked[:cap]
    # Orden estable y legible para el prompt: los más similares primero.
    return [
        {
            "merchant": example.merchant,
            "description": example.description,
            "kind": example.kind,
            "mcc": example.mcc_code,
            "broker_type": example.broker_type,
            "counterparty": example.counterparty,
            "amount_bucket": example.amount_bucket,
            "categoria": example.categoria,
            "subtipo": example.subtipo,
        }
        for example in selected
    ]


__all__ = [
    "DEFAULT_REFERENCE_LIMIT",
    "ReferenceExample",
    "load_accepted_references",
    "select_references",
]
