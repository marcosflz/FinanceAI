"""Reconstruye classification_memory desde decisiones humanas vigentes.

Uso:
    python -m scripts.rebuild_classification_memory
    python -m scripts.rebuild_classification_memory --reset
"""

from __future__ import annotations

import argparse
from collections import Counter

from src.classify.memory import _normalize_pattern, _record_in_session
from src.db.session import _session
from src.models import Classification, ClassificationMemory, FinancialMovement, NormalizedEvent


def rebuild(*, reset: bool = False) -> dict:
    stats = {"processed": 0, "recorded": 0, "skipped": 0, "patterns": 0}
    with _session() as s:
        if reset:
            deleted = s.query(ClassificationMemory).delete()
            stats["deleted"] = deleted
        rows = (
            s.query(Classification, FinancialMovement, NormalizedEvent)
            .join(FinancialMovement, FinancialMovement.id == Classification.movement_id)
            .join(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .filter(
                Classification.vigente == True,  # noqa: E712
                Classification.origen == "user",
                Classification.categoria_id.isnot(None),
            )
            .all()
        )
        seen: Counter[tuple[str, int]] = Counter()
        for classification, movement, event in rows:
            stats["processed"] += 1
            merchant = (movement.merchant or event.description_clean or "").strip()
            pattern = _normalize_pattern(merchant)
            if not pattern:
                stats["skipped"] += 1
                continue
            key = (pattern, classification.categoria_id)
            seen[key] += 1
            _record_in_session(
                s,
                pattern,
                merchant,
                event.mcc_code,
                event.broker_type,
                classification.categoria_id,
                classification.subtipo,
                "user",
            )
            stats["recorded"] += 1
        stats["patterns"] = len(seen)
        s.flush()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Vaciar la memoria antes.")
    args = parser.parse_args()
    print(rebuild(reset=args.reset))


if __name__ == "__main__":
    main()
