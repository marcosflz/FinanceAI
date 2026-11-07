"""
Estrategia de deduplicación.

Niveles:
  L0 — Mismo fichero: file_hash UNIQUE en source_files.
  L1 — Mismo movimiento por transaction_id: match por source_txn_id.
  L2 — Mismo movimiento sin ID: fingerprint canónico.
  L3 — Parecidos: scoring heurístico → cola dedup_candidates.
  L4 — Repetidos legítimos: marcados 'distinto' en dedup_candidates.
"""

from decimal import Decimal
from typing import Optional

from .ingest.text import compute_fingerprint as _compute_fingerprint


# Una sola implementación del fingerprint L2 (la del extractor). Antes había
# dos copias con regex de IBAN ligeramente distintas.
compute_fingerprint = _compute_fingerprint


def score_similarity(
    a_fecha: str,
    b_fecha: str,
    a_amount: Optional[Decimal],
    b_amount: Optional[Decimal],
    a_desc: str,
    b_desc: str,
    a_kind: str,
    b_kind: str,
) -> float:
    """Score L3 de similitud entre dos movimientos.

    Returns:
        Float entre 0 y 1. ≥0.8 → candidato a revisión.
    """
    w1, w2, w3 = 0.4, 0.4, 0.2
    score = 0.0

    # Fecha
    from datetime import datetime
    try:
        da = datetime.strptime(a_fecha[:10], "%Y-%m-%d").date()
        db = datetime.strptime(b_fecha[:10], "%Y-%m-%d").date()
        diff = abs((da - db).days)
        if diff == 0:
            score += w1 * 1.0
        elif diff == 1:
            score += w1 * 0.6
        elif diff <= 3:
            score += w1 * 0.2
    except Exception:
        score += w1 * 0.1

    # Importe
    if a_amount is not None and b_amount is not None:
        try:
            aa = abs(Decimal(str(a_amount)))
            bb = abs(Decimal(str(b_amount)))
            if aa == bb:
                score += w2 * 1.0
            elif aa > 0 and bb > 0:
                ratio = float(min(aa, bb) / max(aa, bb))
                score += w2 * ratio
        except Exception:
            pass
    elif a_amount is None and b_amount is None:
        score += w2 * 1.0

    # Kind
    if a_kind == b_kind:
        score += w3 * 0.5

    # Descripción (token Jaccard)
    import re
    def tokens(t: str) -> set:
        return {w for w in re.split(r'[\s,.!?;:]+', t.upper()) if len(w) >= 3}
    ta = tokens(a_desc)
    tb = tokens(b_desc)
    if ta and tb:
        inter = len(ta & tb)
        union = len(ta | tb)
        if union > 0:
            score += w3 * 0.5 * (inter / union)

    return min(score, 1.0)
