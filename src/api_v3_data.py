"""Endpoints v3 de negocio: cuentas, analytics y cartera.

Se montan bajo ``/api/v3`` y comparten la autenticación/CSRF del resto de la
API v3. Las rutas de movimientos/importaciones/reglas se reutilizan desde los
routers v2 montados también en v3.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from .auth.dependencies import require_csrf, require_user
from .classify.pipeline import classify_batch
from .db.session import _session
from .fx import amount_to_eur
from .ingest.accounts import normalize_iban
from .ingest.agentic import AgenticExtractionError
from .ingest_service import discard_extraction_cache, enqueue_import, process_import
from .model_settings import load_model_settings, save_model_settings
from .portfolio_service import (
    AssetOperation,
    OpeningPosition,
    PortfolioSnapshot as PortfolioCalcSnapshot,
    SnapshotPosition as PortfolioCalcPosition,
    rebuild_portfolio,
)
from .taxonomy import (
    category_paths,
    ensure_default_child,
)
from .models import (
    Account,
    AccountBalanceSnapshot,
    AccountCurrencyBalance,
    Asset,
    AssetOpeningPosition,
    AssetTransaction,
    Categoria,
    Classification,
    ClassificationMemory,
    ClassificationRule,
    ClassificationRuleTag,
    DedupCandidate,
    Etiqueta,
    FinancialMovement,
    MovementLink,
    MovementSource,
    MovementTag,
    NormalizedEvent,
    PortfolioSnapshot,
    PortfolioSnapshotPosition,
    PositionSnapshot,
    RawRow,
    SourceFile,
    TagGroup,
)

router = APIRouter(
    prefix="/api/v3",
    tags=["v3-data"],
    dependencies=[Depends(require_user), Depends(require_csrf)],
)


def _money(value) -> float:
    return float(value or 0)


KPI_EXCLUDED_KINDS = {
    "transferencia_interna",
    "cambio_divisa",
    "inversion_compra",
    "inversion_venta",
    "aporte_activo",
}


# Kinds que suman en ingresos/gastos. Los importes son con signo: un
# reembolso (+) con kind gasto reduce el gasto en vez de aumentarlo.
INCOME_KINDS = {"ingreso", "dividendo", "interes", "cashback"}
EXPENSE_KINDS = {"gasto", "fee", "impuesto"}


def _kpi_split(kind: str | None, value) -> tuple[Decimal, Decimal]:
    """(ingreso, gasto) aportado por un movimiento; gasto en positivo."""
    amount = Decimal(str(value))
    if kind in INCOME_KINDS:
        return amount, Decimal("0")
    if kind in EXPENSE_KINDS:
        return Decimal("0"), -amount
    return Decimal("0"), Decimal("0")


def _excluded_movement_subquery(session):
    """Movimientos cuya categoría vigente los saca de KPIs.

    Se excluyen transferencias/inversiones y cualquier categoría marcada con
    ``excluir_kpis``. También se excluyen los kinds internos aunque no tengan
    clasificación, para que una importación a medias no infle los KPIs.
    """
    return (
        select(Classification.movement_id)
        .join(Categoria, Categoria.id == Classification.categoria_id)
        .where(
            Classification.vigente == True,  # noqa: E712
            or_(
                Categoria.tratamiento.in_(["transferencia", "inversion"]),
                Categoria.excluir_kpis == True,  # noqa: E712
            ),
        )
    )


# Movimiento confirmado como duplicado de otro: se conserva para auditoría
# y dedup de futuras importaciones, pero no cuenta en KPIs ni saldos.
DUPLICATE_STATE = "duplicado"


def _apply_kpi_filters(session, query):
    excluded = _excluded_movement_subquery(session)
    return query.filter(
        FinancialMovement.kind.notin_(KPI_EXCLUDED_KINDS),
        ~FinancialMovement.id.in_(excluded),
        FinancialMovement.estado != DUPLICATE_STATE,
    )


def _import_queue_mode() -> str:
    return os.getenv("IMPORT_QUEUE_MODE", "inline").strip().lower()


def _active_account_count(session) -> int:
    return (
        session.query(Account)
        .filter(Account.activo == True)  # noqa: E712
        .count()
    )


def _cashflow_key(value: date | None, granularity: str) -> str:
    if value is None:
        return "sin-fecha"
    if granularity == "day":
        return value.isoformat()
    if granularity == "week":
        return (value - timedelta(days=value.weekday())).isoformat()
    if granularity == "year":
        return value.strftime("%Y")
    return value.strftime("%Y-%m")


def _cashflow_bucket_starts(
    desde: date, hasta: date, granularity: str
) -> list[date]:
    """Fechas de inicio de cada cubo, incluidas las que no tienen movimientos.

    Así una serie diaria/semanal/mensual/anual mantiene el eje temporal
    continuo y no comprime los huecos sin actividad.
    """
    starts: list[date] = []
    if granularity == "day":
        current = desde
        while current <= hasta:
            starts.append(current)
            current += timedelta(days=1)
        return starts

    if granularity == "week":
        current = desde - timedelta(days=desde.weekday())
        last = hasta - timedelta(days=hasta.weekday())
        while current <= last:
            starts.append(current)
            current += timedelta(days=7)
        return starts

    if granularity == "year":
        for year in range(desde.year, hasta.year + 1):
            starts.append(date(year, 1, 1))
        return starts

    year, month = desde.year, desde.month
    while (year, month) <= (hasta.year, hasta.month):
        starts.append(date(year, month, 1))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return starts


def _period_label(desde: date | None, hasta: date | None) -> str:
    if desde and hasta:
        return f"{desde.strftime('%d/%m/%Y')} – {hasta.strftime('%d/%m/%Y')}"
    if desde:
        return f"Desde {desde.strftime('%d/%m/%Y')}"
    if hasta:
        return f"Hasta {hasta.strftime('%d/%m/%Y')}"
    return "Todo el histórico"


def _account_dict(account: Account, saldo: Decimal) -> dict:
    return {
        "id": account.id,
        "nombre": account.nombre,
        "iban": account.iban,
        "iban_masked": (
            f"{account.iban[:4]}…{account.iban[-4:]}"
            if account.iban and len(account.iban) >= 8
            else None
        ),
        "alias_patrones": json.loads(account.alias_patrones or "[]"),
        "tipo": account.tipo,
        "broker": account.broker,
        "es_propia": bool(account.es_propia),
        "moneda": account.moneda,
        "color": account.color,
        "activo": bool(account.activo),
        "balance_inicial": _money(account.balance_inicial),
        "balance_inicial_fecha": (
            account.balance_inicial_fecha.isoformat()
            if account.balance_inicial_fecha
            else None
        ),
        "saldo_calculado": _money(saldo),
        # Alias del contrato frontend v2.
        "balance": _money(saldo),
        "last_reconciled_at": None,
        "reconciliacion_diferencia": None,
    }


class AccountCreate(BaseModel):
    nombre: str
    iban: str | None = None
    alias_patrones: list[str] = Field(default_factory=list)
    tipo: str = "efectivo_externa"
    broker: str | None = None
    es_propia: bool = True
    moneda: str = "EUR"
    color: str = "#6366f1"
    activo: bool = True
    balance_inicial: Decimal = Decimal("0")
    balance_inicial_fecha: date | None = None


class AccountUpdate(BaseModel):
    nombre: str | None = None
    iban: str | None = None
    alias_patrones: list[str] | None = None
    tipo: str | None = None
    broker: str | None = None
    es_propia: bool | None = None
    moneda: str | None = None
    color: str | None = None
    activo: bool | None = None
    balance_inicial: Decimal | None = None
    balance_inicial_fecha: date | None = None


def _account_currency_balances(session) -> dict[int, dict[str, dict]]:
    """Saldos por cuenta y divisa, sin mezclar unidades monetarias."""
    accounts = session.query(Account).all()
    result: dict[int, dict[str, dict]] = defaultdict(dict)
    anchor_ids: set[tuple[int, str]] = set()
    for anchor in session.query(AccountCurrencyBalance).all():
        currency = (anchor.currency or "EUR").upper()
        initial = Decimal(str(anchor.balance_inicial or 0))
        initial_eur = anchor.balance_inicial_eur
        if initial_eur is None and currency == "EUR":
            initial_eur = initial
        result[anchor.account_id][currency] = {
            "currency": currency,
            "balance": initial,
            "balance_eur": Decimal(str(initial_eur or 0)),
            "balance_inicial": initial,
            "balance_inicial_eur": (
                Decimal(str(initial_eur)) if initial_eur is not None else None
            ),
            "balance_inicial_fecha": anchor.balance_inicial_fecha,
        }
        anchor_ids.add((anchor.account_id, currency))
    for account in accounts:
        currency = (account.moneda or "EUR").upper()
        if (account.id, currency) not in anchor_ids:
            initial = Decimal(str(account.balance_inicial or 0))
            result[account.id][currency] = {
                "currency": currency,
                "balance": initial,
                "balance_eur": initial if currency == "EUR" else Decimal("0"),
                "balance_inicial": initial,
                "balance_inicial_eur": initial if currency == "EUR" else None,
                "balance_inicial_fecha": account.balance_inicial_fecha,
            }

    for account_id, currency, total, total_eur in (
        session.query(
            FinancialMovement.account_id,
            FinancialMovement.currency,
            func.sum(FinancialMovement.amount),
            func.sum(FinancialMovement.amount_eur),
        )
        .join(Account, Account.id == FinancialMovement.account_id)
        .outerjoin(
            AccountCurrencyBalance,
            and_(
                AccountCurrencyBalance.account_id == FinancialMovement.account_id,
                AccountCurrencyBalance.currency == FinancialMovement.currency,
            ),
        )
        .filter(
            FinancialMovement.account_id.isnot(None),
            FinancialMovement.estado != DUPLICATE_STATE,
            or_(
                AccountCurrencyBalance.id.is_(None),
                AccountCurrencyBalance.balance_inicial_fecha.is_(None),
                FinancialMovement.value_date
                >= AccountCurrencyBalance.balance_inicial_fecha,
            ),
        )
        .group_by(FinancialMovement.account_id, FinancialMovement.currency)
        .all()
    ):
        code = (currency or "EUR").upper()
        row = result[int(account_id)].setdefault(code, {
            "currency": code,
            "balance": Decimal("0"),
            "balance_eur": Decimal("0"),
            "balance_inicial": Decimal("0"),
            "balance_inicial_eur": (
                Decimal("0") if code == "EUR" else None
            ),
            "balance_inicial_fecha": None,
        })
        row["balance"] += Decimal(str(total or 0))
        if total_eur is not None:
            row["balance_eur"] += Decimal(str(total_eur))
        elif code == "EUR":
            row["balance_eur"] += Decimal(str(total or 0))
    return result


def _account_balances(session) -> dict[int, Decimal]:
    """Saldo de cada cuenta a partir de sus propios extractos.

    Solo se suman movimientos cuyo ``account_id`` es la cuenta. La cuenta
    destino de una transferencia interna no recibe un abono artificial: su
    saldo se calculará cuando se importe su extracto. Así no se duplica el
    dinero al importar después la otra cuenta.
    """
    currency_balances = _account_currency_balances(session)
    return {
        account_id: sum(
            (row["balance_eur"] for row in rows.values()),
            Decimal("0"),
        )
        for account_id, rows in currency_balances.items()
    }


@router.get("/accounts")
def list_accounts(include_inactive: bool = Query(default=False)):
    with _session() as s:
        query = s.query(Account)
        if not include_inactive:
            query = query.filter(Account.activo == True)  # noqa: E712
        accounts = query.order_by(Account.id).all()
        balances = _account_balances(s)
        currency_balances = _account_currency_balances(s)
        snapshots = {
            row.account_id: row
            for row in s.query(AccountBalanceSnapshot)
            .order_by(AccountBalanceSnapshot.fecha.desc())
            .all()
        }
        result = []
        for account in accounts:
            item = _account_dict(account, balances.get(account.id, Decimal("0")))
            rows = currency_balances.get(account.id, {})
            item["balance_eur"] = _money(
                sum((row["balance_eur"] for row in rows.values()), Decimal("0"))
            )
            item["balances"] = [
                {
                    "currency": row["currency"],
                    "balance": _money(row["balance"]),
                    "balance_eur": _money(row["balance_eur"]),
                    "balance_inicial": _money(row["balance_inicial"]),
                    "balance_inicial_eur": (
                        _money(row["balance_inicial_eur"])
                        if row["balance_inicial_eur"] is not None
                        else None
                    ),
                    "balance_inicial_fecha": (
                        row["balance_inicial_fecha"].isoformat()
                        if row["balance_inicial_fecha"]
                        else None
                    ),
                }
                for row in sorted(rows.values(), key=lambda value: value["currency"])
            ]
            snap = snapshots.get(account.id)
            item["ultima_conciliacion"] = (
                {
                    "fecha": snap.fecha.isoformat(),
                    "saldo_declarado": _money(snap.saldo_declarado),
                    "saldo_calculado": _money(snap.saldo_calculado),
                    "diferencia": _money(snap.diferencia),
                }
                if snap
                else None
            )
            if snap:
                item["last_reconciled_at"] = snap.fecha.isoformat()
                item["reconciliacion_diferencia"] = _money(snap.diferencia)
            result.append(item)
        return {"items": result, "total": len(result)}


def _sync_primary_currency_anchor(session, account: Account) -> None:
    currency = (account.moneda or "EUR").upper()[:3]
    anchor = (
        session.query(AccountCurrencyBalance)
        .filter_by(account_id=account.id, currency=currency)
        .first()
    )
    if anchor is None:
        anchor = AccountCurrencyBalance(
            account_id=account.id,
            currency=currency,
        )
        session.add(anchor)
    anchor.balance_inicial = account.balance_inicial
    anchor.balance_inicial_fecha = account.balance_inicial_fecha
    if currency == "EUR":
        anchor.balance_inicial_eur = account.balance_inicial
    else:
        amount_eur, _, _, _ = amount_to_eur(
            account.balance_inicial,
            currency,
            account.balance_inicial_fecha or date.today(),
        )
        anchor.balance_inicial_eur = amount_eur
    session.flush()


def _create_account_in_session(session, body: AccountCreate) -> Account:
    tipo = body.tipo if body.tipo in {"broker_central", "efectivo_externa"} else "efectivo_externa"
    normalized = normalize_iban(body.iban) if body.iban else None
    existing = (
        session.query(Account).filter(Account.iban == normalized).first()
        if normalized
        else None
    )
    if existing is not None:
        if existing.activo:
            raise HTTPException(409, "Ya existe una cuenta con ese IBAN")
        existing.nombre = body.nombre.strip()
        existing.alias_patrones = json.dumps(body.alias_patrones, ensure_ascii=False)
        existing.tipo = tipo
        existing.broker = body.broker
        existing.es_propia = body.es_propia
        existing.moneda = body.moneda.upper()[:3]
        existing.color = body.color
        existing.balance_inicial = body.balance_inicial
        existing.balance_inicial_fecha = body.balance_inicial_fecha
        existing.activo = True
        session.flush()
        _sync_primary_currency_anchor(session, existing)
        return existing

    account = Account(
        nombre=body.nombre.strip(),
        iban=normalized,
        alias_patrones=json.dumps(body.alias_patrones, ensure_ascii=False),
        tipo=tipo,
        broker=body.broker,
        es_propia=body.es_propia,
        moneda=body.moneda.upper()[:3],
        color=body.color,
        activo=body.activo,
        balance_inicial=body.balance_inicial,
        balance_inicial_fecha=body.balance_inicial_fecha,
    )
    session.add(account)
    session.flush()
    _sync_primary_currency_anchor(session, account)
    return account


@router.post("/accounts", status_code=201)
def create_account(body: AccountCreate):
    with _session() as s:
        account = _create_account_in_session(s, body)
        balances = _account_balances(s)
        return _account_dict(account, balances.get(account.id, Decimal("0")))


@router.post("/accounts/{account_id}/reapply-patterns")
def reapply_patterns(account_id: int):
    """Re-evalúa IBAN/alias de cuentas propias sobre transferencias existentes.

    Nunca cambia ``account_id`` (la cuenta del extracto es un hecho), nunca
    degrada transferencias ya enlazadas y no pisa clasificaciones humanas.
    Antes delegaba en ``scripts/backfill_accounts.py``, que reasignaba todos
    los movimientos de todas las cuentas a la cuenta broker.
    """
    from .ingest.internal_transfers import reapply_account_patterns

    with _session() as s:
        if not s.query(Account).filter_by(id=account_id).first():
            raise HTTPException(404, "Cuenta no encontrada")
        stats = reapply_account_patterns(s)
    return {
        "matches": stats["destinations_found"] + stats["links"].get("linked", 0),
        "updated": stats["movements_updated"] + stats["links"].get("linked", 0),
        "stats": stats,
    }


@router.patch("/accounts/{account_id}")
def update_account(account_id: int, body: AccountUpdate):
    with _session() as s:
        account = s.query(Account).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(404, "Cuenta no encontrada")
        if body.nombre is not None:
            account.nombre = body.nombre.strip()
        if body.iban is not None:
            normalized = normalize_iban(body.iban) or None
            if normalized:
                conflict = (
                    s.query(Account)
                    .filter(Account.iban == normalized, Account.id != account.id)
                    .first()
                )
                if conflict is not None:
                    raise HTTPException(409, "Ese IBAN ya está asignado a otra cuenta")
            account.iban = normalized
        if body.alias_patrones is not None:
            account.alias_patrones = json.dumps(body.alias_patrones, ensure_ascii=False)
        if body.tipo is not None:
            account.tipo = body.tipo
        if body.broker is not None:
            account.broker = body.broker
        if body.es_propia is not None:
            account.es_propia = body.es_propia
        if body.moneda is not None:
            account.moneda = body.moneda.upper()[:3]
        if body.color is not None:
            account.color = body.color
        if body.activo is not None:
            account.activo = body.activo
        if body.balance_inicial is not None:
            account.balance_inicial = body.balance_inicial
        if "balance_inicial_fecha" in body.model_fields_set:
            account.balance_inicial_fecha = body.balance_inicial_fecha
        if {
            "balance_inicial",
            "balance_inicial_fecha",
            "moneda",
        } & body.model_fields_set:
            _sync_primary_currency_anchor(s, account)
        s.flush()
        balances = _account_balances(s)
        return _account_dict(account, balances.get(account.id, Decimal("0")))


@router.delete("/accounts/{account_id}")
def delete_account(account_id: int):
    """Elimina una cuenta o la archiva si tiene historial.

    No se borran movimientos ni extractos: si la cuenta está referenciada, se
    marca ``activo=False`` y desaparece de la lista por defecto. Es un borrado
    seguro y reversible desde ``PATCH /accounts/{id}`` con ``activo=true``.
    """
    with _session() as s:
        account = s.query(Account).filter_by(id=account_id).first()
        if not account:
            raise HTTPException(404, "Cuenta no encontrada")

        references = {
            "movimientos_origen": s.query(FinancialMovement)
            .filter(FinancialMovement.account_id == account_id)
            .count(),
            "movimientos_destino": s.query(FinancialMovement)
            .filter(FinancialMovement.account_destino_id == account_id)
            .count(),
            "extractos": s.query(SourceFile)
            .filter(SourceFile.account_id == account_id)
            .count(),
            "eventos": s.query(NormalizedEvent)
            .filter(NormalizedEvent.source_account_id == account_id)
            .count(),
            "conciliaciones": s.query(AccountBalanceSnapshot)
            .filter(AccountBalanceSnapshot.account_id == account_id)
            .count(),
        }
        has_references = any(references.values())
        if has_references:
            account.activo = False
            return {
                "deleted": True,
                "mode": "archived",
                "account_id": account.id,
                "references": references,
                "message": (
                    "La cuenta tiene historial; se ha archivado y se puede "
                    "restaurar sin perder movimientos."
                ),
            }

        s.delete(account)
        return {
            "deleted": True,
            "mode": "hard",
            "account_id": account_id,
            "references": references,
            "message": "Cuenta eliminada.",
        }


_BLOCKING_MATCH_STATUSES = {"new_account", "mismatch", "warning", "unsupported_product"}


def _norm_text(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _proposed_account_name(bank: str | None, product: str | None, filename: str | None) -> str:
    """Nombre legible para la cuenta propuesta sin repetir el banco.

    El producto puede faltar (PDF de Revolut); el nombre del fichero sirve de
    pista para distinguir corriente/conjunta.
    """
    bank = (bank or "").strip()
    product = (product or "").strip()
    hints = f"{_norm_text(product)} {_norm_text(filename)}"
    if "conjunt" in hints or "joint" in hints:
        suffix = "Cuenta Conjunta"
    elif any(word in hints for word in ("corriente", "current", "personal")):
        suffix = "Cuenta Corriente"
    elif product and _norm_text(product) != _norm_text(bank):
        if bank and _norm_text(bank) in _norm_text(product):
            return product
        suffix = product
    else:
        suffix = ""
    return " ".join(part for part in (bank, suffix) if part) or "Cuenta detectada"


def _broker_from_bank(bank: str | None) -> str | None:
    text = _norm_text(bank)
    if not text:
        return None
    if "revolut" in text:
        return "revolut"
    if "trade republic" in text:
        return "trade_republic"
    return text.replace(" ", "_")


def _pending_action(session, sf: SourceFile, meta: dict) -> dict | None:
    """Acción que el usuario debe aprobar antes de importar movimientos.

    El agente deja el extracto en ``needs_review`` sin crear movimientos cuando
    la cuenta es nueva o ambigua. Aquí se traduce a una acción con la cuenta
    propuesta para que la interfaz la muestre en la bandeja de aprobación.
    """
    if sf.status != "needs_review":
        return None
    match = meta.get("account_match") or {}
    status = match.get("status")
    reason = match.get("reason") or sf.error
    if status == "unsupported_product":
        return {"type": "unsupported_product", "reason": reason}
    blocking = (
        match.get("requires_confirmation") is True
        or status in _BLOCKING_MATCH_STATUSES
        or (match and sf.account_id is None)
    )
    if not blocking:
        has_movements = (
            session.query(MovementSource.movement_id)
            .filter(MovementSource.source_file_id == sf.id)
            .first()
        )
        if has_movements:
            return {"type": "review_movements", "reason": sf.error}
        return None

    detected = meta.get("detected") or {}
    bank = detected.get("bank")
    iban = normalize_iban(detected.get("account_iban"))
    broker = _broker_from_bank(bank)
    summary = meta.get("summary") or {}
    currency = str(summary.get("currency") or "EUR").upper()[:3]
    proposed = {
        "nombre": _proposed_account_name(bank, detected.get("product"), sf.filename),
        "iban": iban if len(iban) >= 15 and iban.isalnum() else None,
        "tipo": "broker_central" if broker == "trade_republic" else "efectivo_externa",
        "broker": broker,
        "moneda": currency,
        "balance_inicial": _money(sf.balance_start) if sf.balance_start is not None else None,
        "balance_inicial_fecha": (
            sf.balance_start_date.isoformat() if sf.balance_start_date else None
        ),
    }
    candidate_ids = [
        int(value)
        for value in (
            list(match.get("candidates") or [])
            + [match.get("selected_account_id"), match.get("detected_account_id")]
        )
        if value is not None
    ]
    candidates = []
    seen: set[int] = set()
    for account_id in candidate_ids:
        if account_id in seen:
            continue
        seen.add(account_id)
        account = session.query(Account).filter_by(id=account_id).first()
        if account is not None and account.activo:
            candidates.append({"id": account.id, "nombre": account.nombre, "iban": account.iban})
    return {
        "type": "create_account" if status == "new_account" else "confirm_account",
        "reason": reason,
        "proposed_account": proposed,
        "suggested_account_id": candidates[0]["id"] if candidates else None,
        "candidates": candidates,
    }


def _import_summary(session, sf: SourceFile) -> dict:
    uncategorized = (
        session.query(FinancialMovement)
        .join(MovementSource, MovementSource.movement_id == FinancialMovement.id)
        .filter(
            MovementSource.source_file_id == sf.id,
            ~session.query(Classification.id)
            .filter(
                Classification.movement_id == FinancialMovement.id,
                Classification.vigente == True,  # noqa: E712
                Classification.categoria_id.isnot(None),
            )
            .exists(),
        )
        .count()
    )
    account = session.query(Account).filter_by(id=sf.account_id).first() if sf.account_id else None
    mime = sf.mime_type
    if not mime:
        lower = (sf.filename or "").lower()
        mime = "application/pdf" if lower.endswith(".pdf") else "text/csv"
    status = sf.status
    if status in {"parsed_with_overlap", "legacy"}:
        status = "parsed"
    extraction_meta: dict = {}
    if sf.extraction_meta:
        try:
            extraction_meta = json.loads(sf.extraction_meta)
        except (TypeError, ValueError):
            extraction_meta = {}
    incidences = []
    for index, incidence in enumerate(extraction_meta.get("incidences") or [], start=1):
        if not isinstance(incidence, dict):
            continue
        item = dict(incidence)
        item.setdefault("id", index)
        incidences.append(item)
    return {
        "id": sf.id,
        "source": sf.source,
        "filename": sf.filename,
        "mime_type": mime,
        "file_hash": sf.file_hash,
        "period_start": sf.period_start.isoformat() if sf.period_start else None,
        "period_end": sf.period_end.isoformat() if sf.period_end else None,
        "row_count": sf.row_count or 0,
        "movement_new_count": sf.movement_new_count or 0,
        "movement_seen_count": sf.movement_seen_count or 0,
        "duplicate_count": 0,
        "uncategorized_count": uncategorized,
        "status": status,
        "account_id": sf.account_id,
        "account": (
            {"id": account.id, "nombre": account.nombre} if account else None
        ),
        "balance_start": _money(sf.balance_start) if sf.balance_start is not None else None,
        "balance_end": _money(sf.balance_end) if sf.balance_end is not None else None,
        "balance_start_date": (
            sf.balance_start_date.isoformat() if sf.balance_start_date else None
        ),
        "detected_account": extraction_meta.get("detected"),
        "account_match": extraction_meta.get("account_match"),
        "account_balance": extraction_meta.get("account_balance"),
        "internal_transfer_links": extraction_meta.get("internal_transfer_links"),
        "incidences": incidences,
        "parser_version": sf.parser_version,
        "error": sf.error,
        "reconciliation": extraction_meta.get("reconciliation"),
        "created_at": sf.subido_en.isoformat() if sf.subido_en else "",
        "queued_at": sf.queued_at.isoformat() if sf.queued_at else None,
        "started_at": sf.started_at.isoformat() if sf.started_at else None,
        "finished_at": sf.finished_at.isoformat() if sf.finished_at else None,
        "attempts": sf.attempts or 0,
        "parsed_at": sf.parseado_en.isoformat() if sf.parseado_en else None,
        "size_bytes": _file_size(sf.storage_path),
        "pending_action": _pending_action(session, sf, extraction_meta),
    }


def _file_size(path: str | None) -> int | None:
    if not path:
        return None
    try:
        return os.path.getsize(path)
    except OSError:
        return None


@router.get("/imports")
def list_imports_v3():
    with _session() as s:
        files = s.query(SourceFile).order_by(SourceFile.id.desc()).all()
        items = [_import_summary(s, sf) for sf in files]
        queued = sorted(
            (sf for sf in files if sf.status == "queued"),
            key=lambda sf: (sf.queued_at or datetime.min, sf.id),
        )
        positions = {sf.id: index for index, sf in enumerate(queued, start=1)}
        for item in items:
            item["queue_position"] = positions.get(item["id"])
        return {"items": items, "total": len(items), "next_cursor": None}


class ModelSettingsPatch(BaseModel):
    jev_model: str | None = Field(default=None, min_length=1, max_length=64)
    jev_reference_max: int | None = Field(default=None, ge=0, le=200)
    classification_batch_size: int | None = Field(default=None, ge=1, le=50)
    jev_max_calls_per_run: int | None = Field(default=None, ge=1, le=500)
    opencode_model: str | None = Field(default=None, min_length=1, max_length=64)
    opencode_fallback_models: list[str] | None = None
    ocr_lang: str | None = Field(default=None, min_length=1, max_length=32)
    ocr_dpi: int | None = Field(default=None, ge=100, le=400)
    auto_approve_threshold: float | None = Field(default=None, ge=0.0, le=1.0)


@router.get("/settings/models")
def get_models_settings_v3():
    return load_model_settings().to_public()


@router.patch("/settings/models")
def update_models_settings_v3(body: ModelSettingsPatch):
    values = body.model_dump(exclude_none=True)
    with _session() as s:
        return save_model_settings(s, values).to_public()


class ClassifyBatchRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=50)
    import_id: int | None = None
    movement_ids: list[int] | None = None


@router.post("/classify/batch")
def classify_batch_v3(body: ClassifyBatchRequest):
    """Clasifica un lote pequeño con Jev y devuelve sugerencias sin aprobar."""
    return classify_batch(
        limit=body.limit,
        import_id=body.import_id,
        movement_ids=body.movement_ids,
    )


def _find_existing_by_hash(session, file_hash: str) -> SourceFile | None:
    return session.query(SourceFile).filter(SourceFile.file_hash == file_hash).first()


@router.post("/imports", status_code=201)
async def upload_imports_v3(
    files: list[UploadFile] = File(...),
    force: bool = Query(default=False),
    account_id: int | None = Form(default=None),
):
    """Subida multipart multi-fichero; devuelve el primero y el resto en ``imports``.

    ``account_id`` indica a qué cuenta pertenece el extracto. Todos los
    movimientos del lote se asignan a esa cuenta y se usan para detectar
    transferencias internas contra las demás cuentas activas.
    """
    if not files:
        raise HTTPException(400, "No se ha enviado ningún fichero")

    # Sin account_id, cada fichero se resuelve de forma independiente por
    # IBAN/perfil aprobado. Solo una novedad o ambigüedad queda en revisión.
    if account_id is not None:
        with _session() as s:
            account = s.query(Account).filter_by(id=account_id).first()
            if account is None:
                raise HTTPException(404, "Cuenta no encontrada")
            if not account.activo:
                raise HTTPException(
                    400, "La cuenta está archivada; actívala antes de importar"
                )

    results = []
    for upload in files:
        content = await upload.read()
        if not content:
            raise HTTPException(400, f"Archivo vacío: {upload.filename}")
        file_hash = hashlib.sha256(content).hexdigest()
        suffix = os.path.splitext(upload.filename or "")[1] or ".csv"
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name
            if _import_queue_mode() == "worker":
                try:
                    source_file_id = enqueue_import(
                        tmp_path,
                        original_filename=upload.filename,
                        account_id=account_id,
                    )
                except ValueError as exc:
                    with _session() as s:
                        existing = _find_existing_by_hash(s, file_hash)
                        if existing is None:
                            raise
                        if account_id is not None and existing.account_id not in (
                            None,
                            account_id,
                        ):
                            raise HTTPException(409, str(exc)) from exc
                        item = _import_summary(s, existing)
                        item["_duplicate"] = True
                        results.append(item)
                        continue
                with _session() as s:
                    sf = s.query(SourceFile).filter_by(id=source_file_id).first()
                    if sf is None:
                        raise HTTPException(500, "La importación no quedó registrada")
                    item = _import_summary(s, sf)
                    item["_duplicate"] = False
                    results.append(item)
                continue

            try:
                result = process_import(
                    tmp_path,
                    force=force,
                    original_filename=upload.filename,
                    account_id=account_id,
                )
                duplicate = False
            except AgenticExtractionError as exc:
                raise HTTPException(422, str(exc)) from exc
            except ValueError as exc:
                # L0 idempotente: mismo contenido ya importado.
                with _session() as s:
                    existing = _find_existing_by_hash(s, file_hash)
                    if existing is None:
                        raise
                    if account_id is not None and existing.account_id not in (
                        None,
                        account_id,
                    ):
                        raise HTTPException(409, str(exc)) from exc
                    duplicate = True
                    item = _import_summary(s, existing)
                    item["_duplicate"] = True
                    results.append(item)
                    continue
            with _session() as s:
                sf = s.query(SourceFile).filter_by(id=result.source_file_id).first()
                if sf is None:
                    raise HTTPException(500, "La importación no quedó registrada")
                item = _import_summary(s, sf)
                item["_duplicate"] = duplicate
                results.append(item)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    first = results[0]
    return {
        "import": first,
        "duplicate": bool(first.pop("_duplicate", False)),
        "imports": [
            {k: v for k, v in item.items() if k != "_duplicate"}
            for item in results
        ],
    }


@router.post("/imports/{import_id}/reprocess")
def reprocess_import(import_id: int):
    """Re-procesa el fichero original si sigue en disco.

    No borra movimientos existentes: el dedup L1/L2 enlaza los ya vistos y
    crea solo los nuevos. Si el fichero no existe, devuelve 410.
    """
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, "Importación no encontrada")
        path = sf.storage_path
        if not path or not os.path.exists(path):
            raise HTTPException(410, "El fichero original ya no está disponible")
        discard_extraction_cache(sf.file_hash)
        if _import_queue_mode() == "worker":
            # Con worker no se bloquea la petición minutos: se reencola. Si el
            # import ya creó movimientos se rechaza para no duplicarlos.
            if sf.status == "processing":
                raise HTTPException(409, "El fichero se está procesando")
            has_movements = (
                s.query(MovementSource.movement_id)
                .filter(MovementSource.source_file_id == sf.id)
                .first()
            )
            if has_movements:
                raise HTTPException(
                    409, "El import ya creó movimientos; no se puede reprocesar"
                )
            sf.status = "queued"
            sf.queued_at = datetime.utcnow()
            sf.started_at = None
            sf.finished_at = None
            sf.parseado_en = None
            sf.error = None
            s.flush()
            return _import_summary(s, sf)
    try:
        process_import(
            path,
            force=True,
            original_filename=sf.filename,
            account_id=sf.account_id,
            source_file_id=sf.id,
        )
    except AgenticExtractionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        return _import_summary(s, sf)


@router.delete("/imports/{import_id}")
def delete_import(import_id: int):
    """Descarta un fichero subido que todavía no ha generado datos.

    Pensado para el gestor de ficheros: quitar un extracto en cola, en
    revisión o fallido. Si ya creó movimientos, operaciones o snapshots se
    rechaza (409) para no dejar datos huérfanos.
    """
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, "Importación no encontrada")
        if sf.status == "processing":
            raise HTTPException(409, "El fichero se está procesando; espera a que termine")
        references = {
            "movimientos": s.query(MovementSource).filter_by(source_file_id=sf.id).count(),
            "operaciones": s.query(AssetTransaction).filter_by(source_file_id=sf.id).count(),
            "snapshots": s.query(PortfolioSnapshot).filter_by(source_file_id=sf.id).count(),
            "conciliaciones": s.query(AccountBalanceSnapshot).filter_by(source_file_id=sf.id).count(),
            "aperturas": s.query(AssetOpeningPosition).filter_by(source_file_id=sf.id).count(),
        }
        if any(references.values()):
            raise HTTPException(
                409,
                "El fichero ya generó datos ("
                + ", ".join(f"{v} {k}" for k, v in references.items() if v)
                + "); no se puede descartar.",
            )
        storage_path = sf.storage_path
        file_hash = sf.file_hash
        raw_ids = select(RawRow.id).where(RawRow.source_file_id == sf.id)
        s.query(NormalizedEvent).filter(NormalizedEvent.raw_row_id.in_(raw_ids)).delete(
            synchronize_session=False
        )
        s.query(RawRow).filter_by(source_file_id=sf.id).delete(synchronize_session=False)
        s.delete(sf)
    discard_extraction_cache(file_hash)
    if storage_path:
        try:
            os.unlink(storage_path)
        except OSError:
            pass
    return {"deleted": True, "id": import_id}


class ImportAccountPatch(BaseModel):
    account_id: int


@router.patch("/imports/{import_id}/account")
def change_import_account(import_id: int, body: ImportAccountPatch):
    """Corrige la cuenta de un import bloqueado y lo devuelve a la cola.

    Solo se permite mientras no haya movimientos creados: si el extracto ya
    generó datos, cambiarlo de cuenta sería una operación destructiva y debe
    hacerse con una reimportación explícita.
    """
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, "Importación no encontrada")
        has_movements = (
            s.query(MovementSource)
            .filter(MovementSource.source_file_id == import_id)
            .count()
        )
        if has_movements:
            raise HTTPException(
                409,
                "El import ya tiene movimientos. No se puede cambiar de cuenta "
                "sin reimportarlo de forma explícita.",
            )
        account = s.query(Account).filter_by(id=body.account_id).first()
        if account is None:
            raise HTTPException(404, "Cuenta no encontrada")
        if not account.activo:
            raise HTTPException(400, "La cuenta está archivada")
        sf.account_id = account.id
        sf.status = "queued"
        sf.queued_at = datetime.utcnow()
        sf.started_at = None
        sf.finished_at = None
        sf.parseado_en = None
        sf.error = None
        # Si el extracto reveló un IBAN y la cuenta aún no lo tiene, se guarda
        # para que la próxima importación pueda casar automáticamente.
        meta = {}
        if sf.extraction_meta:
            try:
                meta = json.loads(sf.extraction_meta)
            except (TypeError, ValueError):
                meta = {}
        detected = (meta.get("detected") or {})
        detected_iban = normalize_iban(detected.get("account_iban"))
        if detected_iban and len(detected_iban) >= 15 and not account.iban:
            conflict = (
                s.query(Account)
                .filter(Account.iban == detected_iban, Account.id != account.id)
                .first()
            )
            if conflict is None:
                account.iban = detected_iban
        if (
            sf.balance_start is not None
            and sf.balance_start_date is not None
            and account.balance_inicial_fecha is None
            and (account.balance_inicial is None or Decimal(account.balance_inicial) == 0)
        ):
            account.balance_inicial = sf.balance_start
            account.balance_inicial_fecha = sf.balance_start_date
        _sync_primary_currency_anchor(s, account)
        s.flush()
        summary = _import_summary(s, sf)
    if _import_queue_mode() != "worker":
        try:
            process_import(
                sf.storage_path or "",
                force=True,
                original_filename=sf.filename,
                account_id=body.account_id,
                source_file_id=import_id,
                reuse_extraction=True,
            )
        except (AgenticExtractionError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=import_id).first()
            return _import_summary(s, sf)
    return summary


class ImportAccountConfirmation(BaseModel):
    action: Literal["create", "assign"]
    account_id: int | None = None
    account: AccountCreate | None = None


@router.post("/imports/{import_id}/confirm-account")
def confirm_import_account(import_id: int, body: ImportAccountConfirmation):
    """Confirma la cuenta y reanuda el extracto en una sola transacción."""
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, "Importación no encontrada")
        has_movements = (
            s.query(MovementSource)
            .filter(MovementSource.source_file_id == import_id)
            .count()
        )
        if has_movements:
            raise HTTPException(
                409,
                "El import ya tiene movimientos. No se puede cambiar de cuenta.",
            )

        if body.action == "create":
            if body.account is None:
                raise HTTPException(422, "Faltan los datos de la cuenta nueva")
            account = _create_account_in_session(s, body.account)
        else:
            if body.account_id is None:
                raise HTTPException(422, "Falta account_id")
            account = s.query(Account).filter_by(id=body.account_id).first()
            if account is None:
                raise HTTPException(404, "Cuenta no encontrada")
            if not account.activo:
                raise HTTPException(400, "La cuenta está archivada")

        sf.account_id = account.id
        sf.status = "queued"
        sf.queued_at = datetime.utcnow()
        sf.started_at = None
        sf.finished_at = None
        sf.parseado_en = None
        sf.error = None

        meta = {}
        if sf.extraction_meta:
            try:
                meta = json.loads(sf.extraction_meta)
            except (TypeError, ValueError):
                meta = {}
        detected = meta.get("detected") or {}
        detected_iban = normalize_iban(detected.get("account_iban"))
        if detected_iban and len(detected_iban) >= 15 and not account.iban:
            conflict = (
                s.query(Account)
                .filter(Account.iban == detected_iban, Account.id != account.id)
                .first()
            )
            if conflict is None:
                account.iban = detected_iban
        if (
            sf.balance_start is not None
            and sf.balance_start_date is not None
            and account.balance_inicial_fecha is None
            and (account.balance_inicial is None or Decimal(account.balance_inicial) == 0)
        ):
            account.balance_inicial = sf.balance_start
            account.balance_inicial_fecha = sf.balance_start_date
        _sync_primary_currency_anchor(s, account)
        s.flush()
        summary = _import_summary(s, sf)

    if _import_queue_mode() != "worker":
        try:
            process_import(
                sf.storage_path or "",
                force=True,
                original_filename=sf.filename,
                account_id=account.id,
                source_file_id=import_id,
                reuse_extraction=True,
            )
        except (AgenticExtractionError, ValueError) as exc:
            raise HTTPException(422, str(exc)) from exc
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=import_id).first()
            return _import_summary(s, sf)
    return summary


@router.get("/imports/{import_id}")
def get_import_detail(import_id: int):
    from .v2_api import _mov_to_dict

    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, "Importación no encontrada")
        summary = _import_summary(s, sf)

        movements = (
            s.query(FinancialMovement)
            .join(MovementSource, MovementSource.movement_id == FinancialMovement.id)
            .filter(MovementSource.source_file_id == import_id)
            .order_by(FinancialMovement.value_date, FinancialMovement.id)
            .all()
        )
        transactions = []
        for movement in movements:
            event = s.query(NormalizedEvent).filter_by(id=movement.event_id).first()
            cl = (
                s.query(Classification)
                .filter(
                    Classification.movement_id == movement.id,
                    Classification.vigente == True,  # noqa: E712
                )
                .first()
            )
            transactions.append(_mov_to_dict(movement, event, cl))

        raw_rows = []
        for row in (
            s.query(RawRow)
            .filter_by(source_file_id=import_id)
            .order_by(RawRow.row_index)
            .all()
        ):
            try:
                payload = json.loads(row.payload)
            except (TypeError, ValueError):
                payload = {"raw": row.payload}
            raw_rows.append({
                "id": row.id,
                "row_index": row.row_index,
                "payload": payload,
                "row_hash": row.row_hash,
            })

        # Reconciliación: primero la validación de saldo del extractor (PDF/
        # XLSX/CSV con columna de saldo); si no existe, la suma de filas vs BD.
        extraction_rec = summary.get("reconciliation") or {}
        reconciliation = None
        if extraction_rec:
            reconciliation = {
                "rows_ok": bool(extraction_rec.get("ok")),
                "balance_difference": extraction_rec.get("difference"),
                "total_amount": extraction_rec.get("actual_delta"),
            }
        else:
            try:
                from .imports_api import get_reconciliation

                rec = get_reconciliation(import_id)
                reconciliation = {
                    "rows_ok": abs(rec.get("difference", 0)) < 0.01,
                    "balance_difference": rec.get("difference"),
                    "total_amount": rec.get("db_total"),
                }
            except Exception:
                reconciliation = None

        summary.update({
            "transactions": transactions,
            "incidences": summary.get("incidences") or [],
            "raw_rows": raw_rows,
            "reconciliation_report": reconciliation,
        })
        return summary


# ── Taxonomía: categorías jerárquicas ──────────────────────────────────────

VALID_APLICA_A = {"gasto", "ingreso", "ambos"}
VALID_TRATAMIENTO = {"normal", "transferencia", "inversion"}
_CATEGORY_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class CategoryCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=255)
    parent_id: int | None = None
    aplica_a: Literal["gasto", "ingreso", "ambos"] = "gasto"
    tratamiento: Literal["normal", "transferencia", "inversion"] = "normal"
    color: str = "#6366f1"
    excluir_kpis: bool = False
    orden: int = 100
    system_key: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=500)
    activa: bool = True


class CategoryUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=255)
    parent_id: int | None = None
    aplica_a: Literal["gasto", "ingreso", "ambos"] | None = None
    tratamiento: Literal["normal", "transferencia", "inversion"] | None = None
    color: str | None = None
    excluir_kpis: bool | None = None
    orden: int | None = None
    system_key: str | None = Field(default=None, max_length=40)
    descripcion: str | None = Field(default=None, max_length=500)
    activa: bool | None = None


def _clean_color(value: str | None, fallback: str = "#6366f1") -> str:
    color = (value or fallback).strip()
    if not _CATEGORY_COLOR_RE.fullmatch(color):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Color hex inválido (#RRGGBB)")
    return color


def _normalise_name(value: str, *, label: str = "nombre") -> str:
    name = (value or "").strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"El {label} es obligatorio")
    return name


def _category_by_id(session, category_id: int) -> Categoria:
    category = session.query(Categoria).filter(Categoria.id == category_id).first()
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Categoría no encontrada")
    return category


def _category_name_exists(
    session,
    nombre: str,
    parent_id: int | None,
    *,
    exclude_id: int | None = None,
) -> Categoria | None:
    query = session.query(Categoria).filter(
        func.lower(Categoria.nombre) == nombre.lower(),
        func.coalesce(Categoria.parent_id, 0) == (parent_id or 0),
    )
    if exclude_id is not None:
        query = query.filter(Categoria.id != exclude_id)
    return query.first()


def _descendant_ids(session, category_id: int) -> set[int]:
    descendants: set[int] = set()
    stack = [category_id]
    while stack:
        current = stack.pop()
        children = (
            session.query(Categoria.id)
            .filter(Categoria.parent_id == current)
            .all()
        )
        for (child_id,) in children:
            if child_id not in descendants:
                descendants.add(child_id)
                stack.append(child_id)
    return descendants


def _validate_category_parent(
    session,
    *,
    parent_id: int | None,
    category_id: int | None,
    aplica_a: str,
) -> Categoria | None:
    if category_id is not None:
        if parent_id == category_id:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Una categoría no puede ser su propio padre"
            )
        if aplica_a != "ambos":
            for descendant_id in _descendant_ids(session, category_id):
                descendant = (
                    session.query(Categoria).filter(Categoria.id == descendant_id).first()
                )
                if descendant is not None and descendant.aplica_a != aplica_a:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        "La nueva tipología no es compatible con las subcategorías existentes",
                    )
    if parent_id is None:
        return None
    parent = session.query(Categoria).filter(Categoria.id == parent_id).first()
    if parent is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "La categoría padre no existe")
    if parent.parent_id is not None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Solo se permiten dos niveles: una raíz y sus subcategorías",
        )
    if category_id is not None and parent_id in _descendant_ids(session, category_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No se puede mover una categoría dentro de una de sus descendientes",
        )
    if category_id is not None and _descendant_ids(session, category_id):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Una categoría con subcategorías no puede convertirse en subcategoría",
        )
    if parent.aplica_a != "ambos" and aplica_a != parent.aplica_a:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "La tipología de la subcategoría debe coincidir con la del padre",
        )
    return parent


def _category_sort_key(category: Categoria) -> tuple[int, str]:
    return (category.orden or 100, (category.nombre or "").lower())


def _category_payloads(session, *, only_id: int | None = None) -> list[dict]:
    categories = session.query(Categoria).all()
    by_id = {category.id: category for category in categories}
    by_parent: dict[int | None, list[Categoria]] = defaultdict(list)
    for category in categories:
        by_parent[category.parent_id].append(category)

    ordered: list[Categoria] = []
    seen: set[int] = set()

    def walk(parent_id: int | None) -> None:
        for category in sorted(by_parent.get(parent_id, []), key=_category_sort_key):
            if category.id in seen:
                continue
            seen.add(category.id)
            ordered.append(category)
            walk(category.id)

    walk(None)
    # Categorías huérfanas o con un ciclo accidental: no las ocultamos.
    for category in sorted(categories, key=_category_sort_key):
        if category.id not in seen:
            ordered.append(category)

    direct_usage = dict(
        session.query(Classification.categoria_id, func.count(Classification.id))
        .filter(Classification.vigente.is_(True), Classification.categoria_id.isnot(None))
        .group_by(Classification.categoria_id)
        .all()
    )
    direct_rules = dict(
        session.query(ClassificationRule.set_categoria_id, func.count(ClassificationRule.id))
        .filter(ClassificationRule.set_categoria_id.isnot(None))
        .group_by(ClassificationRule.set_categoria_id)
        .all()
    )

    def subtree_total(category_id: int, counts: dict) -> int:
        total = int(counts.get(category_id, 0) or 0)
        for child_id in _descendant_ids(session, category_id):
            total += int(counts.get(child_id, 0) or 0)
        return total

    def path_for(category: Categoria) -> list[str]:
        names: list[str] = []
        current: Categoria | None = category
        guard = 0
        while current is not None and guard < 32:
            names.append(current.nombre)
            current = by_id.get(current.parent_id)
            guard += 1
        return list(reversed(names))

    active_children = {
        category.id: sum(
            1 for child in by_parent.get(category.id, []) if child.activa
        )
        for category in categories
    }
    items: list[dict] = []
    for category in ordered:
        if only_id is not None and category.id != only_id:
            continue
        path = path_for(category)
        parent = by_id.get(category.parent_id)
        root = parent or category
        naturaleza = (
            "transferencia"
            if category.tratamiento == "transferencia"
            else "inversion"
            if category.tratamiento == "inversion"
            else category.aplica_a
            if category.aplica_a in {"gasto", "ingreso"}
            else "otro"
        )
        items.append(
            {
                "id": category.id,
                "nombre": category.nombre,
                "parent_id": category.parent_id,
                "root_id": root.id,
                "root_nombre": root.nombre,
                "is_subcategory": parent is not None,
                "path": " › ".join(path),
                "depth": max(0, len(path) - 1),
                "aplica_a": category.aplica_a,
                "tratamiento": category.tratamiento,
                "naturaleza": naturaleza,
                "color": category.color or "#6366f1",
                "excluir_kpis": bool(category.excluir_kpis),
                "orden": category.orden or 100,
                "system_key": category.system_key,
                "es_default": bool(category.es_default),
                "descripcion": category.descripcion,
                "activa": bool(category.activa),
                "assignable": bool(category.activa)
                and active_children.get(category.id, 0) == 0,
                "usage_count": int(direct_usage.get(category.id, 0) or 0),
                "usage_total": subtree_total(category.id, direct_usage),
                "rule_count": int(direct_rules.get(category.id, 0) or 0),
                "rule_total": subtree_total(category.id, direct_rules),
                "children_count": len(by_parent.get(category.id, [])),
                "active_children_count": active_children.get(category.id, 0),
                "creado_en": category.creado_en.isoformat() if category.creado_en else None,
                "actualizado_en": (
                    category.actualizado_en.isoformat()
                    if category.actualizado_en
                    else None
                ),
            }
        )
    return items


@router.get("/categories")
def list_categories_v3():
    with _session() as s:
        items = _category_payloads(s)
        return {"items": items, "total": len(items)}


@router.post("/categories", status_code=status.HTTP_201_CREATED)
def create_category_v3(body: CategoryCreate):
    nombre = _normalise_name(body.nombre)
    color = _clean_color(body.color)
    aplica_a = body.aplica_a if body.aplica_a in VALID_APLICA_A else "gasto"
    tratamiento = (
        body.tratamiento
        if body.tratamiento in VALID_TRATAMIENTO
        else "normal"
    )
    excluir_kpis = bool(body.excluir_kpis or tratamiento in {"transferencia", "inversion"})
    with _session() as s:
        existing = _category_name_exists(s, nombre, body.parent_id)
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Ya existe una categoría con ese nombre en ese nivel",
            )
        parent = (
            s.query(Categoria).filter(Categoria.id == body.parent_id).first()
            if body.parent_id is not None
            else None
        )
        if parent is not None and "aplica_a" not in body.model_fields_set:
            aplica_a = parent.aplica_a
        parent = _validate_category_parent(
            s, parent_id=body.parent_id, category_id=None, aplica_a=aplica_a
        )
        if parent is not None:
            # Las subcategorías no tienen tratamiento propio: siempre heredan
            # el de su raíz, incluida la exclusión de KPIs.
            tratamiento = parent.tratamiento
            excluir_kpis = bool(
                parent.excluir_kpis
                or parent.tratamiento in {"transferencia", "inversion"}
            )
        if body.system_key:
            system_key = body.system_key.strip() or None
            if system_key and s.query(Categoria).filter_by(system_key=system_key).first():
                raise HTTPException(status.HTTP_409_CONFLICT, "system_key ya existe")
        else:
            system_key = None
        category = Categoria(
            nombre=nombre,
            parent_id=body.parent_id,
            aplica_a=aplica_a,
            tratamiento=tratamiento,
            color=color,
            excluir_kpis=excluir_kpis,
            orden=body.orden,
            system_key=system_key,
            descripcion=(body.descripcion or "").strip() or None,
            activa=bool(body.activa),
        )
        if parent is None and nombre.lower() == "otros":
            # Una raíz llamada Otros es legítima; su propia hija Otros será
            # la subcategoría por defecto.
            category.es_default = False
        s.add(category)
        try:
            s.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "Nombre o system_key duplicado") from exc
        if parent is None:
            ensure_default_child(s, category)
        else:
            if nombre.lower() == "otros" and category.es_default is False:
                existing_default = (
                    s.query(Categoria)
                    .filter(
                        Categoria.parent_id == parent.id,
                        Categoria.es_default.is_(True),
                        Categoria.activa.is_(True),
                    )
                    .first()
                )
                if existing_default is None:
                    category.es_default = True
            ensure_default_child(s, parent, reassign_direct=True)
        s.flush()
        payload = _category_payloads(s, only_id=category.id)[0]
        return payload


@router.patch("/categories/{category_id}")
def update_category_v3(category_id: int, body: CategoryUpdate):
    with _session() as s:
        category = _category_by_id(s, category_id)
        fields = body.model_fields_set
        parent_id = category.parent_id
        if "parent_id" in fields:
            parent_id = body.parent_id
        aplica_a = body.aplica_a if body.aplica_a is not None else category.aplica_a
        if body.nombre is not None:
            nombre = _normalise_name(body.nombre)
            duplicate = _category_name_exists(
                s, nombre, parent_id, exclude_id=category_id
            )
            if duplicate is not None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "Ya existe una categoría con ese nombre en ese nivel",
                )
            category.nombre = nombre
        if "parent_id" in fields or "aplica_a" in fields:
            _validate_category_parent(
                s, parent_id=parent_id, category_id=category_id, aplica_a=aplica_a
            )
        old_parent_id = category.parent_id
        if (
            "parent_id" in fields
            and category.es_default
            and parent_id != old_parent_id
        ):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La subcategoría por defecto no se puede mover de padre",
            )
        if "parent_id" in fields:
            category.parent_id = parent_id
        if "aplica_a" in fields:
            category.aplica_a = aplica_a
        if "parent_id" in fields and parent_id != old_parent_id:
            if parent_id is None:
                ensure_default_child(s, category, reassign_direct=True)
            else:
                new_parent = _category_by_id(s, parent_id)
                ensure_default_child(s, new_parent, reassign_direct=True)

        parent_after = (
            _category_by_id(s, category.parent_id)
            if category.parent_id is not None
            else None
        )
        if parent_after is not None:
            inherited_excluded = bool(
                parent_after.excluir_kpis
                or parent_after.tratamiento in {"transferencia", "inversion"}
            )
            if (
                body.tratamiento is not None
                and body.tratamiento != parent_after.tratamiento
            ):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "La subcategoría hereda el tratamiento de su categoría raíz",
                )
            if (
                "excluir_kpis" in fields
                and bool(body.excluir_kpis) != inherited_excluded
            ):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "La subcategoría hereda la exclusión de KPIs de su raíz",
                )
            category.tratamiento = parent_after.tratamiento
            category.excluir_kpis = inherited_excluded
        else:
            if body.tratamiento is not None:
                if body.tratamiento not in VALID_TRATAMIENTO:
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST, "Tratamiento inválido"
                    )
                category.tratamiento = body.tratamiento
                # Si se vuelve a tratamiento normal y el cliente no envía
                # explícitamente excluir_kpis, se incluye de nuevo en KPIs.
                # Antes quedaba el true heredado de transferencia/inversión y
                # parecía que el cambio no se guardaba.
                if (
                    body.tratamiento == "normal"
                    and "excluir_kpis" not in fields
                ):
                    category.excluir_kpis = False
            if body.excluir_kpis is not None:
                category.excluir_kpis = bool(body.excluir_kpis)
            if category.tratamiento in {"transferencia", "inversion"}:
                category.excluir_kpis = True

            # La raíz manda: cualquier cambio de tratamiento/exclusión se
            # propaga a sus subcategorías para que no haya fugas de KPIs.
            for child in (
                s.query(Categoria)
                .filter(Categoria.parent_id == category.id)
                .all()
            ):
                child.tratamiento = category.tratamiento
                child.excluir_kpis = bool(
                    category.excluir_kpis
                    or category.tratamiento in {"transferencia", "inversion"}
                )

        if body.color is not None:
            category.color = _clean_color(body.color)
        if body.orden is not None:
            category.orden = body.orden
        if "descripcion" in fields:
            category.descripcion = (body.descripcion or "").strip() or None
        if body.activa is not None:
            if not body.activa and category.es_default:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "La subcategoría por defecto no se puede archivar",
                )
            category.activa = bool(body.activa)
        if "system_key" in fields:
            system_key = (body.system_key or "").strip() or None
            if system_key:
                duplicate = (
                    s.query(Categoria)
                    .filter(Categoria.system_key == system_key, Categoria.id != category_id)
                    .first()
                )
                if duplicate is not None:
                    raise HTTPException(status.HTTP_409_CONFLICT, "system_key ya existe")
            category.system_key = system_key
        try:
            s.flush()
        except IntegrityError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, "Nombre o system_key duplicado") from exc
        return _category_payloads(s, only_id=category.id)[0]


@router.delete("/categories/{category_id}", status_code=status.HTTP_200_OK)
def delete_category_v3(category_id: int):
    with _session() as s:
        category = _category_by_id(s, category_id)
        if category.es_default:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La subcategoría por defecto no se puede borrar",
            )
        if category.system_key:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Las categorías de sistema no se pueden borrar; archívalas si hace falta",
            )
        if s.query(Categoria).filter(Categoria.parent_id == category_id).count():
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La categoría tiene subcategorías; muévelas o bórralas primero",
            )
        usage = (
            s.query(Classification)
            .filter(Classification.categoria_id == category_id)
            .count()
        )
        rules = (
            s.query(ClassificationRule)
            .filter(ClassificationRule.set_categoria_id == category_id)
            .count()
        )
        memory = (
            s.query(ClassificationMemory)
            .filter(ClassificationMemory.categoria_id == category_id)
            .count()
        )
        if usage or rules or memory:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La categoría está en uso; archívala en vez de borrarla",
            )
        s.delete(category)
        return {"ok": True, "deleted": category_id}


# ── Taxonomía: etiquetas y grupos ──────────────────────────────────────────

class TagGroupCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    color: str = "#6366f1"
    orden: int = 100


class TagGroupUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None
    orden: int | None = None


class TagCreate(BaseModel):
    nombre: str = Field(min_length=1, max_length=100)
    color: str = "#6366f1"
    descripcion: str | None = Field(default=None, max_length=500)
    group_id: int | None = None
    orden: int = 100
    activa: bool = True


class TagUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=100)
    color: str | None = None
    descripcion: str | None = Field(default=None, max_length=500)
    group_id: int | None = None
    orden: int | None = None
    activa: bool | None = None


def _tag_usage(session) -> dict[int, int]:
    return dict(
        session.query(MovementTag.tag_id, func.count(MovementTag.movement_id))
        .group_by(MovementTag.tag_id)
        .all()
    )


def _tag_rule_usage(session) -> dict[int, int]:
    return dict(
        session.query(ClassificationRuleTag.tag_id, func.count(ClassificationRuleTag.rule_id))
        .group_by(ClassificationRuleTag.tag_id)
        .all()
    )


def _tag_payload(tag: Etiqueta, usage: dict[int, int], rule_usage: dict[int, int]) -> dict:
    return {
        "id": tag.id,
        "nombre": tag.nombre,
        "color": tag.color or "#6366f1",
        "descripcion": tag.descripcion,
        "group_id": tag.group_id,
        "group_nombre": tag.group.nombre if tag.group else None,
        "orden": tag.orden or 100,
        "activa": bool(tag.activa),
        "usage_count": int(usage.get(tag.id, 0) or 0),
        "rule_count": int(rule_usage.get(tag.id, 0) or 0),
        "creado_en": tag.creado_en.isoformat() if tag.creado_en else None,
    }


def _tag_groups_payload(session) -> dict:
    usage = _tag_usage(session)
    rule_usage = _tag_rule_usage(session)
    groups = session.query(TagGroup).order_by(TagGroup.orden, TagGroup.nombre).all()
    tags = session.query(Etiqueta).order_by(Etiqueta.orden, Etiqueta.nombre).all()
    by_group: dict[int | None, list[Etiqueta]] = defaultdict(list)
    for tag in tags:
        by_group[tag.group_id].append(tag)
    items = []
    for group in groups:
        items.append(
            {
                "id": group.id,
                "nombre": group.nombre,
                "color": group.color,
                "orden": group.orden,
                "tags": [
                    _tag_payload(tag, usage, rule_usage)
                    for tag in by_group.get(group.id, [])
                ],
            }
        )
    return {
        "items": items,
        "ungrouped": [
            _tag_payload(tag, usage, rule_usage)
            for tag in by_group.get(None, [])
        ],
        "total": len(tags),
    }


def _tag_by_id(session, tag_id: int) -> Etiqueta:
    tag = session.query(Etiqueta).filter(Etiqueta.id == tag_id).first()
    if tag is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Etiqueta no encontrada")
    return tag


def _tag_group_by_id(session, group_id: int) -> TagGroup:
    group = session.query(TagGroup).filter(TagGroup.id == group_id).first()
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Grupo de etiquetas no encontrado")
    return group


@router.get("/tag-groups")
def list_tag_groups_v3():
    with _session() as s:
        return _tag_groups_payload(s)


@router.post("/tag-groups", status_code=status.HTTP_201_CREATED)
def create_tag_group_v3(body: TagGroupCreate):
    nombre = _normalise_name(body.nombre, label="nombre del grupo")
    color = _clean_color(body.color)
    with _session() as s:
        if s.query(TagGroup).filter(func.lower(TagGroup.nombre) == nombre.lower()).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un grupo con ese nombre")
        group = TagGroup(nombre=nombre, color=color, orden=body.orden)
        s.add(group)
        s.flush()
        return {"id": group.id, "nombre": group.nombre, "color": group.color, "orden": group.orden, "tags": []}


@router.patch("/tag-groups/{group_id}")
def update_tag_group_v3(group_id: int, body: TagGroupUpdate):
    with _session() as s:
        group = _tag_group_by_id(s, group_id)
        if body.nombre is not None:
            nombre = _normalise_name(body.nombre, label="nombre del grupo")
            duplicate = (
                s.query(TagGroup)
                .filter(func.lower(TagGroup.nombre) == nombre.lower(), TagGroup.id != group_id)
                .first()
            )
            if duplicate:
                raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe un grupo con ese nombre")
            group.nombre = nombre
        if body.color is not None:
            group.color = _clean_color(body.color)
        if body.orden is not None:
            group.orden = body.orden
        s.flush()
        return {"id": group.id, "nombre": group.nombre, "color": group.color, "orden": group.orden}


@router.delete("/tag-groups/{group_id}")
def delete_tag_group_v3(group_id: int):
    with _session() as s:
        group = _tag_group_by_id(s, group_id)
        s.query(Etiqueta).filter(Etiqueta.group_id == group_id).update(
            {Etiqueta.group_id: None}, synchronize_session=False
        )
        s.delete(group)
        return {"ok": True, "deleted": group_id}


@router.get("/tags")
def list_tags_v3(group_id: int | None = Query(default=None), q: str | None = Query(default=None)):
    with _session() as s:
        usage = _tag_usage(s)
        rule_usage = _tag_rule_usage(s)
        query = s.query(Etiqueta)
        if group_id is not None:
            query = query.filter(Etiqueta.group_id == group_id)
        if q:
            query = query.filter(Etiqueta.nombre.ilike(f"%{q.strip()}%"))
        tags = query.order_by(Etiqueta.orden, Etiqueta.nombre).all()
        items = [_tag_payload(tag, usage, rule_usage) for tag in tags]
        return {"items": items, "total": len(items)}


@router.post("/tags", status_code=status.HTTP_201_CREATED)
def create_tag_v3(body: TagCreate):
    nombre = _normalise_name(body.nombre, label="nombre de la etiqueta")
    color = _clean_color(body.color)
    with _session() as s:
        if s.query(Etiqueta).filter(func.lower(Etiqueta.nombre) == nombre.lower()).first():
            raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una etiqueta con ese nombre")
        if body.group_id is not None:
            _tag_group_by_id(s, body.group_id)
        tag = Etiqueta(
            nombre=nombre,
            color=color,
            descripcion=(body.descripcion or "").strip() or None,
            group_id=body.group_id,
            orden=body.orden,
            activa=bool(body.activa),
        )
        s.add(tag)
        s.flush()
        return _tag_payload(tag, {}, {})


@router.patch("/tags/{tag_id}")
def update_tag_v3(tag_id: int, body: TagUpdate):
    with _session() as s:
        tag = _tag_by_id(s, tag_id)
        fields = body.model_fields_set
        if body.nombre is not None:
            nombre = _normalise_name(body.nombre, label="nombre de la etiqueta")
            duplicate = (
                s.query(Etiqueta)
                .filter(func.lower(Etiqueta.nombre) == nombre.lower(), Etiqueta.id != tag_id)
                .first()
            )
            if duplicate:
                raise HTTPException(status.HTTP_409_CONFLICT, "Ya existe una etiqueta con ese nombre")
            tag.nombre = nombre
        if body.color is not None:
            tag.color = _clean_color(body.color)
        if "descripcion" in fields:
            tag.descripcion = (body.descripcion or "").strip() or None
        if "group_id" in fields:
            if body.group_id is None:
                tag.group_id = None
            else:
                _tag_group_by_id(s, body.group_id)
                tag.group_id = body.group_id
        if body.orden is not None:
            tag.orden = body.orden
        if body.activa is not None:
            tag.activa = bool(body.activa)
        s.flush()
        usage = _tag_usage(s)
        rule_usage = _tag_rule_usage(s)
        return _tag_payload(tag, usage, rule_usage)


@router.delete("/tags/{tag_id}")
def delete_tag_v3(tag_id: int):
    with _session() as s:
        tag = _tag_by_id(s, tag_id)
        usage = s.query(MovementTag).filter(MovementTag.tag_id == tag_id).count()
        rules = (
            s.query(ClassificationRuleTag)
            .filter(ClassificationRuleTag.tag_id == tag_id)
            .count()
        )
        if usage or rules:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "La etiqueta está en uso; archívala en vez de borrarla",
            )
        s.delete(tag)
        return {"ok": True, "deleted": tag_id}


@router.get("/classification-rules")
def list_rules_v3():
    with _session() as s:
        rules = s.query(ClassificationRule).order_by(ClassificationRule.prioridad).all()
        categories = category_paths(s)
        items = []
        for rule in rules:
            items.append({
                "id": rule.id,
                "nombre": getattr(rule, "nombre", None),
                "descripcion": getattr(rule, "descripcion", None),
                "prioridad": rule.prioridad,
                "campo": rule.campo,
                "operador": rule.operador,
                "valor": rule.valor,
                "set_categoria": categories.get(rule.set_categoria_id),
                "set_categoria_id": rule.set_categoria_id,
                "set_subtipo": rule.set_subtipo,
                "activa": bool(rule.activa),
                "auto_aprobar": bool(getattr(rule, "auto_aprobar", False)),
                "hit_count": getattr(rule, "hit_count", 0) or 0,
                "last_hit_at": (
                    rule.last_hit_at.isoformat()
                    if getattr(rule, "last_hit_at", None)
                    else None
                ),
                "creado_en": rule.creado_en.isoformat() if rule.creado_en else "",
            })
        return {"items": items, "total": len(items)}


@router.get("/dedup-candidates")
def list_dedup_candidates():
    from .v2_api import _mov_to_dict

    with _session() as s:
        candidates = (
            s.query(DedupCandidate)
            .filter(DedupCandidate.estado == "pendiente")
            .order_by(DedupCandidate.score.desc())
            .all()
        )
        items = []
        for candidate in candidates:
            movements = []
            for movement_id in (candidate.movement_a, candidate.movement_b):
                movement = s.query(FinancialMovement).filter_by(id=movement_id).first()
                if not movement:
                    movements.append(None)
                    continue
                event = s.query(NormalizedEvent).filter_by(id=movement.event_id).first()
                cl = (
                    s.query(Classification)
                    .filter(
                        Classification.movement_id == movement.id,
                        Classification.vigente == True,  # noqa: E712
                    )
                    .first()
                )
                movements.append(_mov_to_dict(movement, event, cl))
            items.append({
                "id": candidate.id,
                "movement_a": movements[0],
                "movement_b": movements[1],
                "score": float(candidate.score or 0),
                "motivo": candidate.motivo,
                "estado": candidate.estado,
                "created_at": (
                    candidate.resuelto_en.isoformat()
                    if candidate.resuelto_en
                    else ""
                ),
            })
        return {"items": items, "total": len(items)}


class DedupResolution(BaseModel):
    resolution: str


@router.post("/dedup-candidates/{candidate_id}/resolve")
def resolve_dedup_candidate(candidate_id: int, body: DedupResolution):
    if body.resolution not in {"mismo", "distinto"}:
        raise HTTPException(422, "resolution debe ser 'mismo' o 'distinto'")
    with _session() as s:
        candidate = s.query(DedupCandidate).filter_by(id=candidate_id).first()
        if not candidate:
            raise HTTPException(404, "Candidato no encontrado")
        candidate.estado = body.resolution
        candidate.resolved_by = "user"
        candidate.resuelto_en = datetime.utcnow()
        duplicate_id = None
        if body.resolution == "mismo":
            duplicate_id = _mark_duplicate(
                s, duplicate_id=candidate.movement_a, original_id=candidate.movement_b
            )
        return {
            "resolved": True,
            "estado": candidate.estado,
            "duplicate_movement_id": duplicate_id,
        }


def _mark_duplicate(session, *, duplicate_id: int, original_id: int) -> int | None:
    """Saca de KPIs/saldos/cartera el lado nuevo de un par confirmado.

    ``movement_a`` es siempre el movimiento del import más reciente (L3). Se
    conserva la fila para trazabilidad; se borran sus operaciones de cartera
    para no duplicar acciones y se recalcula la posición.
    """
    from .ingest_service import _recalc_position

    duplicate = session.query(FinancialMovement).filter_by(id=duplicate_id).first()
    if duplicate is None or duplicate_id == original_id:
        return None
    duplicate.estado = DUPLICATE_STATE
    duplicate.nota = (
        (duplicate.nota + " · " if duplicate.nota else "")
        + f"Duplicado de #{original_id}"
    )[:500]
    asset_ids = {
        asset_id
        for (asset_id,) in session.query(AssetTransaction.asset_id)
        .filter(AssetTransaction.movement_id == duplicate_id)
        .all()
    }
    session.query(AssetTransaction).filter(
        AssetTransaction.movement_id == duplicate_id
    ).delete(synchronize_session=False)
    session.query(MovementLink).filter(
        or_(
            MovementLink.movement_a == duplicate_id,
            MovementLink.movement_b == duplicate_id,
        )
    ).delete(synchronize_session=False)
    session.flush()
    for asset_id in asset_ids:
        _recalc_position(session, asset_id)
    return duplicate_id


@router.get("/transfers/suggestions")
def transfer_suggestions():
    # La detección automática fuerte ya está en movement_links/backfill; esta
    # cola queda para pares dudosos. Devolver vacío es honesto hasta F2.
    return {"items": [], "total": 0}


class TransferLinkRequest(BaseModel):
    outbound_id: int
    inbound_id: int


@router.post("/transfers/link")
def link_transfer(body: TransferLinkRequest):
    with _session() as s:
        for movement_id in (body.outbound_id, body.inbound_id):
            if not s.query(FinancialMovement).filter_by(id=movement_id).first():
                raise HTTPException(404, f"Movimiento {movement_id} no encontrado")
        existing = (
            s.query(MovementLink)
            .filter(
                MovementLink.movement_a == body.outbound_id,
                MovementLink.movement_b == body.inbound_id,
                MovementLink.link_type == "internal_transfer",
            )
            .first()
        )
        if existing is None:
            s.add(MovementLink(
                movement_a=body.outbound_id,
                movement_b=body.inbound_id,
                link_type="internal_transfer",
                confianza="alta",
            ))
        return {"linked": True}


@router.post("/transfers/dismiss")
def dismiss_transfer(body: TransferLinkRequest):
    return {"dismissed": True}


@router.get("/analytics/daily-density")
def daily_density_v3(
    desde: date | None = None,
    hasta: date | None = None,
):
    with _session() as s:
        q = s.query(
            FinancialMovement.value_date,
            func.count(FinancialMovement.id),
        )
        if desde:
            q = q.filter(FinancialMovement.value_date >= desde)
        if hasta:
            q = q.filter(FinancialMovement.value_date <= hasta)
        rows = (
            q.group_by(FinancialMovement.value_date)
            .order_by(FinancialMovement.value_date)
            .all()
        )
        items = [
            {"date": day.isoformat() if day else None, "count": count}
            for day, count in rows
        ]
        return {"items": items, "total": len(items)}


@router.get("/analytics/summary")
def analytics_summary(
    desde: date | None = None,
    hasta: date | None = None,
):
    with _session() as s:
        base_q = s.query(FinancialMovement)
        if desde:
            base_q = base_q.filter(FinancialMovement.value_date >= desde)
        if hasta:
            base_q = base_q.filter(FinancialMovement.value_date <= hasta)
        kpi_q = _apply_kpi_filters(s, base_q)

        ingresos = Decimal("0")
        gastos = Decimal("0")
        for amount, amount_eur, currency, kind in kpi_q.with_entities(
            FinancialMovement.amount,
            FinancialMovement.amount_eur,
            FinancialMovement.currency,
            FinancialMovement.kind,
        ).all():
            value = amount_eur
            if value is None and (currency or "EUR").upper() == "EUR":
                value = amount
            if value is None:
                continue
            income, expense = _kpi_split(kind, value)
            ingresos += income
            gastos += expense

        transfer_sub = (
            select(Classification.movement_id)
            .join(Categoria, Categoria.id == Classification.categoria_id)
            .where(
                Classification.vigente == True,  # noqa: E712
                Categoria.tratamiento == "transferencia",
            )
        )
        transfer_q = base_q.filter(
            or_(
                FinancialMovement.kind == "transferencia_interna",
                FinancialMovement.id.in_(transfer_sub),
            )
        )
        transferencias_netas = sum(
            (
                Decimal(str(amount_eur if amount_eur is not None else amount))
                for amount, amount_eur, currency in transfer_q.with_entities(
                    FinancialMovement.amount,
                    FinancialMovement.amount_eur,
                    FinancialMovement.currency,
                ).all()
                if amount is not None
                and (
                    amount_eur is not None
                    or (currency or "EUR").upper() == "EUR"
                )
            ),
            Decimal("0"),
        )

        pendientes = base_q.filter(FinancialMovement.estado == "pendiente").count()
        sin_categoria = (
            base_q.filter(
                ~s.query(Classification.id)
                .filter(
                    Classification.movement_id == FinancialMovement.id,
                    Classification.vigente == True,  # noqa: E712
                    Classification.categoria_id.isnot(None),
                )
                .exists()
            ).count()
        )
        duplicados = (
            s.query(DedupCandidate)
            .filter(DedupCandidate.estado == "pendiente")
            .count()
        )
        balances = _account_balances(s)
        active_account_ids = [
            account_id
            for (account_id,) in s.query(Account.id)
            .filter(Account.activo == True)  # noqa: E712
            .all()
        ]
        patrimonio = sum(
            (balances.get(account_id, Decimal("0")) for account_id in active_account_ids),
            Decimal("0"),
        )
        neto = ingresos - gastos
        return {
            "desde": desde.isoformat() if desde else None,
            "hasta": hasta.isoformat() if hasta else None,
            "period": {
                "from": desde.isoformat() if desde else "2026-01-01",
                "to": hasta.isoformat() if hasta else "2026-12-31",
                "label": _period_label(desde, hasta),
            },
            "ingresos": _money(ingresos),
            "gastos": _money(gastos),
            "neto": _money(neto),
            "flujo_neto": _money(neto),
            "tasa_ahorro": (
                float(neto / ingresos) if ingresos > 0 else 0.0
            ),
            "ingresos_prev": 0.0,
            "gastos_prev": 0.0,
            "flujo_neto_prev": 0.0,
            "patrimonio_neto": _money(patrimonio),
            "patrimonio_neto_prev": _money(patrimonio),
            "pendientes": pendientes,
            "sin_categoria": sin_categoria,
            "duplicados": duplicados,
            "transferencias_sugeridas": 0,
            "transferencias_netas": _money(transferencias_netas),
            "aportes_netos": _money(transferencias_netas),
            "moneda": "EUR",
        }


@router.get("/analytics/cashflow")
def analytics_cashflow(
    months: int = Query(default=12, ge=1, le=60),
    desde: date | None = None,
    hasta: date | None = None,
    granularity: Literal["day", "week", "month", "year"] = Query(default="month"),
    all_items: bool = Query(default=False, alias="all"),
):
    with _session() as s:
        query = (
            s.query(
                FinancialMovement.value_date,
                FinancialMovement.amount,
                FinancialMovement.amount_eur,
                FinancialMovement.currency,
                FinancialMovement.kind,
            )
            .filter(FinancialMovement.kind.in_(INCOME_KINDS | EXPENSE_KINDS))
            .order_by(FinancialMovement.value_date)
        )
        query = _apply_kpi_filters(s, query)
        if desde:
            query = query.filter(FinancialMovement.value_date >= desde)
        if hasta:
            query = query.filter(FinancialMovement.value_date <= hasta)
        rows = query.all()
    buckets: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: {"ingresos": Decimal("0"), "gastos": Decimal("0")}
    )
    if desde and hasta and desde <= hasta:
        for start in _cashflow_bucket_starts(desde, hasta, granularity):
            buckets[_cashflow_key(start, granularity)]  # cubo vacío
    for value_date, amount, amount_eur, currency, kind in rows:
        value = amount_eur
        if value is None and (currency or "EUR").upper() == "EUR":
            value = amount
        if value is None:
            continue
        key = _cashflow_key(value_date, granularity)
        income, expense = _kpi_split(kind, value)
        buckets[key]["ingresos"] += income
        buckets[key]["gastos"] += expense
    result = [
        {
            "mes": key,
            "month": key,
            "ingresos": _money(value["ingresos"]),
            "gastos": _money(value["gastos"]),
            "neto": _money(value["ingresos"] - value["gastos"]),
        }
        for key, value in sorted(buckets.items())
    ]
    selected = result if desde or hasta or all_items else result[-months:]
    return {
        "items": selected,
        "total": len(selected),
        "granularity": granularity,
    }


@router.get("/analytics/by-category")
def analytics_by_category(
    desde: date | None = None,
    hasta: date | None = None,
    include_excluded: bool = Query(default=False, alias="include_excluded"),
):
    with _session() as s:
        paths = category_paths(s)
        category_colors = {
            category_id: color
            for category_id, color in s.query(Categoria.id, Categoria.color).all()
        }
        categories_kinds = sorted(INCOME_KINDS | EXPENSE_KINDS)
        if include_excluded:
            categories_kinds.extend(
                ["inversion_compra", "inversion_venta", "aporte_activo", "transferencia_interna"]
            )
        q = (
            s.query(
                Classification.categoria_id,
                FinancialMovement.kind,
                FinancialMovement.amount,
                FinancialMovement.amount_eur,
                FinancialMovement.currency,
            )
            .outerjoin(
                Classification,
                (Classification.movement_id == FinancialMovement.id)
                & (Classification.vigente == True),  # noqa: E712
            )
            .filter(
                FinancialMovement.kind.in_(categories_kinds)
            )
        )
        if not include_excluded:
            q = _apply_kpi_filters(s, q)
        if desde:
            q = q.filter(FinancialMovement.value_date >= desde)
        if hasta:
            q = q.filter(FinancialMovement.value_date <= hasta)
        rows = q.all()

    palette = [
        "#D6F84C", "#60A5FA", "#F472B6", "#34D399", "#FBBF24",
        "#A78BFA", "#FB7185", "#22D3EE", "#A3E635", "#F97316",
    ]
    buckets: dict[int, dict] = defaultdict(
        lambda: {
            "categoria_id": 0,
            "categoria": "Sin categoría",
            "color": None,
            "gastos": Decimal("0"),
            "ingresos": Decimal("0"),
            "movimientos": 0,
        }
    )
    for category_id, kind, amount, amount_eur, currency in rows:
        value = amount_eur
        if value is None and (currency or "EUR").upper() == "EUR":
            value = amount
        if value is None:
            continue
        key = category_id or 0
        bucket = buckets[key]
        bucket["categoria_id"] = key
        bucket["categoria"] = paths.get(category_id, "Sin categoría")
        bucket["color"] = category_colors.get(category_id)
        bucket["movimientos"] += 1
        if kind in EXPENSE_KINDS:
            bucket["gastos"] += -Decimal(str(value))
        else:
            bucket["ingresos"] += Decimal(str(value))
    items = []
    for index, value in enumerate(sorted(
        buckets.values(),
        key=lambda item: item["gastos"] + item["ingresos"],
        reverse=True,
    )):
        items.append({
            "categoria_id": value["categoria_id"],
            "categoria": value["categoria"],
            "color": value["color"] or palette[index % len(palette)],
            "gastos": _money(value["gastos"]),
            "ingresos": _money(value["ingresos"]),
            "total": _money(value["gastos"] + value["ingresos"]),
            "prev_total": 0.0,
            "delta_pct": 0.0,
            "movimientos": value["movimientos"],
        })
    return {"items": items, "total": len(items)}


@router.get("/analytics/by-merchant")
def analytics_by_merchant(limit: int = Query(default=20, ge=1, le=200)):
    with _session() as s:
        query = (
            s.query(
                FinancialMovement.merchant,
                FinancialMovement.amount,
                FinancialMovement.amount_eur,
                FinancialMovement.currency,
            )
            .filter(
                FinancialMovement.kind == "gasto",
                FinancialMovement.merchant.isnot(None),
            )
        )
        rows = _apply_kpi_filters(s, query).all()
    totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for merchant, amount, amount_eur, currency in rows:
        value = amount_eur
        if value is None and (currency or "EUR").upper() == "EUR":
            value = amount
        if value is not None:
            totals[merchant] += -Decimal(str(value))
    ordered = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {"merchant": merchant, "gastos": _money(total)}
        for merchant, total in ordered
    ]


@router.get("/analytics/data-health")
def analytics_data_health():
    with _session() as s:
        total = s.query(FinancialMovement).count()
        pendientes = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.estado == "pendiente")
            .count()
        )
        sin_categoria = (
            s.query(FinancialMovement)
            .filter(
                ~s.query(Classification.id)
                .filter(
                    Classification.movement_id == FinancialMovement.id,
                    Classification.vigente == True,  # noqa: E712
                    Classification.categoria_id.isnot(None),
                )
                .exists()
            )
            .count()
        )
        auto = (
            s.query(Classification)
            .filter(
                Classification.vigente == True,  # noqa: E712
                Classification.categoria_id.isnot(None),
                Classification.origen.in_(["rule", "broker", "memory", "decider"]),
            )
            .count()
        )
        last_import = (
            s.query(SourceFile).order_by(SourceFile.id.desc()).first()
        )
        accounts_total = (
            s.query(Account).filter(Account.activo == True).count()  # noqa: E712
        )
        negative_positions = (
            s.query(PositionSnapshot)
            .filter(PositionSnapshot.cantidad < 0)
            .count()
        )
        last_import_payload = (
            {
                "id": last_import.id,
                "filename": last_import.filename,
                "status": last_import.status,
                "parseado_en": (
                    last_import.parseado_en.isoformat()
                    if last_import.parseado_en
                    else None
                ),
            }
            if last_import
            else None
        )
        return {
            "total_movimientos": total,
            "pendientes": pendientes,
            "sin_categoria": sin_categoria,
            "auto_clasificados": auto,
            "porcentaje_auto": round(auto / total * 100, 1) if total else 0,
            "ultima_importacion": last_import_payload,
            # Contrato frontend.
            "last_import_at": (
                last_import_payload["parseado_en"] if last_import_payload else None
            ),
            "last_import_filename": last_import.filename if last_import else None,
            "auto_classified_pct": round(auto / total * 100, 1) if total else 0,
            "corrections_last_week": 0,
            "pending_count": pendientes,
            "uncategorized_count": sin_categoria,
            "duplicate_count": (
                s.query(DedupCandidate)
                .filter(DedupCandidate.estado == "pendiente")
                .count()
            ),
            "internal_transfers_pending": 0,
            "accounts_total": accounts_total,
            "accounts_unreconciled": accounts_total,
            "negative_positions": negative_positions,
            "missing_opening_positions": negative_positions > 0,
            "stale_movements_without_classification": sin_categoria,
        }


ZERO_DEC = Decimal("0")


def _portfolio_calculation(session) -> dict:
    assets = {asset.id: asset for asset in session.query(Asset).all()}
    kind_map = {
        "compra": "BUY",
        "venta": "SELL",
        "aporte": "FREE_RECEIPT",
        "dividendo_accion": "DIVIDEND",
    }
    # Un dividendo no tiene precio unitario: su ``AssetTransaction`` guarda
    # precio 0 y las acciones con derecho. El importe bruto está en el evento
    # del movimiento; sin él, el total de dividendos era solo la retención.
    dividend_gross = {
        movement_id: amount
        for movement_id, amount in (
            session.query(FinancialMovement.id, NormalizedEvent.amount)
            .join(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .filter(FinancialMovement.kind == "dividendo")
            .all()
        )
    }
    operations = []
    for tx in session.query(AssetTransaction).order_by(
        AssetTransaction.fecha, AssetTransaction.id
    ).all():
        if tx.tipo not in kind_map:
            continue
        price = Decimal(str(tx.price or 0))
        if tx.tipo == "dividendo_accion":
            gross = dividend_gross.get(tx.movement_id)
            price = Decimal(str(gross)) if gross is not None else ZERO_DEC
        operations.append(AssetOperation(
            id=f"tx:{tx.id}",
            asset_id=str(tx.asset_id),
            kind=kind_map[tx.tipo],  # type: ignore[arg-type]
            operation_date=tx.fecha,
            quantity=Decimal(str(tx.shares or 0)),
            price=price,
            fee=Decimal(str(tx.fee or 0)),
            tax=Decimal(str(tx.tax or 0)),
            sequence=tx.id,
        ))
    openings = [
        OpeningPosition(
            asset_id=str(opening.asset_id),
            as_of_date=opening.as_of_date,
            quantity=Decimal(str(opening.quantity or 0)),
            cost_total=(
                Decimal(str(opening.cost_total))
                if opening.cost_total is not None else None
            ),
            cost_status=opening.cost_status or "unknown",  # type: ignore[arg-type]
            source=opening.source or "derived",
        )
        for opening in session.query(AssetOpeningPosition).all()
    ]

    latest_snapshot = (
        session.query(PortfolioSnapshot)
        .order_by(PortfolioSnapshot.snapshot_date.desc())
        .first()
    )
    snapshot = None
    if latest_snapshot is not None:
        row_snapshot = (
            session.query(PortfolioSnapshot)
            .filter(PortfolioSnapshot.snapshot_date == latest_snapshot.snapshot_date)
            .order_by(PortfolioSnapshot.id)
            .all()
        )
        snapshot_positions = []
        for header in row_snapshot:
            for position in (
                session.query(PortfolioSnapshotPosition)
                .filter_by(snapshot_id=header.id)
                .all()
            ):
                snapshot_positions.append(PortfolioCalcPosition(
                    asset_id=str(position.asset_id),
                    quantity=Decimal(str(position.quantity or 0)),
                    price=Decimal(str(position.price or 0)),
                    value=Decimal(str(position.value or 0)),
                    price_date=position.price_date,
                ))
        cash_declared = sum(
            (
                Decimal(str(header.cash_declared))
                for header in row_snapshot
                if header.cash_declared is not None
            ),
            Decimal("0"),
        )
        if any(header.cash_declared is not None for header in row_snapshot):
            snapshot = PortfolioCalcSnapshot(
                snapshot_date=latest_snapshot.snapshot_date,
                positions=tuple(snapshot_positions),
                cash_declared=cash_declared,
            )
        else:
            snapshot = PortfolioCalcSnapshot(
                snapshot_date=latest_snapshot.snapshot_date,
                positions=tuple(snapshot_positions),
            )

    # El efectivo declarado en el snapshot es el de sus cuentas, no el de
    # todas (Revolut no forma parte del extracto de patrimonio de TR).
    cash_calculated = None
    if latest_snapshot is not None:
        balances = _account_balances(session)
        snapshot_accounts = {header.account_id for header in row_snapshot}
        cash_calculated = sum(
            (balances.get(account_id, Decimal("0")) for account_id in snapshot_accounts),
            Decimal("0"),
        )
    calculation = rebuild_portfolio(
        operations=operations,
        openings=openings,
        snapshot=snapshot,
        cash_calculated=cash_calculated,
    )
    calculation["_assets"] = assets
    return calculation


@router.get("/portfolio/summary")
def portfolio_summary():
    class_map = {
        "STOCK": "stock",
        "ETF": "etf",
        "FUND": "fondo",
        "MUTUAL_FUND": "fondo",
        "CRYPTO": "cripto",
    }
    with _session() as s:
        calculation = _portfolio_calculation(s)
        assets = calculation["_assets"]
        raw_positions = calculation["posiciones"]
        display_values: dict[str, Decimal] = {}
        allocation: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        positions = []
        negatives = []
        warnings = [
            issue["message"] for issue in calculation["incidencias"]
        ]
        for item in raw_positions:
            asset = assets.get(int(item["asset_id"]))
            if asset is None:
                continue
            quantity = Decimal(item["cantidad"])
            market_value = (
                Decimal(item["valor_actual"])
                if item["valor_actual"] is not None else None
            )
            cost = Decimal(item["coste_total"])
            display_value = market_value if market_value is not None else cost
            display_values[item["asset_id"]] = display_value
            asset_class = class_map.get(
                (asset.asset_class or "").upper(), "otro"
            )
            pnl = (
                Decimal(item["pnl_no_realizado"])
                if item["pnl_no_realizado"] is not None else None
            )
            pnl_pct = (
                float(pnl / cost * 100)
                if pnl is not None and cost > 0 else 0.0
            )
            coverage = Decimal(item["cobertura_coste"])
            incomplete = (
                quantity < 0
                or coverage < 1
                or market_value is None
                or pnl is None
            )
            if quantity < 0:
                negatives.append({
                    "asset_id": asset.id,
                    "symbol": asset.symbol,
                    "cantidad": _money(quantity),
                })
            positions.append({
                "asset_id": asset.id,
                "symbol": asset.symbol,
                "isin": asset.isin,
                "nombre": asset.nombre or asset.symbol,
                "asset_class": asset_class,
                "cantidad": _money(quantity),
                "cantidad_declarada": (
                    _money(Decimal(item["cantidad_declarada"]))
                    if item["cantidad_declarada"] is not None else None
                ),
                "diferencia_cantidad": (
                    _money(Decimal(item["diferencia_cantidad"]))
                    if item["diferencia_cantidad"] is not None else None
                ),
                "precio_medio": (
                    _money(Decimal(item["precio_medio"]))
                    if item["precio_medio"] is not None else 0.0
                ),
                "precio_actual": (
                    _money(Decimal(item["precio_actual"]))
                    if item["precio_actual"] is not None else None
                ),
                "precio_fecha": item["precio_fecha"],
                "valor_actual": _money(display_value),
                "coste_total": _money(cost),
                "cobertura_coste": _money(coverage),
                "coste_completo": coverage >= 1,
                "pnl_no_realizado": _money(pnl or 0),
                "pnl_no_realizado_pct": round(pnl_pct, 2),
                "pnl_realizado": _money(Decimal(item["pnl_realizado"])),
                "pnl_realizado_completo": bool(item["pnl_realizado_completo"]),
                "peso": 0.0,
                "moneda": asset.moneda or "EUR",
                "yf_ticker": asset.yf_ticker,
                "datos_incompletos": incomplete,
                "invertido": _money(cost),
                "comisiones": _money(Decimal(item["comisiones"])),
                "ganancia_realizada": _money(Decimal(item["pnl_realizado"])),
                "posicion_negativa": quantity < 0,
            })
            if quantity > 0:
                allocation[asset_class] += display_value

        visible = [item for item in positions if item["cantidad"] > 0]
        total_value = sum(
            (display_values[str(item["asset_id"])] for item in visible),
            Decimal("0"),
        )
        for item in visible:
            value = display_values[str(item["asset_id"])]
            item["peso"] = (
                round(float(value / total_value * 100), 2)
                if total_value > 0 else 0.0
            )
        total_cost = sum(
            (Decimal(str(item["coste_total"])) for item in visible),
            Decimal("0"),
        )
        allocation_items = [
            {
                "label": label,
                "value": _money(value),
                "peso": (
                    round(float(value / total_value * 100), 2)
                    if total_value > 0 else 0.0
                ),
            }
            for label, value in allocation.items()
        ]
        if calculation["unknown_cost_positions"]:
            warnings.append(
                f"{calculation['unknown_cost_positions']} posiciones tienen coste desconocido; "
                "su P&L no se calcula hasta aportar o aprobar un coste."
            )
        if positions and calculation["snapshot_date"] is None:
            warnings.append(
                "No hay snapshot de patrimonio; el valor mostrado usa coste."
            )
        return {
            "posiciones": visible,
            "valor_total": _money(total_value),
            "coste_total": _money(total_cost),
            "pnl_no_realizado": _money(Decimal(calculation["total_unrealized"])),
            "pnl_realizado": _money(Decimal(calculation["total_realized"])),
            "dividendos": _money(Decimal(calculation["total_dividends"])),
            "comisiones": _money(Decimal(calculation["total_fees"])),
            "moneda": "EUR",
            "asignacion": allocation_items,
            "avisos": list(dict.fromkeys(warnings)),
            "posiciones_negativas": negatives,
            "calculado_en": calculation["snapshot_date"] or datetime.utcnow().isoformat(),
            "total_invertido": _money(total_cost),
            "ganancia_realizada": _money(Decimal(calculation["total_realized"])),
            "snapshot_date": calculation["snapshot_date"],
            "cash_difference": (
                _money(Decimal(calculation["cash_difference"]))
                if calculation["cash_difference"] is not None else None
            ),
        }


@router.get("/portfolio")
def portfolio_alias():
    return portfolio_summary()


@router.get("/portfolio/history")
def portfolio_history():
    """Serie real de snapshots; no inventa valoraciones intermedias."""
    with _session() as s:
        snapshots = (
            s.query(PortfolioSnapshot)
            .order_by(PortfolioSnapshot.snapshot_date)
            .all()
        )
        items = []
        for snapshot in snapshots:
            positions_value = sum(
                (
                    Decimal(str(position.value or 0))
                    for position in s.query(PortfolioSnapshotPosition)
                    .filter_by(snapshot_id=snapshot.id)
                    .all()
                ),
                Decimal("0"),
            )
            cash = Decimal(str(snapshot.cash_declared or 0))
            items.append({
                "date": snapshot.snapshot_date.isoformat(),
                "account_id": snapshot.account_id,
                "custody_ref": snapshot.custody_ref,
                "positions_value": _money(positions_value),
                "cash": _money(cash),
                "total": _money(
                    Decimal(str(snapshot.total_declared))
                    if snapshot.total_declared is not None
                    else positions_value + cash
                ),
                "currency": snapshot.currency,
            })
        return {"items": items, "total": len(items)}


@router.get("/portfolio/assets/{asset_id}")
def portfolio_asset(asset_id: int):
    """Ficha de un activo con la misma posición FIFO que ``/portfolio/summary``.

    Antes leía ``position_snapshot`` (coste medio legacy, sin aperturas), que
    podía contradecir al resumen.
    """
    with _session() as s:
        asset = s.query(Asset).filter_by(id=asset_id).first()
        if not asset:
            raise HTTPException(404, "Activo no encontrado")
        calculation = _portfolio_calculation(s)
        item = next(
            (
                position for position in calculation["posiciones"]
                if position["asset_id"] == str(asset_id)
            ),
            None,
        )
        return {
            "asset": {
                "id": asset.id,
                "symbol": asset.symbol,
                "isin": asset.isin,
                "nombre": asset.nombre,
                "asset_class": asset.asset_class,
                "yf_ticker": asset.yf_ticker,
            },
            "posicion": (
                {
                    "cantidad": _money(Decimal(item["cantidad"])),
                    "coste_total": _money(Decimal(item["coste_total"])),
                    "precio_medio": (
                        _money(Decimal(item["precio_medio"]))
                        if item["precio_medio"] is not None else None
                    ),
                    "invertido": _money(Decimal(item["coste_total"])),
                    "ganancia_realizada": _money(Decimal(item["pnl_realizado"])),
                    "pnl_realizado_completo": bool(item["pnl_realizado_completo"]),
                    "cobertura_coste": _money(Decimal(item["cobertura_coste"])),
                    "dividendos": _money(Decimal(item["dividendos"])),
                    "incidencias": item["incidencias"],
                }
                if item
                else None
            ),
        }
