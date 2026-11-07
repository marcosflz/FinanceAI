"""Helpers compartidos por los tests de ingesta/clasificación."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from src.db.session import _session
from src.ingest.agentic import ExtractedStatement
from src.ingest.trade_republic import TradeRepublicCsvParser
from src.models import (
    FinancialMovement,
    NormalizedEvent,
    RawRow,
    SourceFile,
)

CSV_HEADER = [
    "datetime", "date", "account_type", "category", "type", "asset_class",
    "name", "symbol", "shares", "price", "amount", "fee", "tax", "currency",
    "original_amount", "original_currency", "fx_rate", "description",
    "transaction_id", "counterparty_name", "counterparty_iban",
    "payment_reference", "mcc_code",
]


def tr_row(**overrides) -> dict:
    row = {key: "" for key in CSV_HEADER}
    row.update({
        "datetime": "2026-01-15T10:00:00.000000Z",
        "date": "2026-01-15",
        "account_type": "DEFAULT",
        "category": "CASH",
        "type": "CARD_TRANSACTION",
        "currency": "EUR",
        "description": "Compra tarjeta",
        "transaction_id": "txn-default",
    })
    row.update(overrides)
    return row


def write_tr_csv(path: Path, rows: list[dict], *, extra_newline: bool = False) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADER)
        writer.writeheader()
        writer.writerows(rows)
        if extra_newline:
            f.write("\n")
    return path


class TrParserExtractor:
    """Doble de test: usa el parser viejo solo como fixture determinista."""

    source = "trade_republic_csv"
    parser_version = "tr-csv-test"

    def extract(self, path: str | Path) -> ExtractedStatement:
        filepath = str(path)
        parser = TradeRepublicCsvParser()
        events = parser.parse(filepath)
        raw_rows: list[dict] = []
        with open(filepath, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                raw_rows.append({"row_index": index, "values": row})
        dates = [event["value_date"] for event in events if event.get("value_date")]
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=raw_rows,
            events=events,
            period_start=min(dates) if dates else None,
            period_end=max(dates) if dates else None,
        )


def make_movement(
    *,
    merchant: str = "MERCHANT",
    kind: str = "gasto",
    amount=Decimal("-10.00"),
    value_date: date | None = None,
    mcc_code: str | None = None,
    broker_type: str = "CASH_CARD_TRANSACTION",
    description: str = "",
    estado: str = "pendiente",
    source_txn_id: str | None = None,
    account_id: int | None = None,
    currency: str = "EUR",
    original_amount=None,
    original_currency: str | None = None,
) -> tuple[int, int]:
    """Crea SourceFile/RawRow/Event/Movement y devuelve (movement_id, event_id)."""
    value_date = value_date or date(2026, 1, 15)
    with _session() as s:
        sf = s.query(SourceFile).first()
        if sf is None:
            sf = SourceFile(
                source="test", filename="test.csv", file_hash="f" * 64,
                parser_version="test-1.0", status="parsed",
            )
            s.add(sf)
            s.flush()
        index = s.query(RawRow).filter_by(source_file_id=sf.id).count()
        payload = json.dumps({"test": True, "n": index})
        rr = RawRow(
            source_file_id=sf.id,
            row_index=index,
            payload=payload,
            row_hash=hashlib.sha256(payload.encode()).hexdigest(),
        )
        s.add(rr)
        s.flush()
        fp = hashlib.sha256(
            f"{value_date}|{amount}|{kind}|{merchant}|{index}".encode()
        ).hexdigest()
        ne = NormalizedEvent(
            raw_row_id=rr.id,
            source_txn_id=source_txn_id,
            broker_type=broker_type,
            kind=kind,
            value_date=value_date,
            amount=amount,
            currency=currency,
            original_amount=original_amount,
            original_currency=original_currency,
            mcc_code=mcc_code,
            description_raw=description,
            description_clean=description,
            fingerprint=fp,
        )
        s.add(ne)
        s.flush()
        fm = FinancialMovement(
            event_id=ne.id,
            account_id=account_id,
            kind=kind,
            direction="-" if amount is not None and amount < 0 else "+",
            amount=amount,
            currency=currency,
            value_date=value_date,
            estado=estado,
            merchant=merchant,
        )
        s.add(fm)
        s.flush()
        return fm.id, ne.id
