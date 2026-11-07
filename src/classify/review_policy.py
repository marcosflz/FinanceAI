"""Política de revisión: las transferencias nunca se autoaprueban.

Una transferencia puede ser un traspaso entre cuentas propias, un pago a un
tercero o un Bizum. El sistema puede *proponer* categoría (p. ej.
``Transferencias › Revolut`` si la otra cuenta es propia), pero la aprobación
es siempre humana. Las domiciliaciones (``*_DIRECT_DEBIT_*``) y los cambios de
divisa no son transferencias a efectos de esta regla.

Las reglas definidas por el usuario (``origen='rule'``) y sus decisiones
(``origen='user'``) sí pueden aprobar: son una decisión explícita.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterable
from typing import TypeVar

from ..db.session import _session
from ..ingest.accounts import is_transfer_type
from ..models import Classification, FinancialMovement, NormalizedEvent

HUMAN_ORIGINS = {"user", "rule"}

T = TypeVar("T")


def is_transfer_movement(kind: str | None, broker_type: str | None) -> bool:
    return kind == "transferencia_interna" or is_transfer_type(broker_type)


def pending_transfer_ids(session) -> set[int]:
    """Movimientos pendientes que son transferencias."""
    rows = (
        session.query(FinancialMovement.id, FinancialMovement.kind, NormalizedEvent.broker_type)
        .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
        .filter(FinancialMovement.estado == "pendiente")
        .all()
    )
    return {
        movement_id
        for movement_id, kind, broker_type in rows
        if is_transfer_movement(kind, broker_type)
    }


def hold_transfers_for_review(session, movement_ids: Iterable[int]) -> int:
    """Devuelve a ``pendiente`` las transferencias aprobadas automáticamente."""
    ids = list(set(movement_ids))
    if not ids:
        return 0
    human = {
        movement_id
        for (movement_id,) in session.query(Classification.movement_id)
        .filter(
            Classification.movement_id.in_(ids),
            Classification.vigente == True,  # noqa: E712
            Classification.origen.in_(HUMAN_ORIGINS),
        )
        .all()
    }
    held = 0
    for movement in (
        session.query(FinancialMovement)
        .filter(FinancialMovement.id.in_(ids), FinancialMovement.estado == "aprobado")
        .all()
    ):
        if movement.id in human:
            continue
        movement.estado = "pendiente"
        held += 1
    return held


def keep_transfers_in_review(func: Callable[..., T]) -> Callable[..., T]:
    """Decorador: tras clasificar, las transferencias siguen en revisión."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _session() as s:
            before = pending_transfer_ids(s)
        result = func(*args, **kwargs)
        if before:
            with _session() as s:
                hold_transfers_for_review(s, before)
        return result

    return wrapper
