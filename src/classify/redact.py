"""
Redacción de datos sensibles antes de enviar al LLM.

Se mueve aquí la lógica de _redact_text desde src/parser.py.
Se mantiene compatibilidad con get_redact_literals desde la BD.
"""

import re

_IBAN_RE = re.compile(r'\b[A-Z]{2}\d{2}(?: ?\d{4}){3,7}(?: ?\d{1,4})?\b')
_BIC_RE = re.compile(r'\b[A-Z]{4}[A-Z]{2}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b')


def redact_text(text: str, literals: list[str] | None = None) -> str:
    """Redacta IBANs, BICs y literales personalizados."""
    text = _IBAN_RE.sub('[IBAN]', text)
    text = _BIC_RE.sub('[BIC]', text)
    if literals:
        for lit in literals:
            lit = lit.strip()
            if lit and len(lit) >= 3:
                text = re.sub(re.escape(lit), '[REDACTED]', text, flags=re.IGNORECASE)
    return text


def get_redact_literals() -> list[str]:
    """Obtiene literales a redactar desde la BD."""
    from ..db.session import _session
    from ..models import AppConfig
    with _session() as s:
        row = s.query(AppConfig).filter_by(key="redact_literals").first()
        if not row or not row.value:
            return []
        return [
            literal.strip()
            for literal in row.value.split("\n")
            if literal.strip() and len(literal.strip()) >= 3
        ]
