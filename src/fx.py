"""Conversión de importes a EUR con fuente y fecha trazables.

El tipo de cambio histórico no cae silenciosamente al cambio actual: si no hay
dato para una fecha financiera, devuelve ``None`` y la importación lo marca para
revisión.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from . import market

_RATE_CACHE: dict[tuple[str, str], Decimal | None] = {}
_RATE_EPS = Decimal("0.000000000001")


@dataclass(frozen=True)
class EurRate:
    rate: Decimal
    rate_date: date
    source: str = "historical"


def _cached_rate(currency: str, value_date: date) -> Decimal | None:
    key = (currency, value_date.isoformat())
    if key not in _RATE_CACHE:
        _RATE_CACHE[key] = _historical_rate(currency, value_date)
    return _RATE_CACHE[key]


def _historical_rate(currency: str, value_date: date) -> Decimal | None:
    direct = market._resolve_fx_pair(currency, "EUR")
    if not direct:
        return None
    start = datetime.combine(value_date - timedelta(days=10), datetime.min.time())
    end = datetime.combine(value_date + timedelta(days=1), datetime.min.time())
    series = market._fetch_fx_series(direct, start, end)
    quote = market._forward_lookup(series, value_date.isoformat())
    if quote and quote > 0:
        # market devuelve "from por 1 to"; EUR por 1 from es el inverso.
        return (Decimal("1") / Decimal(str(quote))).quantize(
            Decimal("0.000000000001"), rounding=ROUND_HALF_UP
        )

    inverse = market._resolve_fx_pair("EUR", currency)
    if inverse:
        inv_series = market._fetch_fx_series(inverse, start, end)
        inverse_quote = market._forward_lookup(
            inv_series, value_date.isoformat()
        )
        if inverse_quote and inverse_quote > 0:
            return Decimal(str(inverse_quote)).quantize(
                Decimal("0.000000000001"), rounding=ROUND_HALF_UP
            )
    return None


def eur_rate_for(currency: str | None, value_date: date) -> EurRate | None:
    code = (currency or "EUR").upper()[:3]
    if code == "EUR":
        return EurRate(Decimal("1"), value_date, "statement")
    rate = _cached_rate(code, value_date)
    if rate is None or rate <= _RATE_EPS:
        return None
    return EurRate(rate, value_date, "historical")


def amount_to_eur(
    amount: Decimal | None,
    currency: str | None,
    value_date: date,
    *,
    provided_rate: Decimal | str | None = None,
    provided_source: str | None = None,
) -> tuple[Decimal | None, Decimal | None, str | None, date | None]:
    """Devuelve ``(amount_eur, rate, source, rate_date)``."""
    if amount is None:
        return None, None, None, None
    code = (currency or "EUR").upper()[:3]
    if provided_rate is not None:
        rate = Decimal(str(provided_rate))
        if rate > 0:
            converted = (Decimal(str(amount)) * rate).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
            return converted, rate, provided_source or "statement", value_date
    resolved = eur_rate_for(code, value_date)
    if resolved is None:
        return None, None, None, None
    converted = (Decimal(str(amount)) * resolved.rate).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return converted, resolved.rate, resolved.source, resolved.rate_date


def clear_rate_cache() -> None:
    """Solo para tests que inyectan series de mercado."""
    _RATE_CACHE.clear()
