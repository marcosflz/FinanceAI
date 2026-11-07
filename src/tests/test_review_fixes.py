"""Regresiones de la revisión 2026-11-04 (ingesta, conciliación, KPIs, cartera)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.db.session import _session
from src.ingest.agentic import (
    StatementMapping,
    _broker_type,
    _build_extracted,
    _guess_bank,
    _infer_kind,
    _normalise_kind,
    _row_to_event,
)
from src.ingest.accounts import is_card_transaction, is_transfer_type
from src.ingest.internal_transfers import link_internal_transfers
from src.ingest.text import parse_decimal
from src.ingest_service import _movement_cash_amount
from src.models import Account, FinancialMovement, MovementLink
from src.tests.helpers import make_movement

from .test_api_v3_data import _login, client  # noqa: F401  (fixture)


# ── Extracción ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "kind", "expected"),
    [
        ("SELL", "inversion_venta", "CASH_SELL"),
        ("INTEREST_PAYMENT", "interes", "CASH_INTEREST_PAYMENT"),
        ("TRANSFER_DIRECT_DEBIT_INBOUND", "gasto", "CASH_TRANSFER_DIRECT_DEBIT_INBOUND"),
        ("CARD_TRANSACTION", "gasto", "CASH_CARD_TRANSACTION"),
        ("Card Payment", "gasto", "CASH_CARD_PAYMENT"),
        ("TRANSFER", "transferencia_interna", "CASH_TRANSFER"),
        ("Recibida", "transferencia_interna", "CASH_TRANSFER_RECIBIDA"),
        ("gasto", "gasto", "AGENTIC_STATEMENT"),
        (None, "inversion_compra", "AGENTIC_TRADE"),
    ],
)
def test_broker_type_keeps_source_type_code(raw, kind, expected):
    assert _broker_type(kind, "x", None, raw_type=raw) == expected


def test_tabular_sell_is_netted_with_fee():
    mapping = StatementMapping(
        date_column="date", amount_column="amount", kind_column="type",
        asset_symbol_column="symbol", shares_column="shares",
        price_column="price", fee_column="fee", tax_column="tax",
        description_column="description",
    )
    event = _row_to_event(
        {
            "date": "2026-01-13", "amount": "434.20", "type": "SELL",
            "symbol": "NL0000235190", "shares": "-2", "price": "217.10",
            "fee": "-1.00", "tax": "", "description": "Sell trade",
        },
        mapping,
        source="csv",
    )
    assert event["kind"] == "inversion_venta"
    assert _movement_cash_amount(event) == Decimal("433.20")


def test_missing_trade_price_is_derived_from_amount():
    mapping = StatementMapping(
        date_column="date", amount_column="amount",
        asset_symbol_column="symbol", shares_column="shares",
    )
    event = _row_to_event(
        {"date": "2026-01-02", "amount": "-50.00", "symbol": "IE00B4ND3602", "shares": "2"},
        mapping,
        source="csv",
    )
    assert event["price"] == Decimal("25")


def test_transfer_and_card_predicates_understand_bank_codes():
    assert is_transfer_type("CASH_TRANSFER")
    assert is_transfer_type("CASH_TRANSFER_INSTANT_INBOUND")
    assert is_transfer_type("CASH_TOPUP")
    assert not is_transfer_type("CASH_TRANSFER_DIRECT_DEBIT_INBOUND")
    assert is_card_transaction("CASH_CARD_PAYMENT")
    assert is_card_transaction("CASH_CARD_TRANSACTION_INTERNATIONAL")
    assert not is_card_transaction("CASH_BUY")


@pytest.mark.parametrize(
    ("description", "amount", "expected"),
    [
        ("TAXI MADRID", "-12.00", "gasto"),
        ("Starbucks Coffee", "-4.50", "gasto"),
        ("Pinterest Ads", "-9.99", "gasto"),
        ("Comisión mantenimiento", "-3.00", "fee"),
        ("Tax refund", "50.00", "impuesto"),
        ("Interest payment", "1.20", "interes"),
    ],
)
def test_infer_kind_matches_whole_words(description, amount, expected):
    assert _infer_kind(description, Decimal(amount), None, None, None) == expected


def test_exchange_type_is_currency_exchange():
    assert _normalise_kind("EXCHANGE") == "cambio_divisa"


def test_descending_statement_balance_chain():
    # Extracto del más reciente al más antiguo: apertura 100 → 90 → 140.
    events = [
        {"value_date": date(2026, 1, 3), "amount": Decimal("50"), "currency": "EUR",
         "_balance_after": Decimal("140"), "_row_index": 0},
        {"value_date": date(2026, 1, 2), "amount": Decimal("-10"), "currency": "EUR",
         "_balance_after": Decimal("90"), "_row_index": 1},
    ]
    extracted = _build_extracted(
        events=events, raw_rows=[{}, {}], parser_version="t", bank=None,
        account_name=None, account_iban=None, opening=None, closing=None,
        issues=[], metadata={"currency": "EUR"},
    )
    assert extracted.opening_balance == Decimal("100")
    assert extracted.closing_balance == Decimal("140")
    assert not [issue for issue in extracted.issues if "descuadrado" in issue]


@pytest.mark.parametrize(
    ("value", "decimal_sep", "expected"),
    [
        ("1.234,56", None, "1234.56"),
        ("1,234.56", None, "1234.56"),
        ("1.234", ",", "1234"),
        ("1,234", ".", "1234"),
        ("1.234,56", ".", "1234.56"),
        ("1,5", ".", "1.5"),
        ("12,50-", None, "-12.50"),
        ("(7,95)", None, "-7.95"),
        ("12.00 GBP", None, "12.00"),
    ],
)
def test_parse_decimal_separators(value, decimal_sep, expected):
    assert parse_decimal(value, decimal_sep) == Decimal(expected)


def test_guess_bank_uses_whole_words():
    assert _guess_bank("Online BANKING · TRADING account · SAVINGS") is None
    assert _guess_bank("ING Direct extracto") == "ING"


# ── Conciliación de transferencias ───────────────────────────────────────


def _two_accounts():
    with _session() as s:
        tr = s.query(Account).filter_by(nombre="Trade Republic Default").one()
        revolut = s.query(Account).filter_by(nombre="Revolut").one()
        return tr.id, revolut.id


def test_amount_only_match_between_card_and_bizum_is_not_linked(db):
    tr_id, revolut_id = _two_accounts()
    make_movement(
        account_id=tr_id, amount=Decimal("9.99"), kind="ingreso",
        broker_type="CASH_TRANSFER_INSTANT_INBOUND", merchant="AMIGO",
        description="Incoming transfer from Pepe",
    )
    make_movement(
        account_id=revolut_id, amount=Decimal("-9.99"), kind="gasto",
        broker_type="CASH_CARD_PAYMENT", merchant="NETFLIX", description="Netflix",
    )
    make_movement(
        account_id=revolut_id, amount=Decimal("-9.99"), kind="gasto",
        broker_type="CASH_CARD_PAYMENT", merchant="SPOTIFY", description="Spotify",
    )
    stats = link_internal_transfers()
    assert stats["linked"] == 0
    with _session() as s:
        assert s.query(MovementLink).count() == 0


def test_investment_buy_is_never_linked_as_transfer(db):
    tr_id, revolut_id = _two_accounts()
    buy_id, _ = make_movement(
        account_id=tr_id, amount=Decimal("-50.00"), kind="inversion_compra",
        broker_type="CASH_BUY", merchant="Revolut fund", description="Revolut",
    )
    make_movement(
        account_id=revolut_id, amount=Decimal("50.00"), kind="ingreso",
        broker_type="CASH_TRANSFER", merchant="Trade Republic",
        description="Trade Republic",
    )
    link_internal_transfers()
    with _session() as s:
        assert s.query(FinancialMovement).filter_by(id=buy_id).one().kind == "inversion_compra"


# ── API: rutas legacy, KPIs, duplicados, cartera ─────────────────────────


def test_legacy_unauthenticated_routes_are_gone(client):  # noqa: F811
    for method, path in (
        ("get", "/api/v2/movements"),
        ("get", "/api/imports"),
        ("get", "/api/documents"),
        ("get", "/api/config"),
        ("get", "/api/pockets"),
    ):
        assert getattr(client, method)(path).status_code == 404, path


def _add_movement(kind: str, amount: str, merchant: str) -> int:
    with _session() as s:
        tr = s.query(Account).filter_by(nombre="Trade Republic").one()
        account_id = tr.id
    movement_id, _ = make_movement(
        account_id=account_id, amount=Decimal(amount), kind=kind,
        merchant=merchant, value_date=date(2026, 1, 5),
    )
    return movement_id


def test_kpis_sign_refunds_and_count_fees(client):  # noqa: F811
    headers = _login(client)
    _add_movement("gasto", "10.00", "REEMBOLSO")   # devolución con kind gasto
    _add_movement("fee", "-2.00", "COMISION")
    body = client.get("/api/v3/analytics/summary", headers=headers).json()
    # Fixture: -38.06 gasto. Reembolso +10 reduce; comisión -2 suma.
    assert body["gastos"] == pytest.approx(30.06)
    cashflow = client.get(
        "/api/v3/analytics/cashflow", params={"all": True}, headers=headers
    ).json()["items"]
    assert sum(item["gastos"] for item in cashflow) == pytest.approx(30.06)


def test_confirmed_duplicate_leaves_kpis(client):  # noqa: F811
    from src.models import DedupCandidate

    headers = _login(client)
    with _session() as s:
        original = s.query(FinancialMovement).filter_by(merchant="AHORRAMAS").one()
        original_id = original.id
    duplicate_id = _add_movement("gasto", "-38.06", "AHORRAMAS")
    with _session() as s:
        candidate = DedupCandidate(
            movement_a=duplicate_id, movement_b=original_id,
            score=Decimal("0.9"), motivo="test",
        )
        s.add(candidate)
        s.flush()
        candidate_id = candidate.id
    before = client.get("/api/v3/analytics/summary", headers=headers).json()["gastos"]
    response = client.post(
        f"/api/v3/dedup-candidates/{candidate_id}/resolve",
        json={"resolution": "mismo"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    after = client.get("/api/v3/analytics/summary", headers=headers).json()["gastos"]
    assert before == pytest.approx(76.12)
    assert after == pytest.approx(38.06)
    with _session() as s:
        assert s.query(FinancialMovement).filter_by(id=duplicate_id).one().estado == "duplicado"


def test_clearing_category_does_not_touch_memory(client):  # noqa: F811
    headers = _login(client)
    with _session() as s:
        movement_id = s.query(FinancialMovement).filter_by(merchant="AHORRAMAS").one().id
    response = client.patch(
        f"/api/v3/movements/{movement_id}",
        json={"categoria_id": None, "nota": None},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    bad = client.patch(
        f"/api/v3/movements/{movement_id}", json={"estado": "borrado"}, headers=headers
    )
    assert bad.status_code == 422


def test_reapply_patterns_never_moves_movements_between_accounts(client):  # noqa: F811
    headers = _login(client)
    with _session() as s:
        other = Account(nombre="Banco B", tipo="efectivo_externa", es_propia=True)
        s.add(other)
        s.flush()
        other_id = other.id
    movement_id, _ = make_movement(account_id=other_id, amount=Decimal("-5"), merchant="X")
    with _session() as s:
        tr_id = s.query(Account).filter_by(nombre="Trade Republic").one().id
    response = client.post(f"/api/v3/accounts/{tr_id}/reapply-patterns", headers=headers)
    assert response.status_code == 200, response.text
    with _session() as s:
        assert s.query(FinancialMovement).filter_by(id=movement_id).one().account_id == other_id


def test_portfolio_dividends_use_gross_minus_tax(client):  # noqa: F811
    from src.models import Asset, AssetTransaction, NormalizedEvent

    headers = _login(client)
    movement_id = _add_movement("dividendo", "0.20", "MSFT")
    with _session() as s:
        movement = s.query(FinancialMovement).filter_by(id=movement_id).one()
        s.query(NormalizedEvent).filter_by(id=movement.event_id).one().amount = Decimal("0.20")
        asset = Asset(
            symbol="US5949181045", isin="US5949181045", nombre="Microsoft",
            asset_class="STOCK",
        )
        s.add(asset)
        s.flush()
        s.add(AssetTransaction(
            asset_id=asset.id, account_id=movement.account_id, movement_id=movement_id,
            tipo="dividendo_accion", shares=Decimal("0.25"), price=Decimal("0"),
            fee=Decimal("0"), tax=Decimal("-0.06"), moneda="EUR",
            fecha=date(2026, 3, 12),
        ))
    body = client.get("/api/v3/portfolio/summary", headers=headers).json()
    assert body["dividendos"] == pytest.approx(0.14)


class _SameChargeExtractor:
    source = "test"
    parser_version = "test-1"

    def extract(self, path):
        from src.ingest.agentic import ExtractedStatement
        from src.ingest.text import compute_fingerprint

        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=[{"row_index": 0, "values": {}}],
            events=[{
                "source_txn_id": None,
                "broker_type": "CASH_CARD_PAYMENT",
                "kind": "gasto",
                "value_date": date(2026, 2, 1),
                "amount": Decimal("-9.99"),
                "currency": "EUR",
                "description_raw": "Spotify",
                "description_clean": "Spotify",
                "fingerprint": compute_fingerprint(
                    date(2026, 2, 1), Decimal("-9.99"), "EUR", "gasto", "Spotify"
                ),
            }],
        )


def test_same_charge_in_two_accounts_is_not_deduplicated(db, tmp_path):
    from src.ingest_service import process_import
    from src.models import DedupCandidate

    tr_id, revolut_id = _two_accounts()
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_text("a")
    second.write_text("b")
    one = process_import(str(first), account_id=tr_id, extractor=_SameChargeExtractor())
    two = process_import(str(second), account_id=revolut_id, extractor=_SameChargeExtractor())
    assert one.new_count == 1
    assert two.new_count == 1 and two.seen_count == 0
    with _session() as s:
        assert s.query(DedupCandidate).count() == 0
