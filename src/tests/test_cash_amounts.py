from decimal import Decimal

import pytest

from src.ingest_service import _movement_cash_amount


@pytest.mark.parametrize(
    ("broker_type", "amount", "fee", "tax", "expected"),
    [
        ("BUY", "-250.00", "-1.00", None, "-251.00"),
        ("SELL", "434.20", "-1.00", None, "433.20"),
        ("INTEREST_PAYMENT", "16.80", None, "-3.19", "13.61"),
        ("BENEFITS_SAVEBACK", "4.79", None, "-0.91", "3.88"),
    ],
)
def test_tabular_broker_cash_is_net(broker_type, amount, fee, tax, expected):
    event = {
        "_source": "csv",
        "broker_type": broker_type,
        "amount": Decimal(amount),
        "fee": Decimal(fee) if fee is not None else None,
        "tax": Decimal(tax) if tax is not None else None,
    }
    assert _movement_cash_amount(event) == Decimal(expected)


def test_pdf_amount_is_already_cash_net():
    event = {
        "_source": "pdf",
        "broker_type": "BUY",
        "amount": Decimal("433.20"),
        "fee": Decimal("-1.00"),
    }
    assert _movement_cash_amount(event) == Decimal("433.20")


def test_asset_delivery_has_no_cash_amount():
    assert _movement_cash_amount({
        "_source": "csv",
        "broker_type": "FREE_RECEIPT",
        "amount": None,
    }) is None
