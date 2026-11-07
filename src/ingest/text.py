"""Utilidades de texto compartidas por la ingesta.

No conocen ningún banco: limpian descripciones, extraen IBANs y calculan el
fingerprint canónico que usa la deduplicación L2.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    re.IGNORECASE,
)
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?\d{4}){3,7}(?: ?\d{1,4})?\b")
_TRAILING_NULL_RE = re.compile(r"\s*null\s*$", re.IGNORECASE)


def normalize_iban(value: str | None) -> str:
    """Normaliza un IBAN: mayúsculas, sin espacios ni guiones."""
    if not value:
        return ""
    return re.sub(r"[\s-]+", "", value).upper()


def extract_ibans(text: str | None) -> list[str]:
    """Extrae IBANs normalizados de un texto, sin duplicados y en orden."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _IBAN_RE.finditer(text.upper()):
        iban = normalize_iban(match.group())
        if 15 <= len(iban) <= 34 and iban not in seen:
            seen.add(iban)
            result.append(iban)
    return result


def clean_description(raw: str | None) -> str:
    """Quita ruido y redacta IBANs/UUIDs dejando el texto legible."""
    if not raw:
        return ""
    text = _TRAILING_NULL_RE.sub("", str(raw).strip())
    text = _UUID_RE.sub("[UUID]", text)
    text = _IBAN_RE.sub("[IBAN]", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_fingerprint(description: str | None) -> str:
    """Normaliza una descripción para que el hash sea estable."""
    text = (description or "").upper()
    text = _UUID_RE.sub("", text)
    text = _IBAN_RE.sub("", text)
    text = re.sub(r"\bNULL\b", "", text)
    text = re.sub(r"[^A-Z0-9\s]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def compute_fingerprint(
    value_date: str | date,
    amount: str | Decimal | None,
    currency: str,
    kind: str,
    description_clean: str | None,
) -> str:
    """SHA-256 canónico para dedup L2."""
    date_text = value_date.isoformat() if isinstance(value_date, date) else str(value_date)
    amount_text = "0"
    if amount not in (None, ""):
        try:
            amount_text = str(
                Decimal(str(amount)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
        except (InvalidOperation, TypeError, ValueError):
            amount_text = str(amount)
    normalized = normalize_for_fingerprint(description_clean)
    raw = f"{date_text}|{amount_text}|{currency}|{kind}|{normalized}"
    return hashlib.sha256(raw.encode()).hexdigest()


_CURRENCY_NOISE_RE = re.compile(r"[€$£¥]|\b[A-Z]{3}\b")


def parse_decimal(
    value: object,
    decimal_separator: str | None = None,
    thousands_separator: str | None = None,
) -> Decimal | None:
    """Convierte un valor a Decimal sin romper por símbolos habituales.

    Si el mapping del extracto declara ``decimal_separator`` (``","`` o
    ``"."``) se respeta; así ``1.234`` en un CSV español es 1234 y no 1,234.
    Sin separador declarado se aplica la heurística: con ambos símbolos, el
    último es el decimal; con solo coma, la coma es decimal.
    Acepta signo final (``12,50-``) y paréntesis contables.
    """
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("\u00a0", " ").replace("\u2212", "-")
    text = _CURRENCY_NOISE_RE.sub("", text.upper()).strip()
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]
    text = text.replace(" ", "").replace("'", "")
    if text.endswith("-") and not text.startswith("-"):
        text = "-" + text[:-1]
    elif text.endswith("+"):
        text = text[:-1]
    decimal_separator = (decimal_separator or "").strip() or None
    if (
        decimal_separator in {",", "."}
        and "," in text
        and "." in text
        and text.rfind(decimal_separator) < max(text.rfind(","), text.rfind("."))
    ):
        # El valor contradice el separador declarado (``1.234,56`` con
        # decimal "."): manda el propio valor.
        decimal_separator = None
    if decimal_separator in {",", "."}:
        other = "." if decimal_separator == "," else ","
        if other in text and not re.fullmatch(
            rf"[-+]?\d{{1,3}}(?:{re.escape(other)}\d{{3}})+(?:{re.escape(decimal_separator)}\d*)?",
            text,
        ):
            # ``1,5`` no puede llevar "," como separador de miles.
            decimal_separator = None
    if decimal_separator in {",", "."}:
        other = "." if decimal_separator == "," else ","
        thousands = thousands_separator if thousands_separator not in (None, "") else other
        if thousands != decimal_separator:
            text = text.replace(thousands, "")
        text = text.replace(other, "")
        text = text.replace(decimal_separator, ".")
    elif "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        parsed = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if not parsed.is_finite():
        return None
    return -abs(parsed) if negative else parsed


def parse_date(value: object, fmt: str | None = None) -> date | None:
    """Parsea una fecha con el formato indicado o con una lista conservadora."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    candidates: list[str] = []
    if fmt:
        candidates.append(_normalise_date_format(fmt))
    candidates.extend(
        [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%d.%m.%Y",
            "%Y/%m/%d",
            "%m/%d/%Y",
            "%d/%m/%y",
            "%d-%m-%y",
            "%d.%m.%y",
        ]
    )
    for candidate in dict.fromkeys(candidates):
        try:
            return datetime.strptime(text, candidate).date()
        except ValueError:
            continue
    return None


def _normalise_date_format(fmt: str) -> str:
    """Acepta ``dd/mm/yyyy`` y lo convierte a ``%d/%m/%Y``."""
    if "%" in fmt:
        return fmt
    replacements = {
        "yyyy": "%Y",
        "yy": "%y",
        "mm": "%m",
        "dd": "%d",
        "MM": "%m",
        "DD": "%d",
    }
    result = fmt
    for source, target in replacements.items():
        result = result.replace(source, target)
    return result
