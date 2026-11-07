"""Verifica el estado posterior a la reimportación.

Uso:
    python -m scripts.verify_reimport
    python -m scripts.verify_reimport --expected-tr-movements 916
"""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

from sqlalchemy import func

from src.api_v3_data import _account_balances
from src.db.session import _session
from src.models import (
    Account,
    Asset,
    AssetTransaction,
    Categoria,
    Classification,
    FinancialMovement,
    MovementLink,
    PositionSnapshot,
    SourceFile,
)


def collect() -> dict:
    with _session() as s:
        paths = {
            category.id: category
            for category in s.query(Categoria).all()
        }
        duplicate_current = (
            s.query(Classification.movement_id, func.count())
            .filter(Classification.vigente == True)  # noqa: E712
            .group_by(Classification.movement_id)
            .having(func.count() > 1)
            .count()
        )
        root_classifications = (
            s.query(Classification.id)
            .join(Categoria, Categoria.id == Classification.categoria_id)
            .filter(
                Classification.vigente == True,  # noqa: E712
                Categoria.parent_id.is_(None),
            )
            .count()
        )
        no_account = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.account_id.is_(None))
            .count()
        )
        sf_no_account = (
            s.query(SourceFile).filter(SourceFile.account_id.is_(None)).count()
        )
        transfer_categories = {
            category.id: paths[category.id].nombre
            for category in paths.values()
            if category.tratamiento == "transferencia"
        }
        transfer_by_category = {
            name: count
            for category_id, name in transfer_categories.items()
            for count in [
                s.query(Classification)
                .filter(
                    Classification.vigente == True,  # noqa: E712
                    Classification.categoria_id == category_id,
                )
                .count()
            ]
        }
        balances = _account_balances(s)
        accounts = [
            {
                "id": account.id,
                "nombre": account.nombre,
                "iban": account.iban,
                "activo": account.activo,
                "balance_inicial": str(account.balance_inicial or 0),
                "balance_inicial_fecha": (
                    account.balance_inicial_fecha.isoformat()
                    if account.balance_inicial_fecha
                    else None
                ),
                "saldo_calculado": str(balances.get(account.id, Decimal("0"))),
            }
            for account in s.query(Account).order_by(Account.id)
        ]
        internal_links = (
            s.query(MovementLink)
            .filter(MovementLink.link_type == "internal_transfer")
            .count()
        )
        internal_movements = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.kind == "transferencia_interna")
            .count()
        )
        return {
            "movements": s.query(FinancialMovement).count(),
            "movements_without_account": no_account,
            "source_files": s.query(SourceFile).count(),
            "source_files_without_account": sf_no_account,
            "classifications": s.query(Classification).count(),
            "current_classifications": (
                s.query(Classification)
                .filter(Classification.vigente == True)  # noqa: E712
                .count()
            ),
            "movements_with_duplicate_current_classification": duplicate_current,
            "classifications_on_root": root_classifications,
            "accounts": accounts,
            "transfer_classifications_by_category": transfer_by_category,
            "internal_transfer_links": internal_links,
            "internal_transfer_movements": internal_movements,
            "assets": s.query(Asset).count(),
            "asset_transactions": s.query(AssetTransaction).count(),
            "position_snapshots": s.query(PositionSnapshot).count(),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-tr-movements", type=int, default=None)
    parser.add_argument("--expected-assets", type=int, default=None)
    parser.add_argument("--expected-asset-transactions", type=int, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = collect()
    failures: list[str] = []
    if report["movements_without_account"]:
        failures.append("Hay movimientos sin cuenta")
    if report["source_files_without_account"]:
        failures.append("Hay importaciones sin cuenta")
    if report["movements_with_duplicate_current_classification"]:
        failures.append("Hay movimientos con más de una clasificación vigente")
    if report["classifications_on_root"]:
        failures.append("Hay clasificaciones directas en categorías raíz")
    if args.expected_tr_movements is not None:
        # El total incluye posibles cuentas Revolut importadas después.
        if report["movements"] < args.expected_tr_movements:
            failures.append(
                f"Movimientos {report['movements']} < esperados "
                f"{args.expected_tr_movements}"
            )
    if args.expected_assets is not None and report["assets"] != args.expected_assets:
        failures.append(
            f"Activos {report['assets']} != esperados {args.expected_assets}"
        )
    if (
        args.expected_asset_transactions is not None
        and report["asset_transactions"] != args.expected_asset_transactions
    ):
        failures.append(
            f"Operaciones de activos {report['asset_transactions']} != "
            f"esperadas {args.expected_asset_transactions}"
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if failures:
        print("\nFALLOS:")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)
    print("\nOK: verificación de reimportación correcta")


if __name__ == "__main__":
    main()
