"""Snapshot de referencia anterior a una reimportación limpia.

No se usa para reaplicar clasificaciones (el plan empieza de cero); sirve para
auditar, comparar y comprobar que no se pierden movimientos.

Uso:
    python -m scripts.reimport_snapshot export --out /data/reimport/snapshot.json
    python -m scripts.reimport_snapshot verify --snapshot /data/reimport/snapshot.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime

from src.db.session import _session
from src.models import (
    Account,
    Asset,
    AssetTransaction,
    Categoria,
    Classification,
    ClassificationMemory,
    FinancialMovement,
    NormalizedEvent,
    PositionSnapshot,
    SourceFile,
)
from src.taxonomy import category_paths


def _dec(value) -> str | None:
    return None if value is None else str(value)


def export(path: str) -> dict:
    with _session() as s:
        paths = category_paths(s)
        data = {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "accounts": [
                {
                    "id": account.id,
                    "nombre": account.nombre,
                    "iban": account.iban,
                    "tipo": account.tipo,
                    "broker": account.broker,
                    "es_propia": account.es_propia,
                    "moneda": account.moneda,
                    "color": account.color,
                    "balance_inicial": _dec(account.balance_inicial),
                    "balance_inicial_fecha": (
                        account.balance_inicial_fecha.isoformat()
                        if account.balance_inicial_fecha
                        else None
                    ),
                    "activo": account.activo,
                    "alias_patrones": json.loads(account.alias_patrones or "[]"),
                }
                for account in s.query(Account).order_by(Account.id)
            ],
            "categories": [
                {
                    "id": category.id,
                    "path": paths.get(category.id),
                    "nombre": category.nombre,
                    "parent_id": category.parent_id,
                    "aplica_a": category.aplica_a,
                    "tratamiento": category.tratamiento,
                    "excluir_kpis": category.excluir_kpis,
                    "es_default": category.es_default,
                    "activa": category.activa,
                    "system_key": category.system_key,
                }
                for category in s.query(Categoria).order_by(Categoria.id)
            ],
            "source_files": [
                {
                    "id": sf.id,
                    "filename": sf.filename,
                    "file_hash": sf.file_hash,
                    "source": sf.source,
                    "account_id": sf.account_id,
                    "period_start": sf.period_start.isoformat() if sf.period_start else None,
                    "period_end": sf.period_end.isoformat() if sf.period_end else None,
                    "row_count": sf.row_count,
                    "movement_new_count": sf.movement_new_count,
                    "movement_seen_count": sf.movement_seen_count,
                    "status": sf.status,
                    "balance_start": _dec(sf.balance_start),
                    "balance_end": _dec(sf.balance_end),
                    "balance_start_date": (
                        sf.balance_start_date.isoformat()
                        if sf.balance_start_date
                        else None
                    ),
                }
                for sf in s.query(SourceFile).order_by(SourceFile.id)
            ],
            "movements": [],
            "classification_memory": [
                {
                    "id": entry.id,
                    "pattern_key": entry.pattern_key,
                    "mcc_code": entry.mcc_code,
                    "broker_type": entry.broker_type,
                    "categoria_id": entry.categoria_id,
                    "category_path": paths.get(entry.categoria_id),
                    "subtipo": entry.subtipo,
                    "merchant": entry.merchant,
                    "veces_aplicado": entry.veces_aplicado,
                    "confianza": _dec(entry.confianza),
                    "origen": entry.origen,
                    "activo": entry.activo,
                }
                for entry in s.query(ClassificationMemory).order_by(ClassificationMemory.id)
            ],
            "assets": [
                {
                    "id": asset.id,
                    "isin": asset.isin,
                    "symbol": asset.symbol,
                    "nombre": asset.nombre,
                    "asset_class": asset.asset_class,
                    "moneda": asset.moneda,
                }
                for asset in s.query(Asset).order_by(Asset.id)
            ],
            "asset_transactions": [
                {
                    "id": tx.id,
                    "asset_id": tx.asset_id,
                    "movement_id": tx.movement_id,
                    "tipo": tx.tipo,
                    "shares": _dec(tx.shares),
                    "price": _dec(tx.price),
                    "fee": _dec(tx.fee),
                    "fecha": tx.fecha.isoformat() if tx.fecha else None,
                }
                for tx in s.query(AssetTransaction).order_by(AssetTransaction.id)
            ],
            "position_snapshots": [
                {
                    "asset_id": snap.asset_id,
                    "cantidad": _dec(snap.cantidad),
                    "coste_total": _dec(snap.coste_total),
                    "precio_medio": _dec(snap.precio_medio),
                    "invertido": _dec(snap.invertido),
                    "comisiones": _dec(snap.comisiones),
                    "ganancia_realizada": _dec(snap.ganancia_realizada),
                }
                for snap in s.query(PositionSnapshot).order_by(PositionSnapshot.asset_id)
            ],
        }
        for movement in s.query(FinancialMovement).order_by(FinancialMovement.id):
            event = s.query(NormalizedEvent).filter_by(id=movement.event_id).first()
            classification = (
                s.query(Classification)
                .filter_by(movement_id=movement.id, vigente=True)
                .first()
            )
            data["movements"].append({
                "movement_id": movement.id,
                "account_id": movement.account_id,
                "account_destino_id": movement.account_destino_id,
                "kind": movement.kind,
                "direction": movement.direction,
                "amount": _dec(movement.amount),
                "currency": movement.currency,
                "value_date": movement.value_date.isoformat() if movement.value_date else None,
                "estado": movement.estado,
                "merchant": movement.merchant,
                "nota": movement.nota,
                "source_txn_id": event.source_txn_id if event else None,
                "broker_type": event.broker_type if event else None,
                "counterparty_iban": event.counterparty_iban if event else None,
                "description_clean": event.description_clean if event else None,
                "category_path": paths.get(classification.categoria_id) if classification else None,
                "subtipo": classification.subtipo if classification else None,
                "origen": classification.origen if classification else None,
                "confianza": _dec(classification.confianza) if classification else None,
                "explicacion": classification.explicacion if classification else None,
            })
        data["counts"] = {
            "accounts": len(data["accounts"]),
            "categories": len(data["categories"]),
            "source_files": len(data["source_files"]),
            "movements": len(data["movements"]),
            "classification_memory": len(data["classification_memory"]),
            "assets": len(data["assets"]),
            "asset_transactions": len(data["asset_transactions"]),
            "position_snapshots": len(data["position_snapshots"]),
        }

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
    digest = hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    print(json.dumps({"path": path, "sha256": digest, "counts": data["counts"]}, indent=2))
    return data


def verify(path: str) -> None:
    with open(path, encoding="utf-8") as handle:
        snapshot = json.load(handle)
    with _session() as s:
        current_counts = {
            "accounts": s.query(Account).count(),
            "categories": s.query(Categoria).count(),
            "source_files": s.query(SourceFile).count(),
            "movements": s.query(FinancialMovement).count(),
            "assets": s.query(Asset).count(),
            "asset_transactions": s.query(AssetTransaction).count(),
            "position_snapshots": s.query(PositionSnapshot).count(),
        }
        current_txns = {
            txn
            for (txn,) in s.query(NormalizedEvent.source_txn_id)
            .filter(NormalizedEvent.source_txn_id.isnot(None))
            .all()
        }
    snapshot_txns = {
        movement.get("source_txn_id")
        for movement in snapshot.get("movements", [])
        if movement.get("source_txn_id")
    }
    missing = sorted(snapshot_txns - current_txns)
    print(json.dumps({
        "snapshot_counts": snapshot.get("counts"),
        "current_counts": current_counts,
        "snapshot_movements_missing_by_txn": len(missing),
        "missing_examples": missing[:20],
    }, indent=2))
    if missing:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export_cmd = sub.add_parser("export")
    export_cmd.add_argument("--out", required=True)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    if args.command == "export":
        export(args.out)
    elif args.command == "verify":
        verify(args.snapshot)


if __name__ == "__main__":
    main()
