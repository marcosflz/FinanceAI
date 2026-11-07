from datetime import date
from decimal import Decimal
from pathlib import Path
import subprocess

import pytest

from src.ingest.portfolio_snapshot import (
    PortfolioSnapshotDraft,
    SnapshotPositionDraft,
    parse_trade_republic_snapshot,
)

ROOT = Path(__file__).resolve().parents[2]


def test_net_worth_snapshot_parses_positions_without_inline_units():
    text = """
    EXTRACTO DEL PATRIMONIO NETO
    a 02.11.2026
    Cuenta de valores 5.741,86
    Wallet Crypto 355,42
    Efectivo 13.979,44
    TOTAL 20.076,72 EUR
    CUENTA DE VALORES
    3,082221 unidades Take-Two Interactive Softw.Inc 172,10 530,45
    02.11.2026
    ISIN: US8740541094
    19,477411 Physical Gold USD (Acc) 68,19 1.328,16
    unidades
    ISIN: IE00B4ND3602
    WALLET CRYPTO
    0,031066 unidades Ethereum 2.005,91 62,32
    ETH 02.11.2026
    """
    draft = parse_trade_republic_snapshot(text)
    assert draft is not None
    assert draft.snapshot_date == date(2026, 11, 2)
    assert draft.securities_value == Decimal("5741.86")
    assert draft.crypto_value == Decimal("355.42")
    assert draft.cash_declared == Decimal("13979.44")
    assert draft.total_declared == Decimal("20076.72")
    assert [(position.symbol, position.quantity) for position in draft.positions] == [
        ("US8740541094", Decimal("3.082221")),
        ("IE00B4ND3602", Decimal("19.477411")),
        ("ETH", Decimal("0.031066")),
    ]


def test_crypto_snapshot_preserves_explicit_purchase_cost():
    text = """
    EXTRACTO DE CRIPTOMONEDAS
    a fecha 06.01.2026
    VALOR NOMINAL NOMBRE DEL INSTRUMENTO PRECIO POR ACCIÓN PRECIO DE COMPRA EN EUR GANANCIA / PÉRDIDA COTIZACIÓN EN EUR
    0,003075 tít. Bitcoin (Bitcoin) 79.710,61 231,05 14,06 245,11
    06.01.2026 6,09%
    VALORES DE MERCADO TOTALES: 245,11 €
    """
    draft = parse_trade_republic_snapshot(text)
    assert draft is not None
    assert draft.doc_type == "crypto_snapshot"
    assert draft.opening_candidate
    position = draft.positions[0]
    assert position.symbol == "BTC"
    assert position.cost_total == Decimal("231.05")
    assert position.pnl_declared == Decimal("14.06")


def test_snapshot_import_persists_valuation_without_movements(db, tmp_path, monkeypatch):
    from src.db.session import _session
    from src.ingest_service import process_import
    from src.models import (
        Account,
        AssetOpeningPosition,
        FinancialMovement,
        PortfolioSnapshot,
        PortfolioSnapshotPosition,
    )

    draft = PortfolioSnapshotDraft(
        snapshot_date=date(2026, 11, 2),
        bank="Trade Republic",
        doc_type="net_worth_snapshot",
        custody_ref="portfolio",
        securities_value=Decimal("530.45"),
        crypto_value=Decimal("62.32"),
        cash_declared=Decimal("100"),
        total_declared=Decimal("692.77"),
        positions=[
            SnapshotPositionDraft(
                name="Take-Two",
                quantity=Decimal("3.082221"),
                price=Decimal("172.10"),
                value=Decimal("530.45"),
                asset_isin="US8740541094",
                asset_symbol="US8740541094",
                asset_class="stock",
                price_date=date(2026, 11, 2),
            ),
            SnapshotPositionDraft(
                name="Ethereum",
                quantity=Decimal("0.031066"),
                price=Decimal("2005.91"),
                value=Decimal("62.32"),
                asset_symbol="ETH",
                asset_class="cripto",
                price_date=date(2026, 11, 2),
            ),
        ],
    )
    path = tmp_path / "snapshot.pdf"
    path.write_bytes(b"fake pdf")
    monkeypatch.setattr(
        "src.ingest_service.read_portfolio_snapshot", lambda _: draft
    )

    result = process_import(str(path), original_filename="snapshot.pdf")
    assert result.account_match["status"] == "match"
    with _session() as s:
        account = s.query(Account).filter_by(nombre="Trade Republic Default").one()
        assert result.account_id == account.id
        snapshot = s.query(PortfolioSnapshot).one()
        assert snapshot.snapshot_date == date(2026, 11, 2)
        assert snapshot.cash_declared == Decimal("100")
        assert s.query(PortfolioSnapshotPosition).count() == 2
        assert s.query(AssetOpeningPosition).count() == 0
        assert s.query(FinancialMovement).count() == 0


def test_explicit_crypto_snapshot_becomes_opening_with_known_cost(
    db, tmp_path, monkeypatch
):
    from src.db.session import _session
    from src.ingest_service import process_import
    from src.models import AssetOpeningPosition

    draft = PortfolioSnapshotDraft(
        snapshot_date=date(2026, 1, 6),
        bank="Trade Republic",
        doc_type="crypto_snapshot",
        custody_ref="crypto",
        crypto_value=Decimal("245.11"),
        total_declared=Decimal("245.11"),
        positions=[
            SnapshotPositionDraft(
                name="Bitcoin",
                quantity=Decimal("0.003075"),
                price=Decimal("79710.61"),
                value=Decimal("245.11"),
                asset_symbol="BTC",
                asset_class="cripto",
                cost_total=Decimal("231.05"),
            ),
        ],
    )
    path = tmp_path / "crypto.pdf"
    path.write_bytes(b"fake crypto pdf")
    monkeypatch.setattr(
        "src.ingest_service.read_portfolio_snapshot", lambda _: draft
    )
    result = process_import(str(path), original_filename="crypto.pdf")
    with _session() as s:
        opening = s.query(AssetOpeningPosition).one()
        assert opening.quantity == Decimal("0.003075")
        assert opening.cost_total == Decimal("231.05")
        assert opening.cost_status == "known"
        assert result.account_id == opening.account_id


@pytest.mark.skipif(
    not (ROOT / "golden" / "files" / "Patrimonio neto.pdf").exists(),
    reason="documento personal no versionado",
)
def test_real_net_worth_document_internal_totals():
    text = subprocess.run(
        ["pdftotext", "-layout", str(ROOT / "golden" / "files" / "Patrimonio neto.pdf"), "-"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    draft = parse_trade_republic_snapshot(text)
    assert draft is not None
    assert len(draft.positions) == 11
    assert draft.securities_value == Decimal("5741.86")
    assert draft.crypto_value == Decimal("355.42")
    assert draft.cash_declared == Decimal("13979.44")
    assert draft.total_declared == Decimal("20076.72")
    assert sum((position.value for position in draft.positions), Decimal("0")) == (
        draft.securities_value + draft.crypto_value
    )
