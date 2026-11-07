"""
Parser legacy de Trade Republic (solo fixture de tests).

El pipeline de producción usa ``src/ingest/agentic.py``. Este módulo se
conserva temporalmente para los tests deterministas del formato TR; no debe
usarse desde la API ni desde nuevos imports.
"""

import csv
import hashlib
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from .base import BaseParser

PARSER_VERSION = "tr-csv-1.0"

_EXPECTED_HEADER = [
    "datetime", "date", "account_type", "category", "type", "asset_class",
    "name", "symbol", "shares", "price", "amount", "fee", "tax", "currency",
    "original_amount", "original_currency", "fx_rate", "description",
    "transaction_id", "counterparty_name", "counterparty_iban",
    "payment_reference", "mcc_code",
]

# Regex para limpiar description
_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
    re.IGNORECASE,
)
_IBAN_RE = re.compile(r'[A-Z]{2}\d{2}(?: ?\d{4}){3,7}(?: ?\d{1,4})?')
_TRAILING_NULL_RE = re.compile(r'\s*null\s*$', re.IGNORECASE)

KIND_MAP = {
    ("CASH", "CARD_TRANSACTION"): "gasto",
    ("CASH", "CARD_TRANSACTION_INTERNATIONAL"): "gasto",
    ("CASH", "TRANSFER_DIRECT_DEBIT_INBOUND"): "gasto",
    ("CASH", "BENEFITS_SAVEBACK"): "cashback",
    ("CASH", "INTEREST_PAYMENT"): "interes",
    ("CASH", "DIVIDEND"): "dividendo",
    ("TRADING", "BUY"): "inversion_compra",
    ("TRADING", "SELL"): "inversion_venta",
    ("DELIVERY", "FREE_RECEIPT"): "aporte_activo",
}


def _normalize_iban(value: str | None) -> str:
    """Normaliza un IBAN: mayúsculas y sin espacios/guiones."""
    if not value:
        return ""
    return re.sub(r'[\s-]+', '', value).upper()


def _extract_ibans(text: str | None) -> list[str]:
    """Extrae IBANs normalizados de un texto, sin duplicados."""
    if not text:
        return []
    result: list[str] = []
    for match in _IBAN_RE.finditer(text.upper()):
        iban = _normalize_iban(match.group())
        if 15 <= len(iban) <= 34 and iban not in result:
            result.append(iban)
    return result


def _clean_description(raw: str) -> str:
    """Limpia description: quita trailing null, UUIDs y redacta IBANs."""
    text = _TRAILING_NULL_RE.sub("", raw.strip())
    text = _UUID_RE.sub("[UUID]", text)
    text = _IBAN_RE.sub("[IBAN]", text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_description_for_fingerprint(desc: str) -> str:
    """Normaliza una description para incluir en fingerprint."""
    s = desc.upper()
    s = _UUID_RE.sub("", s)
    s = _IBAN_RE.sub("", s)
    s = re.sub(r'\bnull\b', '', s, flags=re.IGNORECASE)
    s = re.sub(r'[^A-Z0-9\s]', '', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _compute_fingerprint(
    value_date: str,
    amount: str | None,
    currency: str,
    kind: str,
    desc_clean: str,
) -> str:
    """SHA-256 canónico para dedup L2."""
    amt = "0"
    if amount and amount.strip():
        d = Decimal(amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        amt = str(d)
    nd = _normalize_description_for_fingerprint(desc_clean)
    raw = f"{value_date}|{amt}|{currency}|{kind}|{nd}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _truncate_ts(ts_str: str) -> datetime | None:
    """Convierte datetime ISO con Z a datetime (UTC)."""
    if not ts_str:
        return None
    ts_str = ts_str.strip()
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    # Remove trailing 'Z' if it's still there
    try:
        return datetime.fromisoformat(ts_str).replace(tzinfo=None)
    except Exception:
        return None


def _parse_amount(val: str) -> Decimal | None:
    if not val or not val.strip():
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


def _parse_shares(val: str) -> Decimal | None:
    if not val or not val.strip():
        return None
    try:
        return Decimal(val)
    except Exception:
        return None


def _parse_date(date_str: str) -> date | None:
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


class TradeRepublicCsvParser(BaseParser):
    """Parser para CSV descargado de Trade Republic."""

    source_name = "trade_republic_csv"

    def detect(self, header_lines: list[str], filename: str) -> bool:
        if not header_lines:
            return False
        first = header_lines[0].strip().lower()
        expected = {h.lower() for h in _EXPECTED_HEADER}
        actual = {h.strip('"').lower() for h in first.split(",")}
        if "transaction_id" in actual and "description" in actual:
            return len(expected & actual) >= 15
        return False

    def parse(self, filepath: str) -> list[dict]:
        events = []
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                event = self._row_to_event(raw)
                if event:
                    events.append(event)
        return events

    def _row_to_event(self, raw: dict) -> dict | None:
        cat = (raw.get("category") or "").strip()
        typ = (raw.get("type") or "").strip()

        kind = KIND_MAP.get((cat, typ))
        if kind is None:
            # Transferencias: por signo + detección de cuenta propia
            if cat == "CASH" and typ.startswith("TRANSFER_"):
                kind = "transferencia_interna"  # provisional, se refina en ingesta_service
            else:
                kind = "gasto"  # fallback

        value_date_str = (raw.get("date") or "").strip()
        value_date = _parse_date(value_date_str)

        occurred_at = _truncate_ts(raw.get("datetime"))

        amount = _parse_amount(raw.get("amount"))
        fee = _parse_amount(raw.get("fee"))
        tax_val = _parse_amount(raw.get("tax"))
        currency = (raw.get("currency") or "EUR").strip()
        original_amount = _parse_amount(raw.get("original_amount"))
        original_currency = (raw.get("original_currency") or "").strip() or None
        fx_rate = _parse_amount(raw.get("fx_rate"))

        asset_symbol = (raw.get("symbol") or "").strip() or None
        asset_name = (raw.get("name") or "").strip() or None
        asset_class = (raw.get("asset_class") or "").strip() or None

        shares = _parse_shares(raw.get("shares"))
        price = _parse_amount(raw.get("price"))

        counterparty_name = (raw.get("counterparty_name") or "").strip() or None
        counterparty_iban = _normalize_iban(raw.get("counterparty_iban")) or None
        mcc_code = (raw.get("mcc_code") or "").strip() or None
        source_txn_id = (raw.get("transaction_id") or "").strip() or None

        description_raw = (raw.get("description") or "").strip()

        # IMPORTANTE: extraer IBANs de description ANTES de redactar. El CSV
        # suele dejarlos solo en la descripción (191 transferencias), y el
        # texto redactado ([IBAN]) no sirve para resolver cuentas propias.
        if not counterparty_iban:
            ibans = _extract_ibans(description_raw)
            if ibans:
                counterparty_iban = ibans[0]

        description_clean = _clean_description(description_raw)

        fingerprint = _compute_fingerprint(
            value_date_str,
            raw.get("amount"),
            currency or "EUR",
            kind,
            description_clean,
        )

        event = {
            "source_txn_id": source_txn_id,
            "broker_type": f"{cat}_{typ}",
            "kind": kind,
            "occurred_at": occurred_at,
            "value_date": value_date,
            "amount": amount,
            "currency": currency,
            "fee": fee,
            "tax": tax_val,
            "original_amount": original_amount,
            "original_currency": original_currency,
            "fx_rate": fx_rate,
            "asset_symbol": asset_symbol,
            "asset_name": asset_name,
            "asset_class": asset_class,
            "shares": shares,
            "price": price,
            "counterparty_name": counterparty_name,
            "counterparty_iban": counterparty_iban,
            "mcc_code": mcc_code,
            "description_raw": description_raw,
            "description_clean": description_clean,
            "fingerprint": fingerprint,
        }
        return event
