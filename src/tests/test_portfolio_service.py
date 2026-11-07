from datetime import date
from decimal import Decimal

from src.portfolio_service import (
    AssetOperation,
    OpeningPosition,
    PortfolioSnapshot,
    SnapshotPosition,
    rebuild_asset,
    rebuild_portfolio,
)


def op(
    operation_id: str,
    kind: str,
    day: int,
    quantity: str,
    price: str = "0",
    fee: str = "0",
    tax: str = "0",
    sequence: int = 0,
) -> AssetOperation:
    return AssetOperation(
        id=operation_id,
        asset_id="TEST",
        kind=kind,  # type: ignore[arg-type]
        operation_date=date(2026, 1, day),
        quantity=Decimal(quantity),
        price=Decimal(price),
        fee=Decimal(fee),
        tax=Decimal(tax),
        sequence=sequence,
    )


def test_buy_fee_increases_cost():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "BUY", 1, "1", "250", "-1")],
    )
    assert result.quantity == Decimal("1")
    assert result.cost_total == Decimal("251")


def test_fifo_consumes_first_lot_and_calculates_realized_pnl():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[
            op("1", "BUY", 1, "1", "100"),
            op("2", "BUY", 2, "1", "120"),
            op("3", "SELL", 3, "1", "150", "-1"),
        ],
    )
    assert result.quantity == Decimal("1")
    assert result.cost_total == Decimal("120")
    assert result.realized_pnl == Decimal("49")
    assert result.realized_complete


def test_order_of_input_does_not_change_fifo_result():
    operations = [
        op("3", "SELL", 3, "1", "150", "-1"),
        op("1", "BUY", 1, "1", "100"),
        op("2", "BUY", 2, "1", "120"),
    ]
    forward = rebuild_asset(asset_id="TEST", operations=operations)
    reverse = rebuild_asset(asset_id="TEST", operations=list(reversed(operations)))
    assert forward.as_dict() == reverse.as_dict()


def test_unknown_opening_cost_is_partial_not_zero():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "BUY", 5, "0.5", "100")],
        opening=OpeningPosition(
            asset_id="TEST",
            as_of_date=date(2026, 1, 1),
            quantity=Decimal("1"),
            cost_total=None,
            cost_status="unknown",
        ),
    )
    assert result.quantity == Decimal("1.5")
    assert result.cost_total == Decimal("50")
    assert result.cost_known_quantity == Decimal("0.5")
    assert result.cost_unknown_quantity == Decimal("1")
    assert result.cost_coverage == Decimal("0.3333333333333333333333333333")
    assert result.cost_complete is False
    assert result.pnl_unrealized is None
    assert any(issue.code == "unknown_cost_basis" for issue in result.issues)


def test_opening_cutoff_does_not_double_count_prior_operations():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[
            op("1", "BUY", 2, "1", "100"),
            op("2", "BUY", 7, "1", "120"),
        ],
        opening=OpeningPosition(
            asset_id="TEST",
            as_of_date=date(2026, 1, 6),
            quantity=Decimal("2"),
            cost_total=Decimal("200"),
            cost_status="known",
            source="snapshot",
        ),
    )
    assert result.quantity == Decimal("3")
    assert result.cost_total == Decimal("320")


def test_snapshot_quantity_and_value_reconciliation():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "BUY", 1, "1", "100")],
        snapshot_position=SnapshotPosition(
            asset_id="TEST",
            quantity=Decimal("1.5"),
            price=Decimal("120"),
            value=Decimal("180"),
            price_date=date(2026, 1, 31),
        ),
    )
    assert result.quantity_difference == Decimal("-0.5")
    assert result.market_value == Decimal("180")
    assert result.pnl_unrealized is None
    assert any(issue.code == "snapshot_quantity_mismatch" for issue in result.issues)


def test_snapshot_value_tolerates_rounded_unit_price():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[],
        opening=OpeningPosition(
            asset_id="TEST",
            as_of_date=date(2026, 1, 1),
            quantity=Decimal("98.668467"),
            cost_status="unknown",
        ),
        snapshot_position=SnapshotPosition(
            asset_id="TEST",
            quantity=Decimal("98.668467"),
            price=Decimal("16.80"),
            value=Decimal("1657.27"),
            price_date=date(2026, 11, 2),
        ),
    )
    assert not any(
        issue.code == "snapshot_value_mismatch" for issue in result.issues
    )


def test_known_cost_gets_market_pnl():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "BUY", 1, "1", "100")],
        snapshot_position=SnapshotPosition(
            asset_id="TEST",
            quantity=Decimal("1"),
            price=Decimal("120"),
            value=Decimal("120"),
            price_date=date(2026, 1, 31),
        ),
    )
    assert result.pnl_unrealized == Decimal("20")
    assert not any(issue.code == "snapshot_quantity_mismatch" for issue in result.issues)


def test_free_receipt_uses_document_value_as_known_cost():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "FREE_RECEIPT", 1, "0.5", "100")],
    )
    assert result.quantity == Decimal("0.5")
    assert result.cost_total == Decimal("50")
    assert result.cost_complete


def test_oversold_creates_negative_position_issue():
    result = rebuild_asset(
        asset_id="TEST",
        operations=[op("1", "SELL", 1, "2", "100")],
    )
    assert result.quantity == Decimal("-2")
    assert any(issue.code == "position_oversold" for issue in result.issues)
    assert any(issue.code == "negative_position" for issue in result.issues)


def test_portfolio_snapshot_without_operations_reports_missing_opening():
    result = rebuild_portfolio(
        operations=[],
        snapshot=PortfolioSnapshot(
            snapshot_date=date(2026, 11, 2),
            positions=(
                SnapshotPosition(
                    asset_id="AMZN",
                    quantity=Decimal("1"),
                    price=Decimal("200"),
                    value=Decimal("200"),
                ),
            ),
            cash_declared=Decimal("100"),
        ),
        cash_calculated=Decimal("50"),
    )
    codes = {issue["code"] for issue in result["incidencias"]}
    assert "missing_opening_position" in codes
    assert "cash_snapshot_difference" in codes
    assert result["cash_difference"] == "50"
