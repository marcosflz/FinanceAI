"""Extracción local de snapshots de patrimonio de Trade Republic.

El snapshot no genera compras ni movimientos de efectivo. Se conserva como
valoración fechada para conciliar cantidades, precios y patrimonio.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from ..ai.document_agent import DocumentIntakeAgent, FileKind, probe_file
from .text import parse_date, parse_decimal

_ISIN_RE = re.compile(r"\bISIN:\s*([A-Z]{2}[A-Z0-9]{9}\d)\b")
_QTY_RE = re.compile(
    r"^\s*(\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s+"
    r"(?:(?:unidades|unid\.|tít\.|tit\.|títulos?)\s+)?(.+)$",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d{1,3}(?:\.\d{3})*(?:,\d+)?|\d+(?:[,.]\d+)?")
_DATE_RE = re.compile(r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{4})\b")
_TICKER_RE = re.compile(r"^\s*([A-Z]{2,10})\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})\s*$")

_CRYPTO_TICKERS = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "solana": "SOL",
}


@dataclass
class SnapshotPositionDraft:
    name: str
    quantity: Decimal
    price: Decimal
    value: Decimal
    asset_symbol: str | None = None
    asset_isin: str | None = None
    asset_class: str = "otro"
    price_date: date | None = None
    cost_total: Decimal | None = None
    pnl_declared: Decimal | None = None
    currency: str = "EUR"

    @property
    def symbol(self) -> str:
        return self.asset_isin or self.asset_symbol or self.name


@dataclass
class PortfolioSnapshotDraft:
    snapshot_date: date
    bank: str | None = None
    account_iban: str | None = None
    currency: str = "EUR"
    doc_type: str = "portfolio_snapshot"
    custody_ref: str = "portfolio"
    securities_value: Decimal | None = None
    crypto_value: Decimal | None = None
    cash_declared: Decimal | None = None
    total_declared: Decimal | None = None
    positions: list[SnapshotPositionDraft] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def opening_candidate(self) -> bool:
        return self.doc_type in {"securities_snapshot", "crypto_snapshot"}

    def merged_positions(self) -> list[SnapshotPositionDraft]:
        """Agrupa líneas del mismo ISIN/ticker (p. ej. dos custodias)."""
        merged: dict[str, SnapshotPositionDraft] = {}
        for item in self.positions:
            key = item.symbol
            current = merged.get(key)
            if current is None:
                merged[key] = SnapshotPositionDraft(**item.__dict__)
                continue
            total_qty = current.quantity + item.quantity
            if total_qty > 0:
                current.price = (
                    current.price * current.quantity
                    + item.price * item.quantity
                ) / total_qty
            current.quantity = total_qty
            current.value += item.value
            if current.cost_total is not None and item.cost_total is not None:
                current.cost_total += item.cost_total
            elif item.cost_total is not None:
                current.cost_total = item.cost_total
        return list(merged.values())


def _amounts(text: str) -> list[Decimal]:
    values: list[Decimal] = []
    for token in _NUMBER_RE.findall(text):
        value = parse_decimal(token)
        if value is not None:
            values.append(value)
    return values


def _snapshot_date(text: str) -> date | None:
    for pattern in (
        r"\ba\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        r"FECHA\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
        r"a fecha\s+(\d{1,2}[./-]\d{1,2}[./-]\d{4})",
    ):
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return parse_date(match.group(1), "%d.%m.%Y")
    return None


def _trade_republic_position(
    line: str,
    *,
    section: str,
    currency: str,
) -> SnapshotPositionDraft | None:
    match = _QTY_RE.match(line.strip())
    if not match:
        return None
    quantity = parse_decimal(match.group(1))
    tail = match.group(2).strip()
    if quantity is None:
        return None
    values = _amounts(tail)
    if len(values) < 2:
        return None

    # Cortar el nombre antes de los importes finales. Los nombres no contienen
    # importes monetarios; los números de ISIN se extraen de otra línea.
    number_start = None
    for match_number in _NUMBER_RE.finditer(tail):
        if len(_NUMBER_RE.findall(tail[match_number.start():])) >= 2:
            number_start = match_number.start()
            break
    name = tail[:number_start].strip() if number_start is not None else tail
    name = re.sub(r"\s+", " ", name).strip(" -")

    if section == "crypto":
        if len(values) >= 4:
            price, cost_total, pnl, value = values[-4:]
        else:
            price, value = values[-2:]
            cost_total = pnl = None
        asset_class = "cripto"
        lower_name = name.lower()
        symbol = next(
            (
                ticker
                for token, ticker in _CRYPTO_TICKERS.items()
                if token in lower_name
            ),
            None,
        )
        return SnapshotPositionDraft(
            name=name,
            quantity=quantity,
            price=price,
            value=value,
            asset_symbol=symbol,
            asset_class=asset_class,
            cost_total=cost_total,
            pnl_declared=pnl,
            currency=currency,
        )

    price, value = values[-2:]
    lower_name = name.lower()
    if any(token in lower_name for token in ("etf", "ishares", "physical gold", "vaneck")):
        asset_class = "etf"
    elif any(token in lower_name for token in ("fund", "fidelity", "s&p 500")):
        asset_class = "fondo"
    else:
        asset_class = "stock"
    return SnapshotPositionDraft(
        name=name,
        quantity=quantity,
        price=price,
        value=value,
        asset_class=asset_class,
        currency=currency,
    )


def parse_trade_republic_snapshot(text: str) -> PortfolioSnapshotDraft | None:
    upper = (text or "").upper()
    if not any(marker in upper for marker in (
        "EXTRACTO DEL PATRIMONIO NETO",
        "EXTRACTO DE LA CUENTA DE VALORES",
        "EXTRACTO DE CRIPTOMONEDAS",
    )):
        return None
    snapshot_date = _snapshot_date(text)
    if snapshot_date is None:
        return None

    if "EXTRACTO DEL PATRIMONIO NETO" in upper:
        doc_type = "net_worth_snapshot"
        custody_ref = "portfolio"
    elif "EXTRACTO DE CRIPTOMONEDAS" in upper or "WALLET CRYPTO" in upper:
        doc_type = "crypto_snapshot"
        custody_ref = "crypto"
    else:
        doc_type = "securities_snapshot"
        custody_ref = "securities"

    currency = "EUR"
    currency_match = re.search(r"\b(?:en|EN)\s+([A-Z]{3})\b", text)
    if currency_match:
        currency = currency_match.group(1).upper()
    bank = "Trade Republic" if "TRADE REPUBLIC" in upper else None
    iban_match = re.search(r"\bIBAN\s+([A-Z]{2}\d{2}[A-Z0-9]{10,30})\b", text)
    account_iban = iban_match.group(1) if iban_match else None

    result = PortfolioSnapshotDraft(
        snapshot_date=snapshot_date,
        bank=bank,
        account_iban=account_iban,
        currency=currency,
        doc_type=doc_type,
        custody_ref=custody_ref,
    )
    section = "securities" if doc_type != "crypto_snapshot" else "crypto"
    last_position: SnapshotPositionDraft | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        upper_line = line.upper()
        if "WALLET CRYPTO" in upper_line or "EXTRACTO DE CRIPTOMONEDAS" in upper_line:
            section = "crypto"
            last_position = None
        elif "CUENTA DE VALORES" in upper_line and "EXTRACTO" in upper_line:
            section = "securities"
            last_position = None

        if upper_line.startswith("CUENTA DE VALORES") and doc_type == "net_worth_snapshot":
            amounts = _amounts(line)
            if amounts:
                result.securities_value = amounts[-1]
        elif upper_line.startswith("WALLET CRYPTO") and doc_type == "net_worth_snapshot":
            amounts = _amounts(line)
            if amounts:
                result.crypto_value = amounts[-1]
        elif upper_line.startswith("EFECTIVO") and "BALANCE" not in upper_line:
            amounts = _amounts(line)
            if amounts:
                result.cash_declared = amounts[-1]
        elif upper_line.startswith("TOTAL") and doc_type == "net_worth_snapshot":
            amounts = _amounts(line)
            if amounts:
                result.total_declared = amounts[-1]
        elif "VALORES DE MERCADO TOTALES" in upper_line:
            amounts = _amounts(line)
            if amounts:
                result.total_declared = amounts[-1]
                result.crypto_value = amounts[-1]
        elif "NÚMERO DE POSICIONES" in upper_line:
            amounts = _amounts(line)
            if amounts:
                if doc_type == "securities_snapshot":
                    result.securities_value = amounts[-1]
                    result.total_declared = amounts[-1]
                elif doc_type == "crypto_snapshot":
                    result.crypto_value = amounts[-1]
                    result.total_declared = amounts[-1]

        isin_match = _ISIN_RE.search(line)
        if isin_match and last_position is not None:
            last_position.asset_isin = isin_match.group(1)
            if not last_position.asset_symbol:
                last_position.asset_symbol = isin_match.group(1)
            continue

        date_only = re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{4}", line)
        if date_only and last_position is not None:
            last_position.price_date = parse_date(line, "%d.%m.%Y")
            continue

        ticker_match = _TICKER_RE.match(line)
        if ticker_match and last_position is not None and section == "crypto":
            ticker = ticker_match.group(1)
            if ticker not in {"EUR", "USD"}:
                last_position.asset_symbol = ticker
            last_position.price_date = parse_date(
                ticker_match.group(2), "%d.%m.%Y"
            )
            continue

        position = _trade_republic_position(
            line, section=section, currency=currency
        )
        if position is not None:
            if position.price_date is None:
                position.price_date = snapshot_date
            result.positions.append(position)
            last_position = position

    # En el extracto de patrimonio, el "Cuenta de valores" del sumario no debe
    # confundirse con la cabecera de sección. Preferir los totales explícitos.
    if doc_type == "net_worth_snapshot":
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("Cuenta de valores"):
                amounts = _amounts(stripped)
                if len(amounts) == 1:
                    result.securities_value = amounts[0]
            if stripped.startswith("Total") and len(_amounts(stripped)) == 1:
                result.total_declared = _amounts(stripped)[0]

    result.positions = [
        position
        for position in result.positions
        if position.asset_isin or position.asset_symbol
    ]
    result.positions = result.merged_positions()
    if not result.positions:
        result.issues.append("No se detectaron posiciones en el snapshot")
    if result.total_declared is None:
        components = [
            value for value in (
                result.securities_value,
                result.crypto_value,
                result.cash_declared,
            )
            if value is not None
        ]
        if components:
            result.total_declared = sum(components, Decimal("0"))
    return result


def read_portfolio_snapshot(path: str | Path) -> PortfolioSnapshotDraft | None:
    """Lee un PDF local y devuelve un snapshot si el documento lo es."""
    filepath = Path(path)
    if filepath.suffix.lower() != ".pdf":
        return None
    probe = probe_file(filepath)
    if probe.kind is not FileKind.pdf:
        return None
    pages = DocumentIntakeAgent().extract_text(filepath, probe)
    text = "\n".join(page.text or "" for page in pages)
    return parse_trade_republic_snapshot(text)
