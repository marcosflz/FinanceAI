"""SQLite guarda ``Numeric`` como REAL: las sumas deben seguir siendo exactas
a la escala de la columna (las BD por usuario son SQLite)."""

from __future__ import annotations

import warnings
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select

from src.db.session import _session
from src.models import FinancialMovement, NormalizedEvent, RawRow, SourceFile


def test_sum_of_many_cents_is_exact(db):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with _session() as s:
            sf = SourceFile(source="t", filename="t", file_hash="1" * 64, parser_version="t")
            s.add(sf)
            s.flush()
            for i in range(2000):
                rr = RawRow(source_file_id=sf.id, row_index=i, payload="{}", row_hash=f"{i:064d}")
                s.add(rr)
                s.flush()
                ev = NormalizedEvent(
                    raw_row_id=rr.id,
                    broker_type="CASH_CARD_TRANSACTION",
                    kind="gasto",
                    value_date=date(2026, 1, 1),
                    amount=Decimal("-0.10"),
                    currency="EUR",
                    fingerprint=f"{i:064x}",
                )
                s.add(ev)
                s.flush()
                s.add(
                    FinancialMovement(
                        event_id=ev.id,
                        kind="gasto",
                        direction="-",
                        amount=Decimal("-0.10"),
                        amount_eur=Decimal("-0.10"),
                        currency="EUR",
                        value_date=date(2026, 1, 1),
                        estado="aprobado",
                    )
                )
        with _session() as s:
            total = s.scalar(select(func.sum(FinancialMovement.amount_eur)))
    assert total == Decimal("-200.0000")
