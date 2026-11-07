"""Reimporta un manifiesto de extractos en sus cuentas.

Manifiesto (JSON)::

    {
      "files": [
        {"path": "/data/reimport/files/ene.csv", "account_id": 1,
         "filename": "transactions_2026-01-01_2026-06-30.csv",
         "parser": "trade_republic"},
        {"path": "/data/reimport/files/otro.csv", "account_id": 2,
         "filename": "otro.csv", "parser": "agentic"}
      ]
    }

``parser`` puede ser ``trade_republic``, ``agentic`` o ``auto``. ``auto``
detecta la cabecera de Trade Republic y usa el parser determinista; el resto
va al extractor agéntico.

Uso:
    python -m scripts.reimport_files --manifest /data/reimport/manifest.json
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path

from src.db.session import _session
from src.ingest.accounts import TRADE_REPUBLIC_IBAN
from src.ingest.agentic import ExtractedStatement
from src.ingest.trade_republic import TradeRepublicCsvParser
from src.ingest_service import process_import
from src.models import Account, SourceFile


class TradeRepublicExtractor:
    """Adaptador determinista para los CSV de TR del manifiesto."""

    source = "trade_republic_csv"
    parser_version = "tr-csv-1.0"

    def extract(self, path: str | Path) -> ExtractedStatement:
        filepath = str(path)
        parser = TradeRepublicCsvParser()
        events = parser.parse(filepath)
        raw_rows: list[dict] = []
        with open(filepath, newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader):
                raw_rows.append({"row_index": index, "values": row})
        dates = [event["value_date"] for event in events if event.get("value_date")]
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=raw_rows,
            events=events,
            period_start=min(dates) if dates else None,
            period_end=max(dates) if dates else None,
            bank="Trade Republic",
            account_iban=TRADE_REPUBLIC_IBAN,
            metadata={"format": "csv", "parser": "trade_republic"},
        )


def _is_trade_republic(path: str) -> bool:
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            first = handle.readline().lower()
    except OSError:
        return False
    return "transaction_id" in first and "description" in first and "amount" in first


def _resolve_account(account_ref) -> int:
    with _session() as s:
        account = None
        if isinstance(account_ref, int):
            account = s.query(Account).filter_by(id=account_ref).first()
        elif isinstance(account_ref, str):
            account = s.query(Account).filter_by(nombre=account_ref).first()
            if account is None:
                try:
                    account = s.query(Account).filter_by(id=int(account_ref)).first()
                except (TypeError, ValueError):
                    account = None
        if account is None:
            raise SystemExit(f"Cuenta no encontrada: {account_ref!r}")
        if not account.activo:
            raise SystemExit(f"La cuenta está archivada: {account.nombre}")
        return int(account.id)


def _read_manifest(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        files = data
    else:
        files = data.get("files") or []
    if not files:
        raise SystemExit("El manifiesto no contiene ficheros")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Permite reprocesar un fichero ya registrado (dedup L1/L2).",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        raise SystemExit(f"No existe el manifiesto: {manifest_path}")
    files = _read_manifest(str(manifest_path))

    results = []
    for item in files:
        file_path = str(item.get("path") or "")
        if not file_path or not os.path.exists(file_path):
            raise SystemExit(f"Fichero no encontrado: {file_path!r}")
        account_id = _resolve_account(
            item.get("account_id") or item.get("account") or item.get("cuenta")
        )
        requested_parser = str(item.get("parser") or "auto").lower()
        if requested_parser == "auto":
            parser_name = "trade_republic" if _is_trade_republic(file_path) else "agentic"
        else:
            parser_name = requested_parser
        extractor = TradeRepublicExtractor() if parser_name == "trade_republic" else None
        result = process_import(
            file_path,
            force=args.force or bool(item.get("force")),
            original_filename=item.get("filename") or Path(file_path).name,
            account_id=account_id,
            extractor=extractor,
        )
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=result.source_file_id).first()
            item_result = {
                "file": item.get("filename") or Path(file_path).name,
                "account_id": account_id,
                "parser": parser_name,
                "source_file_id": result.source_file_id,
                "status": sf.status if sf else None,
                "rows": result.total_rows,
                "new": result.new_count,
                "seen": result.seen_count,
                "internal_transfers": result.internal_transfers,
                "linked_internal_transfers": result.linked_internal_transfers,
                "errors": result.errors,
                "account_match": result.account_match,
            }
            results.append(item_result)
            print(json.dumps(item_result, ensure_ascii=False, default=str))

    print(json.dumps({"files": len(results), "results": results}, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
