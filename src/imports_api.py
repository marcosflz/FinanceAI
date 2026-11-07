"""
API endpoints para el flujo de importación CSV-nativo.
"""

import json
import os
import tempfile
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .classify.pipeline import classify_pending
from .db.session import _session
from .ingest.agentic import AgenticExtractionError
from .ingest_service import process_import
from .models import (
    Categoria,
    Classification,
    FinancialMovement,
    MovementSource,
    NormalizedEvent,
    RawRow,
    SourceFile,
)

router = APIRouter(tags=["imports"])


class ImportSummary(BaseModel):
    id: int
    source: str
    filename: str
    status: str
    parser_version: str
    period_start: date | None = None
    period_end: date | None = None
    row_count: int = 0
    movement_new_count: int = 0
    movement_seen_count: int = 0
    error: str | None = None
    subido_en: str = ""
    parseado_en: str | None = None


def _import_to_dict(sf: SourceFile) -> dict:
    return {
        "id": sf.id,
        "source": sf.source,
        "filename": sf.filename,
        "status": sf.status,
        "parser_version": sf.parser_version,
        "period_start": sf.period_start.isoformat() if sf.period_start else None,
        "period_end": sf.period_end.isoformat() if sf.period_end else None,
        "row_count": sf.row_count or 0,
        "movement_new_count": sf.movement_new_count or 0,
        "movement_seen_count": sf.movement_seen_count or 0,
        "error": sf.error,
        "subido_en": sf.subido_en.isoformat() if sf.subido_en else "",
        "parseado_en": sf.parseado_en.isoformat() if sf.parseado_en else None,
    }


@router.post("")
def upload_import(
    file: UploadFile = File(...),
    force: bool = Query(default=False),
    account_id: int | None = Query(default=None),
):
    """Sube un CSV y lo procesa (detecta, parsea, dedup, clasifica).

    Si force=true, permite re-importar un fichero con el mismo hash.
    ``account_id`` asigna el extracto a una cuenta concreta.
    """
    content = file.file.read()
    if not content:
        raise HTTPException(400, "Archivo vacío")

    suffix = ".csv"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = process_import(
            tmp_path,
            force=force,
            original_filename=file.filename,
            account_id=account_id,
        )
    except AgenticExtractionError as e:
        raise HTTPException(422, str(e)) from e
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    finally:
        os.unlink(tmp_path)

    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=result.source_file_id).first()
        return _import_to_dict(sf) if sf else {"source_file_id": result.source_file_id}


@router.get("")
def list_imports():
    """Lista todas las importaciones."""
    with _session() as s:
        imports = (
            s.query(SourceFile)
            .order_by(SourceFile.id.desc())
            .all()
        )
        return [_import_to_dict(sf) for sf in imports]


@router.get("/{import_id}")
def get_import(import_id: int):
    """Detalle de una importación."""
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, f"Import {import_id} no encontrado")
        return _import_to_dict(sf)


@router.get("/{import_id}/movements")
def get_import_movements(
    import_id: int,
    estado: str | None = Query(default=None),
    kind: str | None = Query(default=None),
):
    """Movimientos de una importación."""
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, f"Import {import_id} no encontrado")

        q = (
            s.query(FinancialMovement)
            .join(MovementSource, MovementSource.movement_id == FinancialMovement.id)
            .filter(MovementSource.source_file_id == import_id)
        )
        if estado:
            q = q.filter(FinancialMovement.estado == estado)
        if kind:
            q = q.filter(FinancialMovement.kind == kind)

        movs = q.order_by(FinancialMovement.value_date).all()

        result = []
        for m in movs:
            event = s.query(NormalizedEvent).filter_by(id=m.event_id).first()
            cl = (
                s.query(Classification)
                .filter(
                    Classification.movement_id == m.id,
                    Classification.vigente.is_(True),
                )
                .first()
            )
            cl_cat = None
            if cl:
                cat = s.query(Categoria).filter_by(id=cl.categoria_id).first()
                parent = (
                    s.query(Categoria).filter_by(id=cat.parent_id).first()
                    if cat is not None and cat.parent_id is not None
                    else None
                )
                root = parent or cat
                cl_cat = {
                    "categoria": cat.nombre if cat else None,
                    "categoria_id": cl.categoria_id,
                    "categoria_raiz_id": root.id if root is not None else None,
                    "categoria_raiz_nombre": root.nombre if root is not None else None,
                    "subcategoria_id": cat.id if parent is not None else None,
                    "subcategoria_nombre": (
                        cat.nombre if parent is not None else None
                    ),
                    "subtipo": cl.subtipo,
                    "origen": cl.origen,
                    "confianza": float(cl.confianza) if cl.confianza else None,
                    "explicacion": cl.explicacion,
                }
            result.append({
                "id": m.id,
                "kind": m.kind,
                "direction": m.direction,
                "amount": float(m.amount) if m.amount else None,
                "currency": m.currency,
                "value_date": m.value_date.isoformat() if m.value_date else None,
                "estado": m.estado,
                "merchant": m.merchant,
                "description_clean": event.description_clean if event else None,
                "broker_type": event.broker_type if event else None,
                "clasificacion": cl_cat,
            })
        return result


@router.post("/{import_id}/classify")
def run_classification(import_id: int):
    """Ejecuta el pipeline de clasificación sobre los movimientos pendientes."""
    stats = classify_pending()
    return stats


@router.get("/{import_id}/reconciliation")
def get_reconciliation(import_id: int):
    """Informe de reconciliación: suma de importes de las filas vs BD.

    Usa ``raw_rows`` (fuente inmutable) y el mapping guardado por el extractor
    agéntico. Así funciona con CSV de cualquier banco, PDF y ficheros que ya no
    están en disco.
    """
    from collections import defaultdict

    from sqlalchemy import func

    from .ingest.text import parse_decimal

    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).first()
        if not sf:
            raise HTTPException(404, f"Import {import_id} no encontrado")
        meta: dict = {}
        if sf.extraction_meta:
            try:
                meta = json.loads(sf.extraction_meta)
            except (TypeError, ValueError):
                meta = {}
        mapping = meta.get("mapping") or {}
        raw_rows = (
            s.query(RawRow)
            .filter(RawRow.source_file_id == import_id)
            .order_by(RawRow.row_index)
            .all()
        )

    csv_totals = defaultdict(Decimal)
    csv_rows = 0
    for raw in raw_rows:
        csv_rows += 1
        try:
            payload = json.loads(raw.payload)
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        values = payload.get("values")
        if isinstance(values, dict):
            amt = _raw_amount(values, mapping)
        else:
            # Fila legacy plana o fila de PDF con campos canónicos.
            fields = payload.get("fields")
            source = fields if isinstance(fields, dict) else payload
            amt = parse_decimal(source.get("amount")) if isinstance(source, dict) else None
        if amt is None:
            continue
        csv_totals["total"] += amt
        kind = (
            (payload.get("values") or {}).get("type")
            if isinstance(payload.get("values"), dict)
            else payload.get("type")
        ) or "UNKNOWN"
        csv_totals[f"type_{kind}"] += amt

    db_totals = defaultdict(Decimal)
    with _session() as s:
        rows = (
            s.query(FinancialMovement.kind, func.sum(FinancialMovement.amount))
            .join(MovementSource)
            .filter(MovementSource.source_file_id == import_id)
            .group_by(FinancialMovement.kind)
            .all()
        )
        for kind, amt in rows:
            db_totals[kind] = Decimal(str(amt)) if amt else Decimal("0")

    return {
        "source_file_id": import_id,
        "storage_available": bool(sf.storage_path and os.path.exists(sf.storage_path)),
        "csv_rows": csv_rows,
        "db_movements": sum(db_totals.values()),
        "csv_total": float(csv_totals["total"]),
        "db_total": float(sum(db_totals.values())),
        "difference": float(csv_totals["total"] - sum(db_totals.values())),
        "by_kind": {
            k: {
                "csv": float(csv_totals.get(f"type_{k}", Decimal("0"))),
                "db": float(db_totals.get(k, Decimal("0"))),
            }
            for k in set(
                dict.fromkeys(
                    k[5:] for k in csv_totals if k.startswith("type_")
                ).keys()
            )
            | set(db_totals.keys())
        },
    }


def _raw_amount(values: dict, mapping: dict) -> Decimal | None:
    """Importe de una fila cruda usando el mapping agéntico."""
    from .ingest.text import parse_decimal

    debit = parse_decimal(values.get(mapping.get("debit_column") or ""))
    credit = parse_decimal(values.get(mapping.get("credit_column") or ""))
    if debit is not None or credit is not None:
        return (credit or Decimal("0")) - abs(debit or Decimal("0"))
    amount = parse_decimal(values.get(mapping.get("amount_column") or ""))
    if amount is None:
        return None
    if mapping.get("sign_convention") == "outflow_positive" and amount > 0:
        return -amount
    return amount
