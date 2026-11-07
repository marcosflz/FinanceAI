"""
Memoria de clasificaciones confirmadas por el usuario.

Lookup O(1) por ``pattern_key`` (merchant normalizado). El feedback loop
aumenta la confianza al confirmar y la degrada al corregir; si baja de 0.50
la entrada se desactiva.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from ..db.session import _session
from ..models import ClassificationMemory
from ..taxonomy import category_paths, resolve_assignable_category

CONFIANZA_MIN_LOOKUP = Decimal("0.60")
CONFIANZA_MIN_AUTO = Decimal("0.85")


def lookup(
    mov_id: int,
    merchant: str | None,
    mcc: str | None,
    broker_type: str | None,
    session=None,
) -> dict | None:
    """Busca en memoria una clasificación previa para los mismos atributos.

    Returns:
        dict con {categoria_id, subtipo, merchant, confianza} si hay hit,
        None si no.
    """
    if not merchant:
        return None

    pattern = _normalize_pattern(merchant)
    if not pattern:
        return None

    def _query(s):
        entry = (
            s.query(ClassificationMemory)
            .filter(
                ClassificationMemory.pattern_key == pattern,
                ClassificationMemory.activo == True,  # noqa: E712
            )
            .order_by(ClassificationMemory.confianza.desc())
            .first()
        )
        if entry and entry.confianza is not None and entry.confianza >= CONFIANZA_MIN_LOOKUP:
            return {
                "categoria_id": entry.categoria_id,
                "categoria_nombre": category_paths(s).get(entry.categoria_id),
                "subtipo": entry.subtipo,
                "merchant": entry.merchant or merchant,
                "confianza": entry.confianza,
                "entry_id": entry.id,
            }
        return None

    if session is not None:
        return _query(session)
    with _session() as s:
        return _query(s)


def load_memory_index(session) -> dict[str, dict]:
    """Carga en memoria las entradas activas indexadas por ``pattern_key``."""
    rows = (
        session.query(ClassificationMemory)
        .filter(
            ClassificationMemory.activo == True,  # noqa: E712
            ClassificationMemory.confianza >= CONFIANZA_MIN_LOOKUP,
        )
        .order_by(ClassificationMemory.confianza.desc())
        .all()
    )
    category_names = category_paths(session)
    index: dict[str, dict] = {}
    for entry in rows:
        index.setdefault(entry.pattern_key, {
            "categoria_id": entry.categoria_id,
            "categoria_nombre": category_names.get(entry.categoria_id),
            "subtipo": entry.subtipo,
            "merchant": entry.merchant,
            "confianza": entry.confianza,
            "entry_id": entry.id,
        })
    return index


def record(
    mov_id: int,
    merchant: str | None,
    mcc: str | None,
    broker_type: str | None,
    categoria_id: int,
    subtipo: str | None = None,
    origen: str = "user",
    session=None,
) -> None:
    """Registra una clasificación en memoria (upsert idempotente).

    ``session`` permite reutilizar la transacción del llamador (evita abrir
    una sesión anidada sobre la misma conexión).
    """
    if not merchant:
        return
    pattern = _normalize_pattern(merchant)
    if not pattern:
        return
    if session is not None:
        _record_in_session(
            session, pattern, merchant, mcc, broker_type,
            categoria_id, subtipo, origen,
        )
        return
    with _session() as s:
        _record_in_session(
            s, pattern, merchant, mcc, broker_type,
            categoria_id, subtipo, origen,
        )


def _record_in_session(
    session, pattern: str, merchant: str, mcc: str | None,
    broker_type: str | None, categoria_id: int, subtipo: str | None,
    origen: str,
) -> None:
    resolved = resolve_assignable_category(session, categoria_id)
    if resolved is not None:
        categoria_id = resolved.id
    now = datetime.utcnow()
    entry = (
        session.query(ClassificationMemory)
        .filter(ClassificationMemory.pattern_key == pattern)
        .order_by(ClassificationMemory.confianza.desc())
        .first()
    )
    if entry:
        entry.veces_confirmado = (entry.veces_confirmado or 0) + 1
        entry.ultimo_uso_en = now
        entry.categoria_id = categoria_id
        entry.subtipo = subtipo
        entry.merchant = merchant
        if mcc:
            entry.mcc_code = mcc
        if broker_type:
            entry.broker_type = broker_type
        entry.confianza = min(
            Decimal("1.000"), (entry.confianza or Decimal("0.80")) + Decimal("0.020")
        )
        entry.activo = True
    else:
        entry = ClassificationMemory(
            pattern_key=pattern,
            mcc_code=mcc,
            broker_type=broker_type,
            categoria_id=categoria_id,
            subtipo=subtipo,
            merchant=merchant,
            veces_confirmado=1,
            confianza=Decimal("0.80"),
            origen=origen,
            ultimo_uso_en=now,
        )
    session.add(entry)


def correct(
    mov_id: int,
    merchant: str | None,
    mcc: str | None,
    broker_type: str | None,
    categoria_id: int,
    subtipo: str | None = None,
    session=None,
) -> None:
    """Registra una corrección del usuario vs. la clasificación previa.

    Degrada la confianza (×0.7) de cada entrada con el mismo ``pattern_key``;
    por debajo de 0.50 la desactiva. Si no había precedente, crea una entrada
    nueva con la decisión corregida y confianza base (0.80).
    """
    if not merchant:
        return
    pattern = _normalize_pattern(merchant)
    if not pattern:
        return
    if session is not None:
        _correct_in_session(
            session, pattern, merchant, mcc, broker_type, categoria_id, subtipo,
        )
        return
    with _session() as s:
        _correct_in_session(
            s, pattern, merchant, mcc, broker_type, categoria_id, subtipo,
        )


def _correct_in_session(
    session, pattern: str, merchant: str, mcc: str | None,
    broker_type: str | None, categoria_id: int, subtipo: str | None,
) -> None:
    resolved = resolve_assignable_category(session, categoria_id)
    if resolved is not None:
        categoria_id = resolved.id
    now = datetime.utcnow()
    entries = (
        session.query(ClassificationMemory)
        .filter(ClassificationMemory.pattern_key == pattern)
        .all()
    )
    if not entries:
        session.add(ClassificationMemory(
            pattern_key=pattern,
            mcc_code=mcc,
            broker_type=broker_type,
            categoria_id=categoria_id,
            subtipo=subtipo,
            merchant=merchant,
            veces_corregido=1,
            confianza=Decimal("0.80"),
            origen="user",
            ultimo_uso_en=now,
        ))
        return

    for entry in entries:
        entry.veces_corregido = (entry.veces_corregido or 0) + 1
        entry.confianza = (entry.confianza or Decimal("0.80")) * Decimal("0.7")
        if entry.confianza < Decimal("0.50"):
            entry.activo = False
        entry.categoria_id = categoria_id
        entry.subtipo = subtipo
        entry.ultimo_uso_en = now


def _normalize_pattern(text: str) -> str:
    """Normaliza un merchant/description a ``pattern_key``.

    Elimina prefijos PAYPAL *, UUIDs, IBANs, sufijos ``null``, dígitos largos
    y signos no alfanuméricos; colapsa espacios.
    """
    import re
    s = text.upper()
    s = re.sub(r'\bPAYPAL\s*\*', '', s)
    s = re.sub(r'[0-9A-F]{8}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{4}-[0-9A-F]{12}', '', s)
    s = re.sub(r'\b[A-Z]{2}\d{2}(?:\s?\d{4}){3,7}(?:\s?\d{1,4})?\b', '', s)
    s = re.sub(r'\bNULL\b', '', s)
    s = re.sub(r'\d{6,}', '', s)
    s = re.sub(r'[^A-Z0-9ÁÉÍÓÚÜÑ ]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s
