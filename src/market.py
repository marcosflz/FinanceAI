import logging
import time
from datetime import datetime
from typing import Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# ── Cache ──────────────────────────────────────────────────────────────────────
_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL_QUOTE = 60
_CACHE_TTL_HISTORY = 300
_CACHE_TTL_INFO = 3600
_CACHE_TTL_EXCHANGE = 3600

def _cache_get(key: str, ttl: float):
    entry = _cache.get(key)
    if entry and (time.time() - entry[0]) < ttl:
        return entry[1]
    return None

def _cache_set(key: str, value):
    _cache[key] = (time.time(), value)

# ── Currency normalization ────────────────────────────────────────────────────
# Yahoo Finance returns non-standard currency codes for some exchanges.
# GBp (pence sterling) is the most common: prices are in pence, not pounds.
# Lookup is case-sensitive for GBp (the only entry with lowercase) then
# falls back to uppercase for standard currencies.
_CURRENCY_MAP_CS: dict[str, tuple[str, float]] = {
    "GBp": ("GBP", 0.01),
    "GBX": ("GBP", 0.01),
}
_CURRENCY_MAP_CI: dict[str, tuple[str, float]] = {
    "CNH": ("CNY", 1.0),
}

def normalize_currency(raw: Optional[str]) -> tuple[str, float]:
    """Returns (normalized_currency, price_multiplier)."""
    if not raw:
        return "EUR", 1.0
    # Case-sensitive lookup first (GBp)
    entry = _CURRENCY_MAP_CS.get(raw)
    if entry:
        return entry
    # Case-insensitive for known aliases
    upper = raw.upper().strip()
    entry = _CURRENCY_MAP_CI.get(upper)
    if entry:
        return entry
    return upper, 1.0

def _resolve_fx_pair(from_currency: str, to_currency: str) -> Optional[str]:
    """Resolve a Yahoo Finance FX pair for from_currency→to_currency.

    Returns the pair ticker (e.g. 'EURUSD=X' for USD→EUR).
    Yahoo pairs are named 'TOFROM=X': EURUSD=X gives the price of 1 EUR in USD.
    convert_price divides by this rate, so the pair must represent
    "how many 'from_currency' per 1 'to_currency'" to match the dividing math.
    """
    if from_currency == to_currency:
        return None
    f, t = from_currency.upper(), to_currency.upper()
    # Pair naming convention: {to}{from}=X → price of 1 to in from
    # e.g. EURUSD=X gives USD per 1 EUR ≈ 1.08
    return f"{t}{f}=X"

def _fetch_fx_rate_raw(pair: str) -> Optional[float]:
    """Fetch the current rate for an FX pair using yfinance history.
    More reliable than t.info which can be rate-limited.
    """
    cache_key = f"fx_raw:{pair}"
    cached = _cache_get(cache_key, _CACHE_TTL_EXCHANGE)
    if cached is not None:
        return cached
    try:
        df = yf.download(pair, period="2d", progress=False, auto_adjust=False)
        if df.empty:
            return None
        close = df["Close"].iloc[-1]
        rate = float(close)
        if rate and rate > 0:
            _cache_set(cache_key, rate)
            return rate
    except Exception:
        pass
    return None

def _resolve_fx_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """Resolve exchange rate from_currency → to_currency.
    Tries direct pair, inverse pair, then fails.
    """
    if from_currency == to_currency:
        return 1.0

    # Direct: EURUSD=X gives how many USD per 1 EUR
    direct = _resolve_fx_pair(from_currency, to_currency)
    if direct:
        rate = _fetch_fx_rate_raw(direct)
        if rate is not None and rate > 0:
            return rate

    # Inverse: USDEUR=X gives how many EUR per 1 USD ≈ 0.925.
    # Since convert_price divides by rate, we compute 1/inv to get the
    # same units as the direct pair (to-quantity per-1-from).
    inv_pair = f"{from_currency.upper()}{to_currency.upper()}=X"
    if inv_pair != direct:
        inv_rate = _fetch_fx_rate_raw(inv_pair)
        if inv_rate is not None and inv_rate > 0:
            return round(1.0 / inv_rate, 6)

    return None

# ── Public API ─────────────────────────────────────────────────────────────────

def get_exchange_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """Current exchange rate from_currency → to_currency."""
    if from_currency == to_currency:
        return 1.0
    key = f"exchange:{from_currency}:{to_currency}"
    cached = _cache_get(key, _CACHE_TTL_EXCHANGE)
    if cached is not None:
        return cached
    rate = _resolve_fx_rate(from_currency, to_currency)
    if rate is not None:
        _cache_set(key, rate)
    return rate

def _fetch_fx_series(pair: str, start: datetime, end: datetime) -> dict[str, float]:
    """Fetch daily close prices for an FX pair over a date range.
    Returns dict of 'YYYY-MM-DD' → close price.
    """
    cache_key = f"fx_series:{pair}:{start.date()}:{end.date()}"
    cached = _cache_get(cache_key, 86400)
    if cached is not None:
        return cached
    try:
        df = yf.download(pair, start=start, end=end, progress=False, auto_adjust=False)
        if df.empty:
            return {}
        series = {}
        for idx, row in df.iterrows():
            close = float(row["Close"])
            if close > 0:
                series[idx.strftime("%Y-%m-%d")] = close
        _cache_set(cache_key, series)
        return series
    except Exception:
        return {}

def _forward_lookup(series: dict[str, float], date_str: str) -> Optional[float]:
    """Look up value for date_str; if missing, go backwards up to 7 days. Returns last known value or None."""
    if date_str in series:
        return series[date_str]
    from datetime import timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    for i in range(1, 15):
        prev = (dt - timedelta(days=i)).strftime("%Y-%m-%d")
        if prev in series:
            return series[prev]
    return None

def get_exchange_rate_at(from_currency: str, to_currency: str, date: datetime) -> Optional[float]:
    """Historical exchange rate from_currency → to_currency on (or before) date."""
    if from_currency == to_currency:
        return 1.0

    direct = _resolve_fx_pair(from_currency, to_currency)
    if not direct:
        return None

    date_str = date.strftime("%Y-%m-%d")
    # Fetch ± 5 days to ensure we hit a trading day
    from datetime import timedelta
    start = (date - timedelta(days=10)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = (date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)

    series = _fetch_fx_series(direct, start, end)
    rate = _forward_lookup(series, date_str)
    if rate is not None:
        return rate

    # Try inverse pair
    inv_pair = f"{to_currency.upper()}{from_currency.upper()}=X"
    invert_series = _fetch_fx_series(inv_pair, start, end)
    inv_rate = _forward_lookup(invert_series, date_str)
    if inv_rate is not None and inv_rate > 0:
        return round(1.0 / inv_rate, 6)

    # Fallback: current rate
    return get_exchange_rate(from_currency, to_currency)

def convert_price(price: Optional[float], from_currency: str, to_currency: str) -> Optional[float]:
    """Convert price at current rate. Returns None only if price is None or conversion fails."""
    if price is None:
        return None
    if from_currency == to_currency:
        return price
    rate = get_exchange_rate(from_currency, to_currency)
    if rate is None or rate == 0:
        return None
    return round(price / rate, 4)

def convert_price_at(price: Optional[float], from_currency: str, to_currency: str, date: datetime) -> Optional[float]:
    """Convert price at historical rate. Returns None only if price is None or conversion fails."""
    if price is None:
        return None
    if from_currency == to_currency:
        return price
    rate = get_exchange_rate_at(from_currency, to_currency, date)
    if rate is None or rate == 0:
        return None
    return round(price / rate, 4)

# ── Public functions ───────────────────────────────────────────────────────────

def buscar_activo(query: str, max_results: int = 10) -> list[dict]:
    try:
        search = yf.Search(query, max_results=max_results)
        results = []
        for q in search.quotes:
            raw_moneda = q.get("currency", "")
            moneda, _ = normalize_currency(raw_moneda)
            results.append({
                "ticker": q.get("symbol", ""),
                "nombre": q.get("shortname") or q.get("longname", ""),
                "exchange": q.get("exchange", ""),
                "tipo": q.get("quoteType", "").lower(),
                "moneda": moneda,
            })
        return results
    except Exception:
        return []

def _get_fast_info_currency(ticker: yf.Ticker) -> str:
    """Get currency from fast_info (more reliable than t.info). Returns empty string on failure."""
    try:
        return ticker.fast_info.currency or ""
    except Exception:
        return ""

def get_precio_actual(ticker: str, target_currency: Optional[str] = None) -> dict:
    cache_key = f"quote:{ticker}" + (f":{target_currency}" if target_currency else "")
    cached = _cache_get(cache_key, _CACHE_TTL_QUOTE)
    if cached:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    precio = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
    prev_close = info.get("previousClose") or info.get("regularMarketPreviousClose")

    raw_currency = _get_fast_info_currency(t) or info.get("currency") or ""
    moneda_base, factor = normalize_currency(raw_currency)

    # Apply normalization factor (e.g. GBp → GBP ÷100)
    if factor != 1.0 and precio is not None:
        precio = round(precio * factor, 4)
    if factor != 1.0 and prev_close is not None:
        prev_close = round(prev_close * factor, 4)

    moneda = moneda_base
    if target_currency and moneda_base and moneda_base != target_currency:
        precio_converted = convert_price(precio, moneda_base, target_currency)
        if precio_converted is not None:
            precio = precio_converted
            prev_close = convert_price(prev_close, moneda_base, target_currency) if prev_close is not None else None
            moneda = target_currency

    cambio_abs = None
    cambio_pct = None
    if precio is not None and prev_close:
        cambio_abs = round(precio - prev_close, 4)
        cambio_pct = round((cambio_abs / prev_close) * 100, 2) if prev_close != 0 else 0.0

    result = {
        "ticker": ticker,
        "precio": precio,
        "moneda": moneda,
        "moneda_original": moneda_base,
        "cambio_pct": cambio_pct,
        "cambio_abs": cambio_abs,
        "nombre": info.get("shortName") or info.get("longName", ""),
        "market_state": info.get("marketState", ""),
    }
    _cache_set(cache_key, result)
    return result

def get_historial(
    ticker: str,
    periodo: str = "1y",
    intervalo: str = "1d",
    target_currency: Optional[str] = None,
) -> list[dict]:
    cache_key = f"history:{ticker}:{periodo}:{intervalo}" + (f":{target_currency}" if target_currency else "")
    cached = _cache_get(cache_key, _CACHE_TTL_HISTORY)
    if cached:
        return cached

    t = yf.Ticker(ticker)
    df = t.history(period=periodo, interval=intervalo)

    if df.empty:
        return []

    raw_currency = ""
    try:
        raw_currency = t.fast_info.currency or ""
    except Exception:
        pass
    moneda_base, factor = normalize_currency(raw_currency)

    records = []
    for idx, row in df.iterrows():
        ts = int(idx.timestamp())
        def _val(col):
            v = float(row[col]) if row[col] == row[col] else None
            if v is not None and factor != 1.0:
                v = round(v * factor, 4)
            return v

        open_price = _val("Open")
        high_price = _val("High")
        low_price = _val("Low")
        close_price = _val("Close")

        if target_currency and moneda_base and moneda_base != target_currency:
            open_price = convert_price(open_price, moneda_base, target_currency) or open_price
            high_price = convert_price(high_price, moneda_base, target_currency) or high_price
            low_price = convert_price(low_price, moneda_base, target_currency) or low_price
            close_price = convert_price(close_price, moneda_base, target_currency) or close_price

        records.append({
            "time": ts,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
        })

    _cache_set(cache_key, records)
    return records

def get_info_activo(ticker: str) -> dict:
    cache_key = f"info:{ticker}"
    cached = _cache_get(cache_key, _CACHE_TTL_INFO)
    if cached:
        return cached

    t = yf.Ticker(ticker)
    info = t.info or {}

    raw_moneda = info.get("currency", "")
    moneda, _ = normalize_currency(raw_moneda)

    result = {
        "ticker": ticker,
        "nombre": info.get("shortName") or info.get("longName", ""),
        "sector": info.get("sector"),
        "industria": info.get("industry"),
        "market_cap": info.get("marketCap"),
        "moneda": moneda,
        "exchange": info.get("exchange", ""),
        "tipo": (info.get("quoteType") or "").lower(),
        "descripcion": info.get("longBusinessSummary"),
        "logo": info.get("logo_url"),
        "website": info.get("website"),
        "pais": info.get("country"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "dividend_yield": info.get("dividendYield"),
        "pe_ratio": info.get("trailingPE"),
    }
    _cache_set(cache_key, result)
    return result
