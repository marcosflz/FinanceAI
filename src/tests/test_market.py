import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

from src.market import normalize_currency, convert_price, convert_price_at, get_exchange_rate, _resolve_fx_pair
from src.market import _cache as _market_cache


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear the global market cache between tests to avoid collisions."""
    _market_cache.clear()


class TestNormalizeCurrency:
    def test_gbp_pence(self):
        assert normalize_currency("GBp") == ("GBP", 0.01)

    def test_gbx(self):
        assert normalize_currency("GBX") == ("GBP", 0.01)

    def test_euro(self):
        assert normalize_currency("EUR") == ("EUR", 1.0)

    def test_usd(self):
        assert normalize_currency("USD") == ("USD", 1.0)

    def test_cnh(self):
        assert normalize_currency("CNH") == ("CNY", 1.0)

    def test_empty(self):
        assert normalize_currency("") == ("EUR", 1.0)

    def test_none(self):
        assert normalize_currency(None) == ("EUR", 1.0)

    def test_gbp_real(self):
        assert normalize_currency("GBP") == ("GBP", 1.0)

    def test_unknown(self):
        assert normalize_currency("JPY") == ("JPY", 1.0)


class TestResolveFxPair:
    def test_direct_pair(self):
        # USD→EUR returns "EURUSD=X" (price of 1 EUR in USD)
        assert _resolve_fx_pair("USD", "EUR") == "EURUSD=X"

    def test_eur_to_usd(self):
        assert _resolve_fx_pair("EUR", "USD") == "USDEUR=X"

    def test_same_currency(self):
        assert _resolve_fx_pair("EUR", "EUR") is None


class TestConvertPrice:
    @patch("src.market._resolve_fx_rate")
    def test_same_currency(self, mock_rate):
        assert convert_price(100.0, "EUR", "EUR") == 100.0
        mock_rate.assert_not_called()

    @patch("src.market._resolve_fx_rate")
    def test_conversion(self, mock_rate):
        mock_rate.return_value = 1.08
        result = convert_price(100.0, "USD", "EUR")
        assert result is not None
        assert round(result, 2) == 92.59

    @patch("src.market._resolve_fx_rate")
    def test_conversion_failure(self, mock_rate):
        mock_rate.return_value = None
        assert convert_price(100.0, "ARS", "BOB") is None  # obscure pair → no cache collision

    def test_none_price(self):
        assert convert_price(None, "USD", "EUR") is None


class TestConvertPriceAt:
    @patch("src.market.get_exchange_rate_at")
    def test_same_currency(self, mock_rate_at):
        mock_rate_at.return_value = None
        dt = datetime(2026, 1, 15)
        result = convert_price_at(100.0, "EUR", "EUR", dt)
        assert result == 100.0
        mock_rate_at.assert_not_called()

    @patch("src.market.get_exchange_rate_at")
    def test_historical_conversion(self, mock_rate_at):
        mock_rate_at.return_value = 1.08
        dt = datetime(2026, 1, 15)
        result = convert_price_at(100.0, "USD", "EUR", dt)
        assert result is not None
        assert round(result, 2) == 92.59

    @patch("src.market.get_exchange_rate_at")
    def test_historical_failure(self, mock_rate_at):
        mock_rate_at.return_value = None
        dt = datetime(2026, 1, 15)
        assert convert_price_at(100.0, "USD", "EUR", dt) is None

    def test_none_price(self):
        assert convert_price_at(None, "USD", "EUR", datetime(2026, 1, 15)) is None


class TestGetExchangeRate:
    def test_same_currency(self):
        assert get_exchange_rate("EUR", "EUR") == 1.0

    @patch("src.market._resolve_fx_rate")
    def test_different_currency(self, mock_rate):
        mock_rate.return_value = 1.08
        result = get_exchange_rate("CHF", "NOK")  # obscure → avoid cache collisions
        assert result == 1.08
        mock_rate.assert_called_once_with("CHF", "NOK")

    @patch("src.market._resolve_fx_rate")
    def test_failure(self, mock_rate):
        mock_rate.return_value = None
        assert get_exchange_rate("MXN", "THB") is None
