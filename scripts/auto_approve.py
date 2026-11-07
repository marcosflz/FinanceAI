"""Autoaprueba movimientos pendientes ya clasificados por encima del umbral.

Uso:
    python -m scripts.auto_approve --dry-run
    python -m scripts.auto_approve
    python -m scripts.auto_approve --threshold 0.97
"""

from __future__ import annotations

import argparse
from decimal import Decimal

from src.db.session import _session
from src.model_settings import load_model_settings
from src.models import Classification, FinancialMovement


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    threshold = Decimal(
        str(
            args.threshold
            if args.threshold is not None
            else load_model_settings().auto_approve_threshold
        )
    )

    with _session() as session:
        rows = (
            session.query(FinancialMovement, Classification)
            .join(Classification, Classification.movement_id == FinancialMovement.id)
            .filter(
                FinancialMovement.estado == "pendiente",
                Classification.vigente.is_(True),
                Classification.categoria_id.isnot(None),
                Classification.confianza >= threshold,
            )
            .all()
        )
        ids = sorted({movement.id for movement, _ in rows})
        print(
            f"{len(ids)} movimientos pendientes con clasificación >= {threshold}"
        )
        if args.dry_run:
            return
        for movement, _ in rows:
            movement.estado = "aprobado"
        print(f"{len(ids)} movimientos autoaprobados")


if __name__ == "__main__":
    main()
