"""
Orquestador de importaciones.

Flujo: upload → raw_rows → normalize → accounts → dedup → movements → classify
→ report. Una sola sesión y un solo commit por importación; las reglas se
cargan una vez y se evalúan en memoria.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import re
import shutil
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import or_

from .ai.document_agent import probe_file
from .classify.rules import RuleEngine
from .db.session import _session
from .dedup import compute_fingerprint, score_similarity
from .fx import amount_to_eur
from .ingest.account_match import (
    AccountMatch,
    evaluate_account_match,
    product_is_unsupported,
)
from .ingest.account_resolver import resolve_account
from .ingest.accounts import (
    base_broker_type,
    classify_transfer_kind,
    is_card_transaction,
    is_transfer_type,
    load_account_index,
    normalize_iban,
    resolve_accounts,
)
from .ingest.agentic import AgenticStatementExtractor, ExtractedStatement
from .ingest.internal_transfers import link_internal_transfers
from .ingest.portfolio_snapshot import (
    PortfolioSnapshotDraft,
    read_portfolio_snapshot,
)
from .classify.review_policy import is_transfer_movement
from .model_settings import load_model_settings
from .models import (
    Account,
    AccountCurrencyBalance,
    AppConfig,
    Asset,
    AssetTransaction,
    Categoria,
    Classification,
    DedupCandidate,
    FinancialMovement,
    MovementSource,
    NormalizedEvent,
    AssetOpeningPosition,
    PortfolioSnapshot,
    PortfolioSnapshotPosition,
    PositionSnapshot,
    RawRow,
    SourceFile,
)
from .taxonomy import category_paths, resolve_assignable_category

DATA_DIR = Path(os.getenv("DATA_DIR", "data/files"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Kinds que se consideran hechos deterministas del broker y se auto-aprueban.
DEFAULT_AUTO_APPROVE_KINDS = {
    "inversion_compra", "inversion_venta", "dividendo",
    "interes", "cashback", "aporte_activo", "transferencia_interna",
    "cambio_divisa",
}

BROKER_CLASSIFIED_KINDS = {
    "inversion_compra", "inversion_venta", "dividendo", "interes",
    "cashback", "aporte_activo", "transferencia_interna", "cambio_divisa",
}

# Categoría por defecto para hechos deterministas (si existe en el catálogo).
BROKER_DEFAULT_CATEGORY = {
    "inversion_compra": "Inversiones › Compras",
    "inversion_venta": "Inversiones › Ventas",
    "dividendo": "Ingresos › Dividendos",
    "interes": "Ingresos › Intereses",
    # El cashback de Trade Republic es saveback en activo. Ingresos › Cashback
    # queda disponible para cashback fiat manual.
    "cashback": "Inversiones › Cashback",
    "aporte_activo": "Inversiones › Aportaciones",
    "transferencia_interna": "Transferencias › Otros",
    "cambio_divisa": "Transferencias › Otros",
}

# El saveback de Trade Republic se paga en valor de activo, no en fiat.
BROKER_TYPE_CATEGORY = {
    "BENEFITS_SAVEBACK": "Inversiones › Cashback",
}

# En los CSV del broker, el importe es bruto y las comisiones/impuestos van en
# columnas separadas. El movimiento de efectivo debe reflejar el apunte neto;
# el evento conserva el bruto para cartera y auditoría.
_CASH_NET_BROKER_TYPES = {
    "BUY",
    "SELL",
    "DIVIDEND",
    "INTEREST_PAYMENT",
    "BENEFITS_SAVEBACK",
}


def _movement_cash_amount(event: dict) -> Decimal | None:
    amount = event.get("amount")
    if amount is None:
        return None
    amount = Decimal(str(amount))
    source = str(event.get("_source") or "")
    broker_type = base_broker_type(event.get("broker_type"))
    if not source.startswith(("csv", "xlsx")) or broker_type not in _CASH_NET_BROKER_TYPES:
        return amount
    fee = Decimal(str(event.get("fee") or 0))
    tax = Decimal(str(event.get("tax") or 0))
    return amount + fee + tax


class ImportResult:
    """Resultado de una importación."""

    def __init__(self):
        self.source_file_id: int | None = None
        self.total_rows = 0
        self.new_count = 0
        self.seen_count = 0
        self.intra_file_duplicates = 0
        self.dup_candidates = 0
        self.pending_classify = 0
        self.internal_transfers = 0
        self.linked_internal_transfers = 0
        self.accounts_assigned = 0
        self.account_id: int | None = None
        self.account_match: dict | None = None
        self.period_start: date | None = None
        self.period_end: date | None = None
        self.errors: list[str] = []

    def as_dict(self) -> dict:
        return {
            "source_file_id": self.source_file_id,
            "total_rows": self.total_rows,
            "new_count": self.new_count,
            "seen_count": self.seen_count,
            "intra_file_duplicates": self.intra_file_duplicates,
            "dup_candidates": self.dup_candidates,
            "pending_classify": self.pending_classify,
            "internal_transfers": self.internal_transfers,
            "linked_internal_transfers": self.linked_internal_transfers,
            "accounts_assigned": self.accounts_assigned,
            "account_id": self.account_id,
            "account_match": self.account_match,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end": self.period_end.isoformat() if self.period_end else None,
            "errors": self.errors,
        }


# ---------------------------------------------------------------------------
# Caché de extracción
# ---------------------------------------------------------------------------
# La extracción agéntica de un PDF puede tardar minutos. Cuando un extracto
# queda en revisión (p. ej. hay que aprobar una cuenta nueva) se guarda la
# extracción para que, al aprobar, el worker reanude sin volver a llamar al
# modelo. ``reprocess`` explícito la descarta y re-extrae.
_EXTRACTION_CACHE_VERSION = 1


def _extraction_cache_path(file_hash: str) -> Path:
    return DATA_DIR / f"{file_hash}.extraction.pkl"


def save_extraction_cache(file_hash: str, extraction: ExtractedStatement) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {"version": _EXTRACTION_CACHE_VERSION, "extraction": extraction}
        tmp = _extraction_cache_path(file_hash).with_suffix(".tmp")
        with open(tmp, "wb") as fh:
            pickle.dump(payload, fh)
        os.replace(tmp, _extraction_cache_path(file_hash))
    except OSError:
        pass  # la caché es una optimización; nunca bloquea el import


def load_extraction_cache(file_hash: str) -> ExtractedStatement | None:
    path = _extraction_cache_path(file_hash)
    if not path.exists():
        return None
    try:
        with open(path, "rb") as fh:
            payload = pickle.load(fh)  # fichero propio en DATA_DIR
    except Exception:  # caché corrupta o de otra versión: se ignora
        return None
    if not isinstance(payload, dict) or payload.get("version") != _EXTRACTION_CACHE_VERSION:
        return None
    extraction = payload.get("extraction")
    return extraction if isinstance(extraction, ExtractedStatement) else None


def discard_extraction_cache(file_hash: str | None) -> None:
    if not file_hash:
        return
    try:
        _extraction_cache_path(file_hash).unlink(missing_ok=True)
    except OSError:
        pass


def _select_source_account(session, account_id: int | None, index):
    """Resuelve la cuenta propietaria del extracto.

    - ``account_id`` explícito: debe existir y estar activa.
    - Sin id: cuenta principal (``broker_central``) o primera activa.
    - BD sin cuentas: crea una única cuenta genérica, no todo el seed de
      contrapartes. Así el usuario puede borrar/archivar las cuentas que no
      quiera sin que reaparezcan en la siguiente importación.
    """
    if account_id is not None:
        selected = next((account for account in index.accounts if account.id == account_id), None)
        if selected is None:
            raise ValueError(
                "La cuenta indicada no existe o está archivada. "
                "Actívala o crea otra antes de importar."
            )
        return selected

    selected = index.source or next(iter(index.accounts), None)
    if selected is not None:
        return selected

    account = Account(
        nombre="Cuenta principal",
        tipo="broker_central",
        broker=None,
        es_propia=True,
        moneda="EUR",
        color="#6366f1",
        alias_patrones=json.dumps([], ensure_ascii=False),
        activo=True,
    )
    session.add(account)
    session.flush()
    refreshed = load_account_index(session)
    selected = refreshed.source or next(iter(refreshed.accounts), None)
    if selected is None:
        raise ValueError("No se pudo crear la cuenta principal para el extracto")
    return selected


def _detected_products(extraction) -> list[str]:
    """Productos/cuentas presentes en las filas crudas, si el formato los trae.

    Se usa para no importar un CSV/PDF que mezcla Cuenta, Pockets y Depósito
    en una sola cuenta. ``DEFAULT`` (Trade Republic) se ignora.
    """
    values: set[str] = set()
    for raw in extraction.raw_rows or []:
        fields = raw.get("values") if isinstance(raw, dict) else None
        if fields is None and isinstance(raw, dict):
            fields = raw.get("fields")
        if not isinstance(fields, dict):
            continue
        for key, value in fields.items():
            normalized = re.sub(r"[^a-z0-9]+", "_", str(key).lower()).strip("_")
            if normalized not in {"product", "producto", "account", "cuenta", "account_type"}:
                continue
            text = str(value or "").strip()
            if text and text.upper() not in {"DEFAULT", "DEFAULT_ACCOUNT"}:
                values.add(text)
    return sorted(values)


def _approved_account_profiles(session) -> list[dict]:
    """Perfiles documentales de imports ya consolidados y con cuenta."""
    profiles: list[dict] = []
    rows = (
        session.query(SourceFile.account_id, SourceFile.extraction_meta)
        .filter(
            SourceFile.account_id.isnot(None),
            SourceFile.status.in_(["parsed", "parsed_with_overlap"]),
        )
        .order_by(SourceFile.id.desc())
        .all()
    )
    for account_id, raw_meta in rows:
        try:
            detected = (json.loads(raw_meta or "{}").get("detected") or {})
        except (TypeError, ValueError):
            detected = {}
        profiles.append({
            "account_id": account_id,
            "bank": detected.get("bank"),
            "product": detected.get("product"),
            "account_iban": detected.get("account_iban"),
        })
    return profiles


def _quarantine_product(selected_id: int | None, products: list[str]) -> AccountMatch:
    return AccountMatch(
        status="unsupported_product",
        selected_account_id=selected_id,
        detected_account_id=None,
        reason=(
            "El fichero contiene varios productos/cuentas "
            f"({', '.join(products)}). Separa Cuenta Corriente y Cuenta "
            "Conjunta; Pockets/Depósito no se controlan como cuentas."
        ),
        detected={"product": ", ".join(products)},
    )


def _new_account_match(
    *,
    detected_bank: str | None,
    detected_account_name: str | None,
    detected_iban: str | None,
    detected_product: str | None,
    reason: str | None = None,
) -> AccountMatch:
    detected = {
        "bank": detected_bank,
        "account_name": detected_account_name,
        "account_iban": detected_iban,
        "product": detected_product,
    }
    parts = [detected_bank, detected_product, detected_iban]
    summary = " · ".join(str(part) for part in parts if part)
    return AccountMatch(
        status="new_account",
        selected_account_id=None,
        detected_account_id=None,
        reason=reason or (
            "No hay una cuenta asignada para este extracto"
            + (f" ({summary})" if summary else "")
            + ". Crea la cuenta detectada o asigna una existente y reprocesa."
        ),
        detected=detected,
    )


def _extraction_meta_with_account(extraction, match: AccountMatch) -> dict:
    """Metadatos de extracto + identidad detectada + resultado del match."""
    metadata = dict(extraction.metadata or {})
    metadata["detected"] = match.detected
    metadata["account_match"] = match.as_dict()
    metadata["opening_balance_date"] = (
        extraction.opening_balance_date.isoformat()
        if extraction.opening_balance_date
        else None
    )
    metadata["closing_balance_date"] = (
        extraction.closing_balance_date.isoformat()
        if extraction.closing_balance_date
        else None
    )
    metadata["product"] = extraction.product or metadata.get("product")
    incidences = list(metadata.get("incidences") or [])
    for issue in extraction.issues:
        incidences.append({
            "code": "extraction_issue",
            "severity": "warning",
            "message": issue,
            "row_index": None,
        })
    if match.status in {"warning", "new_account", "mismatch", "unsupported_product"}:
        incidences.append({
            "code": f"account_{match.status}",
            "severity": "error" if match.blocks_import else "warning",
            "message": match.reason,
            "row_index": None,
        })
    metadata["incidences"] = incidences
    return metadata


def _quarantine_import(
    *,
    filepath: str,
    original_filename: str | None,
    file_hash: str,
    extraction,
    match: AccountMatch,
    raw_row_count: int,
    source_file_id: int | None,
    result: ImportResult,
) -> ImportResult:
    """Registra un import bloqueado sin crear movimientos.

    Se conserva el fichero y la identidad detectada para que el usuario pueda
    corregir la cuenta y reprocesar. No se guardan raw_rows/eventos para no
    dejar datos a medias; al reprocesar se crean de cero.
    """
    suffix = Path(filepath).suffix or ".csv"
    dest = DATA_DIR / f"{file_hash}{suffix}"
    if not dest.exists():
        shutil.copy2(filepath, dest)
    if isinstance(extraction, ExtractedStatement):
        save_extraction_cache(file_hash, extraction)
    probe = probe_file(Path(filepath))
    metadata = _extraction_meta_with_account(extraction, match)
    reason = match.reason

    with _session() as s:
        sf = None
        if source_file_id is not None:
            sf = s.query(SourceFile).filter_by(id=source_file_id).first()
        if sf is None:
            sf = s.query(SourceFile).filter_by(file_hash=file_hash).first()
        if sf is None:
            sf = SourceFile(
                source=extraction.source,
                filename=original_filename or os.path.basename(filepath),
                file_hash=file_hash,
                parser_version=extraction.parser_version,
            )
            s.add(sf)
        sf.source = extraction.source
        sf.filename = original_filename or sf.filename
        sf.period_start = extraction.period_start
        sf.period_end = extraction.period_end
        sf.row_count = raw_row_count
        sf.movement_new_count = 0
        sf.movement_seen_count = 0
        sf.status = "needs_review"
        sf.parser_version = extraction.parser_version
        sf.storage_path = str(dest)
        sf.mime_type = probe.mime_type
        sf.page_count = probe.page_count
        sf.account_id = match.selected_account_id
        sf.balance_start = extraction.opening_balance
        sf.balance_end = extraction.closing_balance
        sf.balance_start_date = (
            (extraction.opening_balance_date or extraction.period_start)
            if extraction.opening_balance is not None
            else None
        )
        sf.extraction_meta = json.dumps(metadata, ensure_ascii=False, default=str)
        sf.error = f"Cuenta del extracto: {reason}"
        sf.parseado_en = datetime.utcnow()
        sf.finished_at = datetime.utcnow()
        s.flush()
        result.source_file_id = sf.id
        result.account_id = sf.account_id
        result.total_rows = raw_row_count
        result.period_start = sf.period_start
        result.period_end = sf.period_end
        result.account_match = match.as_dict()
        result.errors.append(reason)
    return result


def _extraction_currency(extraction) -> str:
    summary = (extraction.metadata or {}).get("summary") or {}
    currency = summary.get("currency")
    if not currency and extraction.events:
        currency = extraction.events[0].get("currency")
    return str(currency or "EUR").upper()[:3]


def _maybe_initialize_account_balance(session, account_id: int, extraction):
    """Inicializa o concilia el saldo de apertura por cuenta y divisa."""
    opening = extraction.opening_balance
    if opening is None:
        return "not_detected", "El extracto no trae saldo inicial."
    opening_date = extraction.opening_balance_date or extraction.period_start
    account = session.query(Account).filter_by(id=account_id).first()
    if account is None:
        return "not_applied", "Cuenta no encontrada."
    currency = _extraction_currency(extraction)
    anchor = (
        session.query(AccountCurrencyBalance)
        .filter_by(account_id=account_id, currency=currency)
        .first()
    )
    movement_count = (
        session.query(FinancialMovement)
        .filter(
            FinancialMovement.account_id == account_id,
            FinancialMovement.currency == currency,
        )
        .count()
    )
    primary_slot_empty = (
        currency != (account.moneda or "EUR")
        or (
            account.balance_inicial_fecha is None
            and (
                account.balance_inicial is None
                or Decimal(account.balance_inicial) == 0
            )
        )
    )
    if movement_count == 0 and anchor is None and primary_slot_empty:
        opening_eur, _, _, _ = amount_to_eur(opening, currency, opening_date)
        anchor = AccountCurrencyBalance(
            account_id=account.id,
            currency=currency,
            balance_inicial=opening,
            balance_inicial_eur=opening_eur,
            balance_inicial_fecha=opening_date,
        )
        session.add(anchor)
        if currency == (account.moneda or "EUR"):
            account.balance_inicial = opening
            account.balance_inicial_fecha = opening_date
        return (
            "applied",
            f"Saldo inicial {opening} {currency} aplicado a la cuenta"
            + (f" con fecha {opening_date}" if opening_date else " sin fecha"),
        )

    if opening_date is None:
        return "not_applied", "Saldo inicial detectado sin fecha; no se aplica."
    anchor = anchor or (
        session.query(AccountCurrencyBalance)
        .filter_by(account_id=account_id, currency=currency)
        .first()
    )
    anchor_date = anchor.balance_inicial_fecha if anchor else None
    if anchor_date and anchor_date <= opening_date:
        prior_total = (
            session.query(FinancialMovement)
            .filter(
                FinancialMovement.account_id == account_id,
                FinancialMovement.currency == currency,
                FinancialMovement.value_date >= anchor_date,
                FinancialMovement.value_date < opening_date,
            )
            .with_entities(FinancialMovement.amount)
            .all()
        )
        calculated = Decimal(str(anchor.balance_inicial or 0)) + sum(
            (Decimal(str(amount or 0)) for (amount,) in prior_total),
            Decimal("0"),
        )
        difference = calculated - Decimal(str(opening))
        if abs(difference) <= Decimal("0.01"):
            return (
                "reconciled",
                f"Saldo inicial {opening} {currency} conciliado con la cuenta.",
            )
        return (
            "warning",
            f"Saldo inicial del extracto {opening} {currency} a {opening_date} "
            f"no cuadra con la cuenta ({calculated}; diferencia {difference}).",
        )

    return (
        "not_applied",
        "El extracto empieza antes que el saldo inicial de la cuenta; no se "
        "sobrescribe.",
    )



def enqueue_import(
    filepath: str,
    *,
    original_filename: str | None = None,
    account_id: int | None = None,
) -> int:
    """Guarda el fichero y lo deja en la cola persistente del worker.

    Devuelve el ``source_file_id``. El control de duplicado es el mismo que en
    la importación síncrona; el worker reutiliza esta fila al procesar.
    """
    source_path = Path(filepath)
    raw_bytes = source_path.read_bytes()
    if not raw_bytes:
        raise ValueError("El archivo está vacío")
    file_hash = hashlib.sha256(raw_bytes).hexdigest()
    probe = probe_file(source_path)
    suffix = source_path.suffix or ".csv"
    dest = DATA_DIR / f"{file_hash}{suffix}"

    with _session() as s:
        existing = s.query(SourceFile).filter_by(file_hash=file_hash).first()
        if existing:
            if account_id is not None and existing.account_id not in (None, account_id):
                raise ValueError(
                    f"El fichero ya está importado en otra cuenta "
                    f"(import_id={existing.id}, account_id={existing.account_id})"
                )
            raise ValueError(
                f"Fichero duplicado (id={existing.id}): '{existing.filename}'"
            )
        if not dest.exists():
            shutil.copy2(source_path, dest)
        sf = SourceFile(
            source="agentic_statement",
            filename=original_filename or source_path.name,
            file_hash=file_hash,
            row_count=0,
            status="queued",
            parser_version="agentic-v1",
            storage_path=str(dest),
            mime_type=probe.mime_type,
            page_count=probe.page_count,
            account_id=account_id,
            queued_at=datetime.utcnow(),
            attempts=0,
        )
        s.add(sf)
        s.flush()
        return sf.id


def _snapshot_extraction(snapshot: PortfolioSnapshotDraft) -> ExtractedStatement:
    detected_product = snapshot.bank or "portfolio_snapshot"
    rows = [
        {
            "symbol": position.symbol,
            "name": position.name,
            "quantity": str(position.quantity),
            "price": str(position.price),
            "value": str(position.value),
            "price_date": (
                position.price_date.isoformat() if position.price_date else None
            ),
            "cost_total": (
                str(position.cost_total)
                if position.cost_total is not None else None
            ),
        }
        for position in snapshot.positions
    ]
    return ExtractedStatement(
        source="portfolio_snapshot",
        parser_version="portfolio-v1",
        raw_rows=rows,
        events=[],
        period_start=snapshot.snapshot_date,
        period_end=snapshot.snapshot_date,
        product=detected_product,
        bank=snapshot.bank,
        account_name=snapshot.bank,
        account_iban=snapshot.account_iban,
        issues=list(snapshot.issues),
        metadata={
            "format": "portfolio_snapshot",
            "doc_type": snapshot.doc_type,
            "custody_ref": snapshot.custody_ref,
            "snapshot": {
                "snapshot_date": snapshot.snapshot_date.isoformat(),
                "securities_value": (
                    str(snapshot.securities_value)
                    if snapshot.securities_value is not None else None
                ),
                "crypto_value": (
                    str(snapshot.crypto_value)
                    if snapshot.crypto_value is not None else None
                ),
                "cash_declared": (
                    str(snapshot.cash_declared)
                    if snapshot.cash_declared is not None else None
                ),
                "total_declared": (
                    str(snapshot.total_declared)
                    if snapshot.total_declared is not None else None
                ),
            },
        },
    )


def _process_portfolio_snapshot_import(
    *,
    filepath: str,
    original_filename: str | None,
    file_hash: str,
    source_file_id: int | None,
    account_id: int | None,
    snapshot: PortfolioSnapshotDraft,
    result: ImportResult,
) -> ImportResult:
    """Persiste un snapshot de patrimonio sin crear compras ni efectivo."""
    extraction = _snapshot_extraction(snapshot)
    result.total_rows = len(snapshot.positions)
    result.period_start = snapshot.snapshot_date
    result.period_end = snapshot.snapshot_date

    with _session() as s:
        index = load_account_index(s)
        if not index.accounts:
            match = _new_account_match(
                detected_bank=snapshot.bank,
                detected_account_name=snapshot.bank,
                detected_iban=snapshot.account_iban,
                detected_product=snapshot.bank or "portfolio_snapshot",
                reason=(
                    "No hay cuentas activas para asociar el extracto de "
                    "patrimonio. Confirma la cuenta y reprocesa."
                ),
            )
        elif account_id is None:
            match = resolve_account(
                accounts=index.accounts,
                detected_bank=snapshot.bank,
                detected_account_name=snapshot.bank,
                detected_iban=snapshot.account_iban,
                detected_product=snapshot.bank or "portfolio_snapshot",
                approved_profiles=_approved_account_profiles(s),
            )
        else:
            selected = _select_source_account(s, account_id, index)
            account_id = selected.id
            match = evaluate_account_match(
                selected_account=selected,
                index=load_account_index(s, source_account=selected),
                detected_bank=snapshot.bank,
                detected_account_name=snapshot.bank,
                detected_iban=snapshot.account_iban,
                detected_product=snapshot.bank or "portfolio_snapshot",
            )
    result.account_id = match.selected_account_id
    result.account_match = match.as_dict()
    if match.blocks_import:
        return _quarantine_import(
            filepath=filepath,
            original_filename=original_filename,
            file_hash=file_hash,
            extraction=extraction,
            match=match,
            raw_row_count=len(snapshot.positions),
            source_file_id=source_file_id,
            result=result,
        )

    effective_account_id = match.selected_account_id
    if effective_account_id is None:
        raise ValueError("El snapshot no tiene una cuenta asignada")

    suffix = Path(filepath).suffix or ".pdf"
    with _session() as s:
        account = s.query(Account).filter_by(id=effective_account_id).first()
        if account is None:
            raise ValueError("La cuenta del snapshot no existe")
        if source_file_id is not None:
            sf = s.query(SourceFile).filter_by(id=source_file_id).first()
            if sf is None:
                raise ValueError("Importación encolada no encontrada")
        else:
            sf = s.query(SourceFile).filter_by(file_hash=file_hash).first()
        if sf is None:
            sf = SourceFile(
                source="portfolio_snapshot",
                filename=original_filename or Path(filepath).name,
                file_hash=file_hash,
                parser_version=extraction.parser_version,
            )
            s.add(sf)
            s.flush()
        dest = Path(sf.storage_path) if sf.storage_path else DATA_DIR / f"{file_hash}{suffix}"
        if not Path(dest).exists():
            shutil.copy2(filepath, dest)
        sf.source = extraction.source
        sf.filename = original_filename or sf.filename
        sf.period_start = snapshot.snapshot_date
        sf.period_end = snapshot.snapshot_date
        sf.row_count = len(snapshot.positions)
        sf.parser_version = extraction.parser_version
        sf.storage_path = str(dest)
        sf.account_id = effective_account_id
        sf.balance_start = snapshot.cash_declared
        sf.balance_end = snapshot.total_declared
        sf.balance_start_date = (
            snapshot.snapshot_date if snapshot.cash_declared is not None else None
        )
        sf.status = "parsed"
        sf.error = None
        sf.parseado_en = datetime.utcnow()
        sf.finished_at = datetime.utcnow()

        old_raw_rows = (
            s.query(RawRow).filter_by(source_file_id=sf.id).delete(
                synchronize_session=False
            )
        )
        del old_raw_rows
        for index_row, row in enumerate(extraction.raw_rows):
            payload = json.dumps(row, ensure_ascii=False, default=str)
            s.add(RawRow(
                source_file_id=sf.id,
                row_index=index_row,
                payload=payload,
                row_hash=hashlib.sha256(payload.encode()).hexdigest(),
            ))

        existing_snapshot = (
            s.query(PortfolioSnapshot)
            .filter_by(
                account_id=effective_account_id,
                snapshot_date=snapshot.snapshot_date,
                custody_ref=snapshot.custody_ref,
            )
            .first()
        )
        if existing_snapshot is None:
            existing_snapshot = PortfolioSnapshot(
                account_id=effective_account_id,
                snapshot_date=snapshot.snapshot_date,
                custody_ref=snapshot.custody_ref,
            )
            s.add(existing_snapshot)
            s.flush()
        existing_snapshot.source_file_id = sf.id
        existing_snapshot.currency = snapshot.currency
        existing_snapshot.cash_declared = snapshot.cash_declared
        existing_snapshot.total_declared = snapshot.total_declared
        existing_snapshot.securities_value = snapshot.securities_value
        existing_snapshot.crypto_value = snapshot.crypto_value
        existing_snapshot.metadata_json = json.dumps(
            extraction.metadata, ensure_ascii=False, default=str
        )
        s.query(PortfolioSnapshotPosition).filter_by(
            snapshot_id=existing_snapshot.id
        ).delete(synchronize_session=False)

        reconciliation_issues = list(snapshot.issues)
        positions_value = Decimal("0")
        for position in snapshot.positions:
            symbol = position.symbol
            asset = s.query(Asset).filter(
                or_(
                    Asset.isin == position.asset_isin,
                    Asset.symbol == symbol,
                )
            ).first() if position.asset_isin else s.query(Asset).filter(
                Asset.symbol == symbol
            ).first()
            if asset is None:
                asset = Asset(
                    isin=position.asset_isin,
                    symbol=symbol,
                    nombre=position.name,
                    asset_class=position.asset_class,
                    moneda=snapshot.currency,
                )
                s.add(asset)
                s.flush()
            else:
                if position.asset_isin and not asset.isin:
                    asset.isin = position.asset_isin
                if not asset.nombre:
                    asset.nombre = position.name
            s.add(PortfolioSnapshotPosition(
                snapshot_id=existing_snapshot.id,
                asset_id=asset.id,
                quantity=position.quantity,
                price=position.price,
                price_date=position.price_date,
                value=position.value,
                cost_total=position.cost_total,
                pnl_declared=position.pnl_declared,
                currency=snapshot.currency,
            ))
            positions_value += position.value

            if snapshot.opening_candidate:
                opening = (
                    s.query(AssetOpeningPosition)
                    .filter_by(
                        account_id=effective_account_id,
                        asset_id=asset.id,
                        as_of_date=snapshot.snapshot_date,
                    )
                    .first()
                )
                if opening is None:
                    opening = AssetOpeningPosition(
                        account_id=effective_account_id,
                        asset_id=asset.id,
                        as_of_date=snapshot.snapshot_date,
                        quantity=position.quantity,
                    )
                    s.add(opening)
                opening.quantity = position.quantity
                opening.cost_total = position.cost_total
                opening.cost_status = (
                    "known" if position.cost_total is not None else "unknown"
                )
                opening.source = "snapshot"
                opening.source_file_id = sf.id
                opening.approved_at = datetime.utcnow()

        declared_positions = sum(
            (
                value for value in (
                    snapshot.securities_value,
                    snapshot.crypto_value,
                )
                if value is not None
            ),
            Decimal("0"),
        )
        if (
            declared_positions
            and abs(positions_value - declared_positions) > Decimal("0.02")
        ):
            reconciliation_issues.append(
                "La suma de posiciones no coincide con los totales del snapshot: "
                f"{positions_value} frente a {declared_positions}"
            )
        metadata = _extraction_meta_with_account(extraction, match)
        metadata["portfolio_reconciliation"] = {
            "positions_value": str(positions_value),
            "declared_positions_value": str(declared_positions),
            "issues": reconciliation_issues,
        }
        sf.extraction_meta = json.dumps(metadata, ensure_ascii=False, default=str)
        if reconciliation_issues:
            sf.status = "needs_review"
            sf.error = "; ".join(reconciliation_issues)[:4000]
        result.source_file_id = sf.id
        result.account_id = effective_account_id
        result.new_count = len(snapshot.positions)
        result.accounts_assigned = len(snapshot.positions)
        s.flush()
    return result


def process_import(
    filepath: str,
    force: bool = False,
    original_filename: str | None = None,
    account_id: int | None = None,
    extractor: AgenticStatementExtractor | None = None,
    source_file_id: int | None = None,
    reuse_extraction: bool = False,
) -> ImportResult:
    """Procesa un fichero importado: extrae, normaliza, dedup y persiste.

    La extracción es agéntica (OpenCode Go). ``account_id`` es la cuenta a la
    que pertenece el extracto; si se omite, se usa la principal o la primera
    activa. ``extractor`` permite inyectar un doble en tests. Si se pasa
    ``source_file_id``, se reutiliza la fila ya encolada en lugar de crear otra.
    ``reuse_extraction`` reanuda con la extracción guardada al dejar el
    extracto en revisión (aprobación de cuenta) sin volver a llamar al agente.
    """
    result = ImportResult()
    filepath = str(filepath)

    with open(filepath, "rb") as f:
        raw_bytes = f.read()
    file_hash = hashlib.sha256(raw_bytes).hexdigest()

    # L0 por contenido: el mismo fichero no debe reimportarse aunque cambie la
    # etiqueta de la fuente/parser entre versiones. Se comprueba antes de
    # llamar al agente para no gastar una extracción inútil. Cuando el worker
    # reutiliza una fila ya encolada, el control de duplicado se hizo al subir.
    if source_file_id is None:
        with _session() as s:
            existing = s.query(SourceFile).filter_by(file_hash=file_hash).first()
            if existing:
                if account_id is not None and existing.account_id not in (None, account_id):
                    raise ValueError(
                        f"El fichero ya está importado en otra cuenta "
                        f"(import_id={existing.id}, account_id={existing.account_id})"
                    )
                if not force:
                    raise ValueError(
                        f"Fichero duplicado (id={existing.id}): '{existing.filename}'"
                    )
                result.source_file_id = existing.id
                result.account_id = existing.account_id
                result.total_rows = existing.row_count or 0
                result.new_count = 0
                result.seen_count = existing.movement_seen_count or 0
                result.period_start = existing.period_start
                result.period_end = existing.period_end
                return result

    snapshot = read_portfolio_snapshot(filepath)
    if snapshot is not None:
        return _process_portfolio_snapshot_import(
            filepath=filepath,
            original_filename=original_filename,
            file_hash=file_hash,
            source_file_id=source_file_id,
            account_id=account_id,
            snapshot=snapshot,
            result=result,
        )

    # Extracción fuera de la transacción de BD: puede tardar varios segundos.
    cached = load_extraction_cache(file_hash) if reuse_extraction else None
    if cached is not None:
        extraction = cached
    elif extractor is None:
        model_settings = load_model_settings()
        with AgenticStatementExtractor(
            model=model_settings.opencode_model,
            fallback_models=model_settings.opencode_fallback_models,
            ocr_lang=model_settings.ocr_lang,
            ocr_dpi=model_settings.ocr_dpi,
        ) as agent:
            extraction = agent.extract(filepath)
    else:
        extraction = extractor.extract(filepath)

    raw_rows_data: list[tuple[int, str, str]] = []
    for idx, raw in enumerate(extraction.raw_rows):
        payload = json.dumps(raw, ensure_ascii=False, default=str)
        row_hash = hashlib.sha256(payload.encode()).hexdigest()
        raw_rows_data.append((idx, payload, row_hash))

    events_dicts = extraction.events
    if len(events_dicts) != len(raw_rows_data):
        raise ValueError(
            f"Nº eventos ({len(events_dicts)}) ≠ nº filas ({len(raw_rows_data)})"
        )
    result.total_rows = len(raw_rows_data)
    result.period_start = extraction.period_start
    result.period_end = extraction.period_end

    # Cuenta efectiva del extracto. Si viene de la cola del worker, la fila
    # source_files ya guarda la cuenta elegida al subir.
    effective_account_id = account_id
    if effective_account_id is None and source_file_id is not None:
        with _session() as s:
            queued = s.query(SourceFile).filter_by(id=source_file_id).first()
            if queued is not None:
                effective_account_id = queued.account_id

    # Validación de identidad ANTES de crear raw_rows/movimientos. Un extracto
    # de otra cuenta conocida no debe acabar en la cuenta seleccionada.
    with _session() as s:
        account_index = load_account_index(s)
        detected_products = _detected_products(extraction)
        detected_product = (
            extraction.product
            or (detected_products[0] if detected_products else None)
        )
        inferred_bank = extraction.bank
        source_label = str(extraction.source or "").lower()
        if not inferred_bank and "trade_republic" in source_label:
            inferred_bank = "Trade Republic"
        if not inferred_bank and extraction.raw_rows:
            fields = extraction.raw_rows[0].get("values") or {}
            if {"account_type", "category", "transaction_id"} <= set(fields):
                inferred_bank = "Trade Republic"
        if len(detected_products) > 1:
            selected_account = (
                _select_source_account(s, effective_account_id, account_index)
                if effective_account_id is not None
                else None
            )
            selected_id = selected_account.id if selected_account else None
            match = _quarantine_product(selected_id, detected_products)
        elif product_is_unsupported(detected_product):
            match = AccountMatch(
                status="unsupported_product",
                selected_account_id=effective_account_id,
                detected_account_id=None,
                reason=(
                    f"El extracto es del producto {detected_product!r}. "
                    "Pockets/Depósito no se controlan como cuentas; "
                    "importa solo Cuenta Corriente o Cuenta Conjunta."
                ),
                detected={
                    "bank": inferred_bank,
                    "account_name": extraction.account_name,
                    "account_iban": extraction.account_iban,
                    "product": detected_product,
                },
            )
        elif not account_index.accounts:
            # Arranque desde cero: no crear una "Cuenta principal" genérica.
            match = _new_account_match(
                detected_bank=inferred_bank,
                detected_account_name=extraction.account_name,
                detected_iban=extraction.account_iban,
                detected_product=detected_product,
            )
            effective_account_id = None
        elif effective_account_id is None:
            match = resolve_account(
                accounts=account_index.accounts,
                detected_bank=inferred_bank,
                detected_account_name=extraction.account_name,
                detected_iban=extraction.account_iban,
                detected_product=detected_product,
                approved_profiles=_approved_account_profiles(s),
            )
            effective_account_id = match.selected_account_id
        else:
            selected_account = _select_source_account(
                s, effective_account_id, account_index
            )
            effective_account_id = selected_account.id
            match = evaluate_account_match(
                selected_account=selected_account,
                index=load_account_index(s, source_account=selected_account),
                detected_bank=extraction.bank,
                detected_account_name=extraction.account_name,
                detected_iban=extraction.account_iban,
                detected_product=detected_product,
            )
    result.account_id = effective_account_id
    result.account_match = match.as_dict()

    if match.blocks_import:
        return _quarantine_import(
            filepath=filepath,
            original_filename=original_filename,
            file_hash=file_hash,
            extraction=extraction,
            match=match,
            raw_row_count=len(raw_rows_data),
            source_file_id=source_file_id,
            result=result,
        )

    suffix = Path(filepath).suffix or ".csv"
    account_meta = _extraction_meta_with_account(extraction, match)
    review_reasons: list[str] = []
    with _session() as s:
        if source_file_id is not None:
            sf = s.query(SourceFile).filter_by(id=source_file_id).first()
            if sf is None:
                raise ValueError(f"Importación encolada no encontrada: {source_file_id}")
            if sf.file_hash != file_hash:
                raise ValueError("El fichero encolado no coincide con su hash")
            if sf.status in {"parsed", "parsed_with_overlap"}:
                raise ValueError(f"La importación {source_file_id} ya estaba procesada")
            if (
                s.query(MovementSource.movement_id)
                .filter(MovementSource.source_file_id == sf.id)
                .first()
                is not None
            ):
                # Reprocesar un import que ya creó movimientos duplicaría
                # raw_rows y, con una extracción LLM no determinista,
                # también movimientos. Hay que revisarlo, no re-extraerlo.
                raise ValueError(
                    f"La importación {source_file_id} ya tiene movimientos; "
                    "revísalos en el detalle en lugar de reprocesarla"
                )
            # Restos de un intento anterior sin movimientos (fallo/cuarentena).
            s.query(RawRow).filter(RawRow.source_file_id == sf.id).delete(
                synchronize_session=False
            )
            dest = Path(sf.storage_path) if sf.storage_path else DATA_DIR / f"{file_hash}{suffix}"
            if not dest.exists():
                shutil.copy2(filepath, dest)
            sf.source = extraction.source
            sf.filename = original_filename or sf.filename
            sf.period_start = result.period_start
            sf.period_end = result.period_end
            sf.row_count = result.total_rows
            sf.status = "processing"
            sf.parser_version = extraction.parser_version
            sf.storage_path = str(dest)
            sf.balance_start = extraction.opening_balance
            sf.balance_end = extraction.closing_balance
            sf.balance_start_date = (
                (extraction.opening_balance_date or extraction.period_start)
                if extraction.opening_balance is not None
                else None
            )
            sf.extraction_meta = json.dumps(
                account_meta, ensure_ascii=False, default=str
            )
            sf.error = None
        else:
            dest = DATA_DIR / f"{file_hash}{suffix}"
            shutil.copy2(filepath, dest)
            sf = SourceFile(
                source=extraction.source,
                filename=original_filename or os.path.basename(filepath),
                file_hash=file_hash,
                period_start=result.period_start,
                period_end=result.period_end,
                row_count=result.total_rows,
                status="parsed",
                parser_version=extraction.parser_version,
                storage_path=str(dest),
                balance_start=extraction.opening_balance,
                balance_end=extraction.closing_balance,
                balance_start_date=(
                    (extraction.opening_balance_date or extraction.period_start)
                    if extraction.opening_balance is not None
                    else None
                ),
                extraction_meta=json.dumps(
                    account_meta, ensure_ascii=False, default=str
                ),
            )
            s.add(sf)
        s.flush()
        result.source_file_id = sf.id

        for idx, payload, row_hash in raw_rows_data:
            s.add(RawRow(
                source_file_id=sf.id,
                row_index=idx,
                payload=payload,
                row_hash=row_hash,
            ))
        s.flush()

        raw_rows = (
            s.query(RawRow)
            .filter_by(source_file_id=sf.id)
            .order_by(RawRow.row_index)
            .all()
        )

        # Cuenta del extracto: explícita si se indicó; si no, la principal o la
        # primera activa. Solo se crea una cuenta genérica si la BD está vacía;
        # nunca se auto-crean Revolut/Bunq/N26 a partir de transferencias.
        if effective_account_id is None:
            # Nunca caer en "la primera cuenta": sin cuenta resuelta el import
            # debería haber quedado en revisión antes de llegar aquí.
            raise ValueError("El extracto no tiene una cuenta resuelta")
        account_index = load_account_index(s)
        source_account = _select_source_account(s, effective_account_id, account_index)
        account_index = load_account_index(s, source_account=source_account)
        sf.account_id = source_account.id
        result.account_id = source_account.id

        detected_iban = normalize_iban(extraction.account_iban)
        if detected_iban and len(detected_iban) >= 15:
            account_row = s.query(Account).filter_by(id=source_account.id).first()
            if account_row is not None and not account_row.iban:
                conflict = (
                    s.query(Account)
                    .filter(Account.iban == detected_iban, Account.id != account_row.id)
                    .first()
                )
                if conflict is None:
                    account_row.iban = detected_iban
                    account_meta.setdefault("detected", {})["account_iban"] = detected_iban

        balance_status, balance_message = _maybe_initialize_account_balance(
            s, source_account.id, extraction
        )
        account_meta["account_balance"] = {
            "status": balance_status,
            "message": balance_message,
            "opening": (
                str(extraction.opening_balance)
                if extraction.opening_balance is not None
                else None
            ),
            "opening_date": (
                extraction.opening_balance_date.isoformat()
                if extraction.opening_balance_date
                else None
            ),
        }
        if balance_status == "warning":
            review_reasons.append(balance_message)
            account_meta.setdefault("incidences", []).append({
                "code": "opening_balance_mismatch",
                "severity": "error",
                "message": balance_message,
                "row_index": None,
            })
        if match.status == "warning":
            review_reasons.append(match.reason)
        sf.extraction_meta = json.dumps(
            account_meta, ensure_ascii=False, default=str
        )

        # Dedup: L1 por transaction_id y L2 por fingerprint con consumo 1:1.
        txn_map: dict[str, int] = {}
        for txn_id, movement_id in (
            s.query(NormalizedEvent.source_txn_id, FinancialMovement.id)
            .join(FinancialMovement, FinancialMovement.event_id == NormalizedEvent.id)
            .filter(NormalizedEvent.source_txn_id.isnot(None))
            .all()
        ):
            if txn_id:
                txn_map[txn_id] = movement_id

        # L2 se limita a la cuenta del extracto: el mismo cargo (fecha,
        # importe, concepto) en la cuenta personal y en la conjunta son dos
        # movimientos reales, no un duplicado.
        fp_pool: dict[str, list[int]] = defaultdict(list)
        for fp, movement_id in (
            s.query(NormalizedEvent.fingerprint, FinancialMovement.id)
            .join(FinancialMovement, FinancialMovement.event_id == NormalizedEvent.id)
            .filter(FinancialMovement.account_id == source_account.id)
            .order_by(FinancialMovement.id)
            .all()
        ):
            if fp:
                fp_pool[fp].append(movement_id)
        fp_initial_counts = {fp: len(ids) for fp, ids in fp_pool.items()}
        fp_consumed: dict[str, int] = defaultdict(int)

        auto_approve_kinds = _get_auto_approve_kinds(s)
        auto_threshold = Decimal(
            str(load_model_settings(s).auto_approve_threshold)
        )
        category_ids = {
            nombre: cat_id
            for cat_id, nombre in s.query(Categoria.id, Categoria.nombre).all()
        }
        category_ids.update(
            {path: cat_id for cat_id, path in category_paths(s).items()}
        )
        rule_engine = RuleEngine.from_session(s)
        new_movement_ids: list[int] = []
        touched_assets: set[int] = set()
        fx_missing_count = 0

        for idx, rr in enumerate(raw_rows):
            ev = events_dicts[idx]
            source_txn_id = ev.get("source_txn_id")

            # 1) Resolver cuentas antes de decidir el kind.
            _, destination = resolve_accounts(
                ev, source_account=source_account, index=account_index
            )
            if destination is not None and not (
                is_transfer_type(ev.get("broker_type"))
                or is_card_transaction(ev.get("broker_type"))
            ):
                destination = None

            event_kind = ev["kind"]
            transfer_kind = (
                None
                if event_kind == "cambio_divisa"
                else classify_transfer_kind(
                    ev.get("broker_type"), ev.get("amount"), destination
                )
            )
            if transfer_kind is not None:
                event_kind = transfer_kind
            elif destination is not None and is_card_transaction(ev.get("broker_type")):
                # Recarga de tarjeta a Revolut/N26: mover dinero entre cuentas
                # propias, no un gasto.
                event_kind = "transferencia_interna"
            elif event_kind == "transferencia_interna":
                # Parser marca provisionalmente toda transferencia; si no hay
                # cuenta propia, decide por el signo del importe.
                amt = ev.get("amount")
                event_kind = "ingreso" if amt is not None and amt > 0 else "gasto"

            # 2) L1: transaction_id siempre primero.
            if source_txn_id and source_txn_id in txn_map:
                existing_movement_id = txn_map[source_txn_id]
                _link_seen(s, sf, rr, existing_movement_id, "source_txn_id", result)
                continue

            # 3) L2: fingerprint solo si NO hay transaction_id. Si el CSV trae
            # comisiones/impuestos, se recalcula con el neto para que coincida
            # con el mismo apunte leído desde un PDF.
            cash_amount = _movement_cash_amount(ev)
            currency = ev.get("currency", "EUR")
            amount_eur, fx_rate_to_eur, fx_source, fx_date = amount_to_eur(
                cash_amount,
                currency,
                ev["value_date"],
                provided_rate=ev.get("fx_rate_to_eur"),
                provided_source=ev.get("fx_source"),
            )
            if (
                cash_amount is not None
                and amount_eur is None
                and str(currency).upper() != "EUR"
            ):
                fx_missing_count += 1
            fingerprint = ev.get("fingerprint")
            if not fingerprint or cash_amount != ev.get("amount"):
                fingerprint = compute_fingerprint(
                    str(ev["value_date"]),
                    str(cash_amount) if cash_amount is not None else None,
                    ev.get("currency", "EUR"),
                    event_kind,
                    ev.get("description_clean", ""),
                )
            if not source_txn_id:
                existing_movement_id = _consume_fingerprint(
                    fingerprint, fp_pool, fp_initial_counts, fp_consumed
                )
                if existing_movement_id is not None:
                    _link_seen(s, sf, rr, existing_movement_id, "fingerprint", result)
                    continue

            # 4) Evento y movimiento nuevos.
            ne = NormalizedEvent(
                raw_row_id=rr.id,
                source_txn_id=source_txn_id,
                source_account_id=source_account.id,
                broker_type=ev["broker_type"],
                kind=event_kind,
                occurred_at=ev.get("occurred_at"),
                value_date=ev["value_date"],
                amount=ev.get("amount"),
                currency=ev.get("currency", "EUR"),
                fee=ev.get("fee"),
                tax=ev.get("tax"),
                original_amount=ev.get("original_amount"),
                original_currency=ev.get("original_currency"),
                fx_rate=ev.get("fx_rate"),
                asset_symbol=ev.get("asset_symbol"),
                asset_name=ev.get("asset_name"),
                asset_class=ev.get("asset_class"),
                shares=ev.get("shares"),
                price=ev.get("price"),
                counterparty_name=ev.get("counterparty_name"),
                counterparty_iban=ev.get("counterparty_iban"),
                mcc_code=ev.get("mcc_code"),
                description_raw=ev.get("description_raw"),
                description_clean=ev.get("description_clean"),
                fingerprint=fingerprint,
            )
            s.add(ne)
            s.flush()

            amt = cash_amount
            direction = "-" if amt is not None and amt < 0 else "+"
            is_internal = event_kind == "transferencia_interna"
            # Transferencias (propias, a terceros o Bizum) siempre a revisión;
            # solo se propone categoría cuando la otra cuenta es propia.
            transfer_like = is_transfer_movement(event_kind, ev.get("broker_type"))
            estado = (
                "aprobado"
                if not transfer_like and event_kind in auto_approve_kinds
                else "pendiente"
            )
            merchant = _choose_merchant(ev)

            fm = FinancialMovement(
                event_id=ne.id,
                account_id=source_account.id if source_account else None,
                account_destino_id=destination.id if is_internal and destination else None,
                kind=event_kind,
                direction=direction,
                amount=amt,
                currency=currency,
                amount_eur=amount_eur,
                fx_rate_to_eur=fx_rate_to_eur,
                fx_source=fx_source,
                fx_date=fx_date,
                value_date=ev["value_date"],
                estado=estado,
                merchant=merchant,
            )
            s.add(fm)
            s.flush()
            new_movement_ids.append(fm.id)
            if source_account is not None:
                result.accounts_assigned += 1
            if is_internal:
                result.internal_transfers += 1

            # 5) Regla determinista (motor precompilado, sin sesión extra).
            hit = rule_engine.evaluate(
                merchant=merchant,
                kind=event_kind,
                description_clean=ev.get("description_clean"),
                mcc_code=ev.get("mcc_code"),
                broker_type=ev.get("broker_type"),
                counterparty_name=ev.get("counterparty_name"),
                counterparty_iban=ev.get("counterparty_iban"),
            )
            rule_classified = False
            if hit is not None:
                if hit.set_kind:
                    fm.kind = hit.set_kind
                if hit.set_merchant:
                    fm.merchant = hit.set_merchant
                if hit.auto_aprobar:
                    fm.estado = "aprobado"
                if hit.categoria_id:
                    rule_category = resolve_assignable_category(s, hit.categoria_id)
                    s.add(Classification(
                        movement_id=fm.id,
                        categoria_id=(
                            rule_category.id if rule_category is not None else hit.categoria_id
                        ),
                        subtipo=hit.subtipo,
                        origen="rule",
                        confianza=Decimal("0.99"),
                        explicacion=hit.explicacion,
                        vigente=True,
                    ))
                    if Decimal("0.99") >= auto_threshold and not transfer_like:
                        fm.estado = "aprobado"
                    rule_classified = True

            # 6) Hecho determinista del broker si la regla no clasificó.
            if not rule_classified:
                category_id = _broker_category_id(
                    event_kind,
                    ev.get("broker_type"),
                    category_ids,
                    source_account=source_account,
                    destination=destination,
                )
                # Antes toda transferencia a terceros se clasificaba como
                # Transferencias (fuera de KPIs) y se aprobaba sola. Ahora solo
                # se propone categoría a hechos deterministas y a traspasos
                # con cuenta propia resuelta; el resto queda sin categoría.
                if event_kind in BROKER_CLASSIFIED_KINDS:
                    if category_id is not None:
                        resolved = resolve_assignable_category(s, category_id)
                        if resolved is not None:
                            category_id = resolved.id
                    s.add(Classification(
                        movement_id=fm.id,
                        categoria_id=category_id,
                        subtipo=None,
                        origen="broker",
                        confianza=Decimal("0.99"),
                        explicacion=_classification_explanation(event_kind, ev),
                        vigente=True,
                    ))
                    if Decimal("0.99") >= auto_threshold and not transfer_like:
                        fm.estado = "aprobado"

            # 7) Trazabilidad: un MovementSource por (movimiento, fichero).
            _add_movement_source(
                s, fm.id, sf.id, rr.id,
                "new_source_txn_id" if source_txn_id else "new_fingerprint",
            )
            result.new_count += 1

            # 8) Dedup de eventos nuevos para futuras líneas del mismo fichero.
            if source_txn_id:
                txn_map[source_txn_id] = fm.id
            fp_pool[fingerprint].append(fm.id)

            # 9) Activos: la posición se recalcula una vez por activo al final.
            asset_id = _create_asset_transaction(
                s, fm, ev, source_file_id=sf.id
            )
            if asset_id is not None:
                touched_assets.add(asset_id)

        for asset_id in touched_assets:
            _recalc_position(s, asset_id)
        if fx_missing_count:
            review_reasons.append(
                f"{fx_missing_count} movimientos sin tipo de cambio EUR para su fecha"
            )

        _detect_l3_candidates(s, result, new_movement_ids, sf.id)
        link_stats = link_internal_transfers(s)
        result.linked_internal_transfers = link_stats.get("linked", 0)
        account_meta["internal_transfer_links"] = link_stats
        sf.extraction_meta = json.dumps(
            account_meta, ensure_ascii=False, default=str
        )

        sf.movement_new_count = result.new_count
        sf.movement_seen_count = result.seen_count
        sf.parseado_en = datetime.utcnow()
        sf.finished_at = datetime.utcnow()
        reconciliation = extraction.metadata.get("reconciliation") or {}
        if review_reasons:
            sf.status = "needs_review"
            sf.error = "; ".join(review_reasons)[:4000]
        elif (
            extraction.metadata.get("requires_review")
            or extraction.metadata.get("ocr_used")
            or (reconciliation and reconciliation.get("ok") is False)
        ):
            sf.status = "needs_review"
            sf.error = (
                "Extracción OCR: revisar fechas/importes"
                if extraction.metadata.get("ocr_used")
                else "Conciliación de saldo descuadrada; revisar movimientos"
            )
        elif result.seen_count > 0:
            sf.status = "parsed_with_overlap"
            sf.error = None
        else:
            sf.status = "parsed"
            sf.error = None

        result.pending_classify = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.estado == "pendiente")
            .count()
        )

    discard_extraction_cache(file_hash)
    return result


def _link_seen(
    session,
    sf: SourceFile,
    raw_row: RawRow,
    movement_id: int,
    match_type: str,
    result: ImportResult,
) -> None:
    """Registra un avistamiento sin crear movimiento."""
    # autoflush=False en la sesión: forzar el flush para que la consulta vea
    # el MovementSource recién creado por una fila anterior del mismo fichero.
    session.flush()
    exists = (
        session.query(MovementSource.movement_id)
        .filter_by(movement_id=movement_id, source_file_id=sf.id)
        .first()
    )
    if exists:
        # Duplicado intra-fichero: el esquema solo permite una fila por
        # (movimiento, fichero); se cuenta como avistamiento extra.
        result.intra_file_duplicates += 1
    else:
        session.add(MovementSource(
            movement_id=movement_id,
            source_file_id=sf.id,
            raw_row_id=raw_row.id,
            match_type=match_type,
        ))
    sf.movement_seen_count = (sf.movement_seen_count or 0) + 1
    result.seen_count += 1


def _add_movement_source(
    session, movement_id: int, source_file_id: int,
    raw_row_id: int, match_type: str,
) -> None:
    exists = (
        session.query(MovementSource.movement_id)
        .filter_by(movement_id=movement_id, source_file_id=source_file_id)
        .first()
    )
    if not exists:
        session.add(MovementSource(
            movement_id=movement_id,
            source_file_id=source_file_id,
            raw_row_id=raw_row_id,
            match_type=match_type,
        ))


def _consume_fingerprint(
    fingerprint: str,
    pool: dict[str, list[int]],
    initial_counts: dict[str, int],
    consumed: dict[str, int],
) -> int | None:
    """Consumo 1:1 de fingerprints preexistentes.

    Solo se consumen los movimientos que ya existían al empezar el import;
    las repeticiones legítimas dentro del mismo fichero no se colapsan.
    """
    ids = pool.get(fingerprint) or []
    index = consumed.get(fingerprint, 0)
    if index >= initial_counts.get(fingerprint, 0) or index >= len(ids):
        return None
    consumed[fingerprint] = index + 1
    return ids[index]


def _get_auto_approve_kinds(session) -> set[str]:
    row = session.query(AppConfig).filter_by(key="auto_approve_kinds").first()
    if not row or not row.value:
        return set(DEFAULT_AUTO_APPROVE_KINDS)
    try:
        return set(json.loads(row.value))
    except (TypeError, ValueError):
        return set(DEFAULT_AUTO_APPROVE_KINDS)


def _is_revolut_account(account) -> bool:
    if account is None:
        return False
    broker = (getattr(account, "broker", None) or "").lower()
    name = (getattr(account, "nombre", None) or "").lower()
    return broker == "revolut" or "revolut" in name


def _broker_category_id(
    kind: str,
    broker_type: str | None,
    category_ids: dict[str, int],
    *,
    source_account=None,
    destination=None,
) -> int | None:
    if is_transfer_type(broker_type) or kind == "transferencia_interna":
        if _is_revolut_account(source_account) or _is_revolut_account(destination):
            return category_ids.get("Transferencias › Revolut") or category_ids.get(
                "Transferencias › Otros"
            ) or category_ids.get("Transferencias")
        return category_ids.get("Transferencias › Otros") or category_ids.get(
            "Transferencias"
        )
    name = BROKER_TYPE_CATEGORY.get(base_broker_type(broker_type)) or (
        BROKER_DEFAULT_CATEGORY.get(kind)
    )
    if not name:
        return None
    direct = category_ids.get(name)
    if direct is not None:
        return direct
    # Compatibilidad con catálogos antiguos sin la subcategoría por defecto.
    return category_ids.get(name.split("›")[0].strip())


def _find_own_iban(session, event: dict) -> str | None:
    """Compatibilidad: devuelve el IBAN propio de destino si existe."""
    index = load_account_index(session)
    _, destination = resolve_accounts(event, source_account=index.source, index=index)
    return destination.iban if destination else None


def _find_destination_account(
    session, event: dict, amount: Decimal | None,
) -> int | None:
    """Compatibilidad: id de la cuenta propia de destino."""
    index = load_account_index(session)
    _, destination = resolve_accounts(event, source_account=index.source, index=index)
    return destination.id if destination else None


def _resolve_account(session, event: dict) -> int | None:
    """Compatibilidad: cuenta origen (broker central)."""
    index = load_account_index(session)
    return index.source.id if index.source else None


def _choose_merchant(event: dict) -> str | None:
    """Elige el merchant más informativo según el tipo de evento.

    En transferencias/domiciliaciones el ``name`` del CSV puede ser el
    titular de la cuenta (p. ej. el propio usuario), mientras que el comercio
    real está en ``description``. En tarjetas, ``name`` sí es el comercio.
    """
    broker_type = (event.get("broker_type") or "").upper()
    from_description = _extract_merchant(event.get("description_clean", ""))
    if "TRANSFER" in broker_type or "DIRECT_DEBIT" in broker_type:
        return (
            from_description
            or event.get("counterparty_name")
            or event.get("asset_name")
        )
    return (
        event.get("asset_name")
        or event.get("counterparty_name")
        or from_description
    )


def _extract_merchant(desc: str) -> str | None:
    """Extrae merchant de una descripción limpia."""
    if not desc:
        return None
    import re
    desc_upper = desc.upper()
    for prefix in [
        "OUTGOING TRANSFER FOR ",
        "INCOMING TRANSFER FROM ",
        "BIZUM DEBIT TRANSFER TO ",
        "SEPA DIRECT DEBIT TRANSFER TO ",
        "SAVINGS PLAN EXECUTION ",
        "CASH DIVIDEND FOR ISIN ",
        "INTEREST PAYMENT FOR ",
        "SAVEBACK CASH REWARD ",
        "BUY TRADE ",
        "SELL TRADE ",
        "FREE_RECEIPT ",
    ]:
        if desc_upper.startswith(prefix):
            rest = desc[len(prefix):].strip()
            rest = re.sub(r'\s*\(.*?\)', '', rest)  # quitar IBANs entre paréntesis
            rest = re.sub(r'\s*[A-Z]{2}\d+.*', '', rest)  # quitar IBANs sueltos
            return rest.strip() or None
    return desc[:80]


def _classification_explanation(kind: str, event: dict) -> str:
    """Explicación corta para auto-clasificación."""
    bt = event.get("broker_type", "")
    if kind in ("inversion_compra", "inversion_venta"):
        return f"Tipo broker: {bt} — clasificación determinista desde CSV"
    if kind in ("dividendo", "interes", "cashback"):
        return f"Tipo broker: {bt} — clasificación determinista desde CSV"
    if kind == "transferencia_interna":
        return "Transferencia a cuenta propia detectada por IBAN/patrón"
    if kind in ("gasto", "ingreso"):
        return f"Clasificado por signo del importe: {event.get('amount')}"
    return "Clasificación automática"


def _apply_import_rules(
    session, fm: FinancialMovement, ne: NormalizedEvent,
    event: dict, current_kind: str, merchant: str | None,
    engine: RuleEngine | None = None,
) -> None:
    """Compatibilidad: evalúa reglas sobre un movimiento ya creado."""
    engine = engine or RuleEngine.from_session(session)
    hit = engine.evaluate(
        merchant=merchant,
        kind=current_kind,
        description_clean=event.get("description_clean", ""),
        mcc_code=event.get("mcc_code"),
        broker_type=event.get("broker_type"),
        counterparty_name=event.get("counterparty_name"),
        counterparty_iban=event.get("counterparty_iban"),
    )
    if hit is None:
        return
    if hit.set_kind:
        fm.kind = hit.set_kind
    if hit.set_merchant:
        fm.merchant = hit.set_merchant
    if hit.auto_aprobar:
        fm.estado = "aprobado"
    if hit.categoria_id:
        session.add(Classification(
            movement_id=fm.id,
            categoria_id=hit.categoria_id,
            subtipo=hit.subtipo,
            origen="rule",
            confianza=Decimal("0.99"),
            explicacion=hit.explicacion,
            vigente=True,
        ))


def _create_asset_transaction(
    session,
    fm: FinancialMovement,
    event: dict,
    *,
    source_file_id: int | None = None,
) -> int | None:
    """Crea AssetTransaction si el evento lleva datos de activo."""
    if not event.get("asset_symbol") or event.get("shares") is None:
        return None
    symbol = event["asset_symbol"]
    asset_name = event.get("asset_name")
    asset_class = event.get("asset_class") or "accion"
    shares = event.get("shares")
    price = event.get("price")
    fee = event.get("fee") or Decimal("0")
    if shares is None:
        return None
    if price is None:
        # Los dividendos no traen precio unitario; el número de acciones sí es
        # necesario para mantener la posición. El precio 0 no altera el coste.
        if fm.kind == "dividendo":
            price = Decimal("0")
        else:
            return None

    asset = (
        session.query(Asset)
        .filter((Asset.isin == symbol) | (Asset.symbol == symbol))
        .first()
    )
    if not asset:
        asset = Asset(
            isin=symbol if len(symbol) == 12 else None,
            symbol=symbol,
            nombre=asset_name,
            asset_class=asset_class,
        )
        session.add(asset)
        session.flush()

    kind_map = {
        "inversion_compra": "compra",
        "inversion_venta": "venta",
        "aporte_activo": "aporte",
        "dividendo": "dividendo_accion",
    }
    at = AssetTransaction(
        asset_id=asset.id,
        account_id=fm.account_id,
        source_file_id=source_file_id,
        movement_id=fm.id,
        tipo=kind_map.get(fm.kind, "compra"),
        shares=abs(shares) if shares else Decimal("0"),
        price=price,
        fee=fee,
        tax=event.get("tax"),
        moneda=event.get("currency"),
        fecha=fm.value_date,
    )
    session.add(at)
    return asset.id


def _recalc_position(session, asset_id: int) -> None:
    """Recalcula y persiste position_snapshot para un activo."""
    from sqlalchemy import func

    buys = (
        session.query(
            func.sum(AssetTransaction.shares),
            func.sum(AssetTransaction.shares * AssetTransaction.price),
            func.sum(AssetTransaction.fee),
        )
        .filter(
            AssetTransaction.asset_id == asset_id,
            AssetTransaction.tipo.in_(["compra", "aporte"]),
        )
        .first()
    )
    sells = (
        session.query(
            func.sum(AssetTransaction.shares),
            func.sum(AssetTransaction.shares * AssetTransaction.price),
            func.sum(AssetTransaction.fee),
        )
        .filter(
            AssetTransaction.asset_id == asset_id,
            AssetTransaction.tipo == "venta",
        )
        .first()
    )

    buy_shares = buys[0] or Decimal("0")
    buy_cost = buys[1] or Decimal("0")
    buy_fees = buys[2] or Decimal("0")
    sell_shares = abs(sells[0] or Decimal("0"))
    sell_revenue = sells[1] or Decimal("0")
    sell_fees = abs(sells[2] or Decimal("0"))

    total_shares = buy_shares - sell_shares
    total_fees = buy_fees + sell_fees

    # FIFO simplificado por coste medio: la base de coste de las unidades
    # vendidas se descuenta del coste restante. La ganancia realizada es
    # ingreso de venta - coste de lo vendido - comisiones de venta.
    avg_buy_price = buy_cost / buy_shares if buy_shares > 0 else Decimal("0")
    sold_cost_basis = avg_buy_price * sell_shares
    remaining_cost = buy_cost - sold_cost_basis
    if remaining_cost < 0:
        remaining_cost = Decimal("0")
    realized_pnl = (
        sell_revenue - sold_cost_basis - sell_fees
        if sell_shares > 0
        else Decimal("0")
    )

    avg_price = (
        remaining_cost / total_shares if total_shares > 0 else Decimal("0")
    )
    total_invested = remaining_cost + buy_fees

    existing = session.query(PositionSnapshot).filter_by(asset_id=asset_id).first()
    if existing:
        existing.cantidad = total_shares
        existing.coste_total = remaining_cost
        existing.precio_medio = avg_price
        existing.invertido = total_invested
        existing.comisiones = total_fees
        existing.ganancia_realizada = realized_pnl
        existing.calculado_en = datetime.utcnow()
    else:
        session.add(PositionSnapshot(
            asset_id=asset_id,
            cantidad=total_shares,
            coste_total=remaining_cost,
            precio_medio=avg_price,
            invertido=total_invested,
            comisiones=total_fees,
            ganancia_realizada=realized_pnl,
            calculado_en=datetime.utcnow(),
        ))


def _detect_l3_candidates(
    session,
    result: ImportResult,
    new_movement_ids: list[int],
    source_file_id: int,
) -> None:
    """Cola L3: compara movimientos de ficheros importados distintos.

    Los repetidos legítimos del mismo extracto (mismo día/importe pero dos
    compras distintas) no se comparan entre sí. Tampoco se comparan dos filas
    nuevas del mismo fichero. Solo un movimiento nuevo se compara con
    movimientos vistos en otros ficheros, que es donde tiene sentido buscar
    solapes entre extractos.

    No hace merge automático. Respeta pares ya resueltos (``mismo``/
    ``distinto``) y no duplica candidatos pendientes.
    """
    if not new_movement_ids:
        return

    new_movs = (
        session.query(FinancialMovement)
        .filter(FinancialMovement.id.in_(new_movement_ids))
        .all()
    )
    if not new_movs:
        return

    from datetime import timedelta


    min_date = min(m.value_date for m in new_movs)
    max_date = max(m.value_date for m in new_movs)

    has_other_source = (
        session.query(MovementSource.movement_id)
        .filter(
            MovementSource.movement_id == FinancialMovement.id,
            MovementSource.source_file_id != source_file_id,
        )
        .exists()
    )
    has_current_source = (
        session.query(MovementSource.movement_id)
        .filter(
            MovementSource.movement_id == FinancialMovement.id,
            MovementSource.source_file_id == source_file_id,
        )
        .exists()
    )
    candidates = (
        session.query(FinancialMovement)
        .filter(
            FinancialMovement.id.notin_(new_movement_ids),
            FinancialMovement.value_date >= min_date - timedelta(days=3),
            FinancialMovement.value_date <= max_date + timedelta(days=3),
            FinancialMovement.estado.in_(["pendiente", "aprobado"]),
            has_other_source,
            ~has_current_source,
        )
        .all()
    )
    # Nunca comparamos nuevos entre sí: dos filas del mismo extracto pueden ser
    # dos compras legítimas iguales del mismo día.
    pool = candidates

    known_pairs: set[tuple[int, int]] = set()
    resolved_pairs: set[tuple[int, int]] = set()
    for dc in session.query(DedupCandidate).all():
        pair = tuple(sorted((dc.movement_a, dc.movement_b)))
        if dc.estado in ("mismo", "distinto"):
            resolved_pairs.add(pair)
        else:
            known_pairs.add(pair)

    new_ids = set(new_movement_ids)
    emitted: set[tuple[int, int]] = set()
    for new_mov in new_movs:
        new_amount = abs(Decimal(str(new_mov.amount))) if new_mov.amount is not None else None
        for other in pool:
            if other.id == new_mov.id:
                continue
            # El par se evalúa una sola vez, con el nuevo como lado A.
            if other.id in new_ids:
                continue
            pair = tuple(sorted((new_mov.id, other.id)))
            if pair in resolved_pairs or pair in known_pairs or pair in emitted:
                continue
            if other.kind != new_mov.kind:
                continue
            if new_amount is None or other.amount is None:
                continue
            if abs(Decimal(str(other.amount))) != new_amount:
                continue
            # Las dos patas de un traspaso (−100 / +100) o el mismo cargo en
            # dos cuentas distintas no son duplicados.
            if (Decimal(str(other.amount)) < 0) != (Decimal(str(new_mov.amount)) < 0):
                continue
            if (
                new_mov.account_id is not None
                and other.account_id is not None
                and new_mov.account_id != other.account_id
            ):
                continue
            if (new_mov.currency or "EUR") != (other.currency or "EUR"):
                continue
            day_diff = abs((new_mov.value_date - other.value_date).days)
            if day_diff > 3:
                continue
            score = score_similarity(
                str(new_mov.value_date), str(other.value_date),
                new_mov.amount, other.amount,
                new_mov.merchant or "", other.merchant or "",
                new_mov.kind, other.kind,
            )
            if score < 0.8:
                continue
            session.add(DedupCandidate(
                movement_a=new_mov.id,
                movement_b=other.id,
                score=Decimal(str(round(score, 4))),
                motivo=f"scoring L3 (Δ{day_diff}d, mismo importe/kind)",
            ))
            emitted.add(pair)
            result.dup_candidates += 1
