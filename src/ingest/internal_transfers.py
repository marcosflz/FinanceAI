"""Enlace determinista de las dos patas de una transferencia interna.

Un traspaso entre cuentas propias aparece dos veces: una salida en la cuenta
origen y una entrada en la destino. No son duplicados; son dos movimientos que
deben quedar enlazados para que la trazabilidad y los saldos sean correctos.

El matcher solo enlaza cuando hay evidencia (IBAN de la otra cuenta, alias,
destino ya resuelto o recarga de tarjeta a otra cuenta). Si hay ambigüedad no
inventa un enlace: deja los movimientos para revisión.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import and_, or_

from ..db.session import _session
from ..models import (
    Account,
    Categoria,
    Classification,
    DedupCandidate,
    FinancialMovement,
    MovementLink,
    NormalizedEvent,
)
from ..taxonomy import DefaultSubcategoryMissing, resolve_assignable_category
from .accounts import (
    is_card_transaction,
    is_transfer_type,
    load_account_index,
    normalize_iban,
    resolve_accounts,
)

# Solo estos kinds pueden ser una pata de traspaso. Compras/ventas de
# inversión, dividendos, intereses o cashback nunca se reinterpretan como
# transferencia aunque coincida el importe con otro movimiento.
LINKABLE_KINDS = {"transferencia_interna", "ingreso", "gasto", "cambio_divisa"}

# Evidencias que no dependen solo del importe. ``same_currency_amount`` es
# débil: dos movimientos de signo contrario y mismo importe en cuentas propias
# distintas pueden ser casualidad (un Bizum recibido y una compra de 9,99 €).
_WEAK_EVIDENCE = {"same_currency_amount"}


@dataclass
class _Candidate:
    score: int
    date_diff: int
    a: FinancialMovement
    b: FinancialMovement
    evidence: str


def _is_revolut(account: Account | None) -> bool:
    if account is None:
        return False
    return (account.broker or "").lower() == "revolut" or "revolut" in (
        account.nombre or ""
    ).lower()


def _aliases(account: Account) -> list[str]:
    try:
        data = json.loads(account.alias_patrones or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip().upper() for item in data if str(item).strip()]


def _account_tokens(account: Account) -> set[str]:
    stop = {
        "CUENTA", "CORRIENTE", "DEFAULT", "BANCO", "BANK", "PROPIA",
        "OTRAS", "AHORRO", "CUENTAS",
    }
    tokens = {
        token
        for token in (account.nombre or "").upper().replace("-", " ").split()
        if len(token) >= 4 and token not in stop
    }
    for alias in _aliases(account):
        if "*" in alias or alias.startswith("RE:"):
            continue
        for token in alias.replace("-", " ").split():
            if len(token) >= 4 and token.isalpha() and token not in stop:
                tokens.add(token)
    return tokens


def _description_values(movement: FinancialMovement, event: NormalizedEvent | None) -> list[str]:
    values = [movement.merchant or ""]
    if event is not None:
        values.extend([event.description_raw or "", event.description_clean or ""])
        values.append(event.counterparty_name or "")
    return [value.upper() for value in values if value]


def _evidence(
    a: FinancialMovement,
    b: FinancialMovement,
    event_a: NormalizedEvent | None,
    event_b: NormalizedEvent | None,
    account_a: Account,
    account_b: Account,
) -> str | None:
    """Devuelve la evidencia que justifica el enlace, o None."""
    if a.account_destino_id == b.account_id or b.account_destino_id == a.account_id:
        return "account_destino"

    iban_a = normalize_iban(account_a.iban)
    iban_b = normalize_iban(account_b.iban)
    if iban_a and event_b is not None and normalize_iban(event_b.counterparty_iban) == iban_a:
        return "counterparty_iban_b"
    if iban_b and event_a is not None and normalize_iban(event_a.counterparty_iban) == iban_b:
        return "counterparty_iban_a"

    tokens_a = _account_tokens(account_a)
    tokens_b = _account_tokens(account_b)
    for value in _description_values(a, event_a):
        if any(token in value for token in tokens_b):
            return "description_b"
    for value in _description_values(b, event_b):
        if any(token in value for token in tokens_a):
            return "description_a"

    # Recarga de tarjeta: TR "Revolut**5844*" contra top-up de Revolut.
    if _is_revolut(account_b) and any("REVOLUT" in value for value in _description_values(a, event_a)):
        return "revolut_topup"
    if _is_revolut(account_a) and any("REVOLUT" in value for value in _description_values(b, event_b)):
        return "revolut_topup"

    return None


def _amount_evidence(
    a: FinancialMovement,
    b: FinancialMovement,
    event_a: NormalizedEvent | None,
    event_b: NormalizedEvent | None,
) -> str | None:
    if (a.currency or "EUR") == (b.currency or "EUR"):
        if abs(abs(Decimal(a.amount or 0)) - abs(Decimal(b.amount or 0))) <= Decimal("0.01"):
            return "same_currency_amount"
        return None
    for event, other in ((event_a, b), (event_b, a)):
        if event is None or event.original_amount is None:
            continue
        if (
            (event.original_currency or "").upper() == (other.currency or "EUR").upper()
            and abs(
                abs(Decimal(event.original_amount))
                - abs(Decimal(other.amount or 0))
            ) <= Decimal("0.01")
        ):
            return "original_currency_amount"
    return None


def _is_transfer_like(movement: FinancialMovement, event: NormalizedEvent | None) -> bool:
    if movement.kind in {"transferencia_interna", "cambio_divisa"}:
        return True
    broker_type = event.broker_type if event is not None else None
    return is_transfer_type(broker_type) or is_card_transaction(broker_type)


def _candidate_score(
    a: FinancialMovement,
    b: FinancialMovement,
    event_a: NormalizedEvent | None,
    event_b: NormalizedEvent | None,
    account_a: Account,
    account_b: Account,
) -> _Candidate | None:
    if a.id == b.id:
        return None
    if a.amount is None or b.amount is None:
        return None
    if a.amount == 0 or b.amount == 0:
        return None
    if a.kind not in LINKABLE_KINDS or b.kind not in LINKABLE_KINDS:
        return None
    if (a.amount > 0) == (b.amount > 0):
        return None
    if not a.value_date or not b.value_date:
        return None
    date_diff = abs((a.value_date - b.value_date).days)
    if date_diff > 3:
        return None

    amount_evidence = _amount_evidence(a, b, event_a, event_b)
    same_account = a.account_id == b.account_id
    if same_account and amount_evidence != "original_currency_amount":
        return None
    if amount_evidence is None:
        return None

    evidence = _evidence(a, b, event_a, event_b, account_a, account_b)
    if evidence is None:
        evidence = amount_evidence
    if evidence in _WEAK_EVIDENCE and not (
        _is_transfer_like(a, event_a) and _is_transfer_like(b, event_b)
    ):
        return None
    if (
        same_account
        and (a.currency or "EUR") == (b.currency or "EUR")
    ):
        return None

    score = {
        "account_destino": 6,
        "counterparty_iban_a": 6,
        "counterparty_iban_b": 6,
        "description_a": 4,
        "description_b": 4,
        "revolut_topup": 5,
        "same_currency_amount": 2,
        "original_currency_amount": 6,
    }[evidence]
    if date_diff == 0:
        score += 2
    elif date_diff == 1:
        score += 1
    return _Candidate(score=score, date_diff=date_diff, a=a, b=b, evidence=evidence)


def _target_category_id(session, source: Account, destination: Account) -> int | None:
    transfer = (
        session.query(Categoria)
        .filter(Categoria.nombre == "Transferencias", Categoria.parent_id.is_(None))
        .first()
    )
    if transfer is None:
        return None
    child_name = "Revolut" if _is_revolut(source) or _is_revolut(destination) else "Otros"
    child = (
        session.query(Categoria)
        .filter(Categoria.parent_id == transfer.id, Categoria.nombre == child_name)
        .first()
    )
    target = child or transfer
    try:
        resolved = resolve_assignable_category(session, target)
    except DefaultSubcategoryMissing:
        resolved = None
    return resolved.id if resolved is not None else target.id


def _ensure_classification(
    session,
    movement: FinancialMovement,
    target_id: int | None,
    *,
    explanation: str,
) -> None:
    if target_id is None:
        return
    current = (
        session.query(Classification)
        .filter(
            Classification.movement_id == movement.id,
            Classification.vigente == True,  # noqa: E712
        )
        .first()
    )
    if current is not None:
        if current.categoria_id == target_id:
            return
        if current.origen == "user":
            # No pisar una decisión humana.
            return
        current.vigente = False
    session.add(Classification(
        movement_id=movement.id,
        categoria_id=target_id,
        subtipo=None,
        origen="rule",
        confianza=Decimal("0.99"),
        explicacion=explanation,
        vigente=True,
    ))


def _remove_dedup_pair(session, a_id: int, b_id: int) -> None:
    session.query(DedupCandidate).filter(
        or_(
            and_(DedupCandidate.movement_a == a_id, DedupCandidate.movement_b == b_id),
            and_(DedupCandidate.movement_a == b_id, DedupCandidate.movement_b == a_id),
        )
    ).delete(synchronize_session=False)


def link_internal_transfers(session=None, *, dry_run: bool = False) -> dict:
    """Enlaza pares de transferencias internas. Idempotente.

    Devuelve contadores; con ``dry_run`` no escribe nada.
    """
    if session is None:
        with _session() as own_session:
            return _link_internal_transfers(own_session, dry_run=dry_run)
    return _link_internal_transfers(session, dry_run=dry_run)


def _link_internal_transfers(session, *, dry_run: bool) -> dict:
    stats = {
        "scanned": 0,
        "candidates": 0,
        "linked": 0,
        "already_linked": 0,
        "ambiguous": 0,
        "dry_run": dry_run,
    }
    accounts = {
        account.id: account
        for account in session.query(Account)
        .filter(Account.activo == True)  # noqa: E712
        .all()
        if account.es_propia
    }
    rows = (
        session.query(FinancialMovement, NormalizedEvent)
        .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
        .filter(
            FinancialMovement.account_id.isnot(None),
            FinancialMovement.amount.isnot(None),
            FinancialMovement.estado != "duplicado",
        )
        .order_by(FinancialMovement.value_date, FinancialMovement.id)
        .all()
    )
    stats["scanned"] = len(rows)

    buckets: dict[tuple[str, Decimal], list[tuple[FinancialMovement, NormalizedEvent | None]]] = defaultdict(list)
    for movement, event in rows:
        if movement.account_id not in accounts:
            continue
        amount = Decimal(str(movement.amount))
        if amount == 0:
            continue
        key = ((movement.currency or "EUR"), abs(amount).quantize(Decimal("0.01")))
        buckets[key].append((movement, event))

    candidates: list[_Candidate] = []
    seen_pairs: set[tuple[int, int]] = set()
    for items in buckets.values():
        if len(items) < 2:
            continue
        for index, (a, event_a) in enumerate(items):
            for b, event_b in items[index + 1:]:
                pair = (min(a.id, b.id), max(a.id, b.id))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                candidate = _candidate_score(
                    a, b, event_a, event_b,
                    accounts[a.account_id], accounts[b.account_id],
                )
                if candidate is not None:
                    candidates.append(candidate)

    # Las transferencias entre divisas pueden tener importes absolutos
    # distintos. Se indexan también por el importe original declarado en el
    # otro lado para encontrar pares EUR↔KRW/GBP sin inventar conversiones.
    aux_buckets: dict[tuple[str, Decimal], list[tuple[FinancialMovement, NormalizedEvent | None]]] = defaultdict(list)
    for movement, event in rows:
        if movement.account_id not in accounts or movement.amount in (None, 0):
            continue
        if event is not None and event.original_amount is not None:
            key = (
                (event.original_currency or movement.currency or "EUR"),
                abs(Decimal(str(event.original_amount))).quantize(Decimal("0.01")),
            )
            aux_buckets[key].append((movement, event))
    for key, aux_items in aux_buckets.items():
        direct_items = buckets.get(key, [])
        for a, event_a in aux_items:
            for b, event_b in direct_items:
                if a.id == b.id:
                    continue
                pair = (min(a.id, b.id), max(a.id, b.id))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                candidate = _candidate_score(
                    a, b, event_a, event_b,
                    accounts[a.account_id], accounts[b.account_id],
                )
                if candidate is not None:
                    candidates.append(candidate)

    # Un candidato débil (solo importe) solo se acepta si es el único posible
    # para ambas patas; si hay varios, se deja para revisión manual.
    involvement: dict[int, int] = defaultdict(int)
    for candidate in candidates:
        involvement[candidate.a.id] += 1
        involvement[candidate.b.id] += 1
    accepted: list[_Candidate] = []
    for candidate in candidates:
        if candidate.evidence in _WEAK_EVIDENCE and (
            involvement[candidate.a.id] > 1 or involvement[candidate.b.id] > 1
        ):
            stats["ambiguous"] += 1
            continue
        accepted.append(candidate)
    candidates = accepted

    stats["candidates"] = len(candidates)
    candidates.sort(key=lambda item: (-item.score, item.date_diff, item.a.id, item.b.id))

    used: set[int] = set()
    for candidate in candidates:
        a, b = candidate.a, candidate.b
        if a.id in used or b.id in used:
            continue
        existing = (
            session.query(MovementLink)
            .filter(
                MovementLink.link_type.in_([
                    "internal_transfer", "currency_exchange"
                ]),
                or_(
                    and_(MovementLink.movement_a == a.id, MovementLink.movement_b == b.id),
                    and_(MovementLink.movement_a == b.id, MovementLink.movement_b == a.id),
                ),
            )
            .first()
        )
        if existing is not None:
            used.update({a.id, b.id})
            stats["already_linked"] += 1
            continue

        account_a = accounts[a.account_id]
        account_b = accounts[b.account_id]
        is_exchange = a.account_id == b.account_id
        target_id = _target_category_id(session, account_a, account_b)
        if not dry_run:
            if is_exchange:
                a.kind = "cambio_divisa"
                b.kind = "cambio_divisa"
            else:
                a.kind = "transferencia_interna"
                b.kind = "transferencia_interna"
                a.account_destino_id = b.account_id
                b.account_destino_id = a.account_id
            if is_exchange:
                # Un cambio de divisa en la misma cuenta no es transferencia.
                a.estado = "aprobado"
                b.estado = "aprobado"
            # Los traspasos enlazados quedan propuestos, no aprobados: la
            # aprobación de transferencias es siempre manual.
            session.add(MovementLink(
                movement_a=min(a.id, b.id),
                movement_b=max(a.id, b.id),
                link_type="currency_exchange" if is_exchange else "internal_transfer",
                confianza="alta",
            ))
            _ensure_classification(
                session, a, target_id,
                explanation=f"Transferencia interna enlazada con movimiento #{b.id}",
            )
            _ensure_classification(
                session, b, target_id,
                explanation=f"Transferencia interna enlazada con movimiento #{a.id}",
            )
            _remove_dedup_pair(session, a.id, b.id)
            session.flush()
        used.update({a.id, b.id})
        stats["linked"] += 1

    return stats


def reapply_account_patterns(session) -> dict:
    """Re-evalúa IBAN/alias de cuentas propias sobre movimientos existentes.

    Solo convierte en ``transferencia_interna`` movimientos de tipo
    transferencia/tarjeta cuyo destino resuelve a otra cuenta propia. No
    cambia la cuenta del extracto, no degrada enlaces existentes y respeta las
    clasificaciones del usuario. Termina enlazando las dos patas.
    """
    stats = {"scanned": 0, "destinations_found": 0, "movements_updated": 0}
    index = load_account_index(session)
    by_id = {account.id: account for account in index.accounts}
    rows = (
        session.query(FinancialMovement, NormalizedEvent)
        .join(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
        .filter(
            FinancialMovement.account_id.isnot(None),
            FinancialMovement.account_destino_id.is_(None),
            FinancialMovement.kind.in_(["ingreso", "gasto", "transferencia_interna"]),
        )
        .all()
    )
    for movement, event in rows:
        stats["scanned"] += 1
        source = by_id.get(movement.account_id)
        if source is None:
            continue
        if not (is_transfer_type(event.broker_type) or is_card_transaction(event.broker_type)):
            continue
        _, destination = resolve_accounts(
            {
                "broker_type": event.broker_type,
                "counterparty_iban": event.counterparty_iban,
                "counterparty_name": event.counterparty_name,
                "description_raw": event.description_raw,
                "asset_name": event.asset_name,
            },
            source_account=source,
            index=index,
        )
        if destination is None:
            continue
        stats["destinations_found"] += 1
        current = (
            session.query(Classification)
            .filter(
                Classification.movement_id == movement.id,
                Classification.vigente == True,  # noqa: E712
            )
            .first()
        )
        if current is not None and current.origen == "user":
            continue
        movement.kind = "transferencia_interna"
        movement.account_destino_id = destination.id
        _ensure_classification(
            session,
            movement,
            _target_category_id(session, source, destination),
            explanation=f"Transferencia a cuenta propia: {destination.nombre}",
        )
        stats["movements_updated"] += 1
    session.flush()
    stats["links"] = _link_internal_transfers(session, dry_run=False)
    return stats
