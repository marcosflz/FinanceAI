"""
API endpoints para el modelo v2 (financial_movements, clasificación, analytics).
"""

import json
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from .db.session import _session
from .models import (
    AppConfig, ClassificationJob, FinancialMovement, NormalizedEvent,
    Classification, ClassificationRule, Categoria, MovementSource,
    MovementLink, SourceFile, Account, DedupCandidate,
)
from .classify.rules import run_rule_for_movement, RuleEngine
from .classify.memory import lookup as memory_lookup, record as memory_record, correct as memory_correct
from .classify.pipeline import classify_one
from .classify.review_policy import keep_transfers_in_review
from .classify.llm_batch import classify_batch, LLMError
from .dedup import score_similarity
from .taxonomy import (
    category_choices_paths,
    category_path,
    category_paths,
    resolve_assignable_category,
)
from sqlalchemy import func, or_, select

# ── Background classification jobs ────────────────────────────────────────────

_BATCH_SIZE = 25
_cancel_flags: dict[int, threading.Event] = {}
_job_lock = threading.Lock()


@keep_transfers_in_review
def _run_classify_job(job_id: int) -> None:
    """Worker: reglas + memoria para todos, luego LLM por batches de 25."""
    cancel = _cancel_flags.get(job_id)
    log: list[dict] = []
    _log_processed = 0

    def append_log(method: str, merchant: str, categoria: str, confianza: float, explicacion: str) -> None:
        nonlocal _log_processed
        _log_processed += 1
        log.append({
            "ts": datetime.utcnow().isoformat(),
            "method": method,
            "merchant": merchant,
            "categoria": categoria,
            "confianza": confianza,
            "explicacion": explicacion,
        })
        if len(log) > 10000:
            log[:5000] = []

    def save_job(final: bool = False) -> None:
        with _session() as s:
            job = s.query(ClassificationJob).filter_by(id=job_id).first()
            if not job:
                return
            job.processed = _log_processed
            job.rule_count = sum(1 for l in log if l["method"] == "rule")
            job.memory_count = sum(1 for l in log if l["method"] == "memory")
            job.llm_count = sum(1 for l in log if l["method"] == "llm")
            job.failed_count = sum(1 for l in log if l["method"] == "failed")
            job.log_lines = json.dumps(log[-500:])
            if final:
                unclassified = (
                    s.query(FinancialMovement.id)
                    .outerjoin(
                        Classification,
                        (Classification.movement_id == FinancialMovement.id)
                        & (Classification.vigente == True)  # noqa: E712
                        & (Classification.categoria_id.isnot(None)),
                    )
                    .filter(
                        FinancialMovement.estado == "pendiente",
                        Classification.id.is_(None),
                    )
                    .count()
                )
                if unclassified > 0:
                    job.status = "failed"
                    job.error = (
                        f"{unclassified} movimientos pendientes sin clasificar"
                    )
                else:
                    job.status = "completed"
                job.finished_at = datetime.utcnow()

    def check_cancel() -> bool:
        if cancel and cancel.is_set():
            with _session() as s:
                s.query(ClassificationJob).filter_by(id=job_id).update(
                    {"status": "cancelled", "finished_at": datetime.utcnow()}
                )
                s.commit()
            save_job()
            return True
        return False

    def save_cl(
        mov_id: int, categoria_id: int | None, subtipo: str | None,
        origen: str, confianza_val: Decimal, explicacion: str,
    ) -> None:
        with _session() as s:
            old = s.query(Classification).filter(
                Classification.movement_id == mov_id,
                Classification.vigente == True,
            ).all()
            resolved = (
                resolve_assignable_category(s, categoria_id)
                if categoria_id is not None
                else None
            )
            for o in old:
                o.vigente = False
            s.add(Classification(
                movement_id=mov_id,
                categoria_id=resolved.id if resolved is not None else categoria_id,
                subtipo=subtipo, origen=origen,
                confianza=confianza_val, explicacion=explicacion[:500],
                vigente=True,
            ))
            s.commit()

    def get_cats() -> list[str]:
        with _session() as s:
            return category_choices_paths(s)

    def get_subtipos() -> dict:
        from .db.lookups import get_subtipo_descriptions
        return get_subtipo_descriptions()

    try:
        # 1. Contar total (pendientes sin clasificación vigente con categoría)
        with _session() as s:
            total = (
                s.query(FinancialMovement.id)
                .outerjoin(
                    Classification,
                    (Classification.movement_id == FinancialMovement.id)
                    & (Classification.vigente == True)  # noqa: E712
                    & (Classification.categoria_id.isnot(None)),
                )
                .filter(
                    FinancialMovement.estado == "pendiente",
                    Classification.id.is_(None),
                )
                .count()
            )
            s.query(ClassificationJob).filter_by(id=job_id).update(
                {"status": "running", "total": total}
            )
            s.commit()

        # 2. Obtener datos de los pendientes sin categoría
        pending: list[dict] = []
        with _session() as s:
            rows = (
                s.query(FinancialMovement, NormalizedEvent)
                .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
                .outerjoin(
                    Classification,
                    (Classification.movement_id == FinancialMovement.id)
                    & (Classification.vigente == True)  # noqa: E712
                    & (Classification.categoria_id.isnot(None)),
                )
                .filter(
                    FinancialMovement.estado == "pendiente",
                    Classification.id.is_(None),
                )
                .order_by(FinancialMovement.value_date)
                .all()
            )
            for mov, event in rows:
                pending.append({
                    "id": mov.id,
                    "merchant": mov.merchant or "",
                    "kind": mov.kind,
                    "amount": str(mov.amount) if mov.amount else "0",
                    "descripcion": event.description_clean if event else "",
                    "mcc_code": event.mcc_code if event else None,
                    "broker_type": event.broker_type if event else None,
                    "counterparty_name": event.counterparty_name if event else None,
                    "counterparty_iban": event.counterparty_iban if event else None,
                })
            # Reglas precompiladas una sola vez para todo el job.
            rule_engine = RuleEngine.from_session(s)

        # 3. Ronda 1: Reglas deterministas
        need_llm: list[dict] = []
        for p in pending:
            if check_cancel():
                return
            cl, actions = run_rule_for_movement(
                mov_id=p["id"], merchant=p["merchant"], kind=p["kind"],
                description_clean=p["descripcion"], mcc_code=p["mcc_code"],
                broker_type=p["broker_type"],
                counterparty_name=p.get("counterparty_name"),
                counterparty_iban=p.get("counterparty_iban"),
                engine=rule_engine,
            )
            # Aplicar acciones de regla (kind, merchant, auto-aprobar)
            if actions:
                with _session() as s2:
                    m = s2.query(FinancialMovement).filter_by(id=p["id"]).first()
                    if m:
                        if actions.get("set_kind"):
                            m.kind = actions["set_kind"]
                        if actions.get("set_merchant"):
                            m.merchant = actions["set_merchant"]
                        if actions.get("auto_aprobar"):
                            m.estado = "aprobado"
                        s2.commit()
            if cl:
                cat_name = ""
                if cl.categoria_id:
                    with _session() as s2:
                        c = s2.query(Categoria).filter_by(id=cl.categoria_id).first()
                        if c:
                            cat_name = category_path(s2, c)
                save_cl(p["id"], cl.categoria_id, cl.subtipo, "rule", cl.confianza, cl.explicacion)
                append_log("rule", p["merchant"], cat_name,
                           float(cl.confianza) if cl.confianza else 1.0, cl.explicacion or "")
                save_job()
                continue
            need_llm.append(p)

        # 4. Ronda 2: Memoria
        llm_rest: list[dict] = []
        for p in need_llm:
            if check_cancel():
                return
            mem = memory_lookup(p["id"], p["merchant"], p["mcc_code"], p["broker_type"])
            if mem and mem.get("confianza", 0) >= Decimal("0.85"):
                cat_id = mem["categoria_id"]
                st = mem.get("subtipo")
                conf = mem["confianza"]
                cat_name = mem.get("categoria_nombre", "")
                save_cl(p["id"], cat_id, st, "memory", conf,
                        f"Precedente: {cat_name} (confianza {conf})")
                memory_record(p["id"], p["merchant"], p["mcc_code"], p["broker_type"],
                              cat_id, subtipo=st, origen="memory")
                append_log("memory", p["merchant"], cat_name, float(conf), f"Por precedente: {cat_name}")
                save_job()
                continue
            llm_rest.append(p)

        # 5. Ronda 3: LLM por batches
        categorias = get_cats()
        subtipos_descs = get_subtipos()
        with _session() as s:
            cat_ids = {
                path: cat_id for cat_id, path in category_paths(s).items()
            }
        for i in range(0, len(llm_rest), _BATCH_SIZE):
            if check_cancel():
                return
            chunk = llm_rest[i:i + _BATCH_SIZE]
            chunk_ids = {p["id"] for p in chunk}
            returned_ids: set[int] = set()
            try:
                results = classify_batch(chunk, categorias, subtipos_descs)
                for r in results:
                    mov_id = r.get("id")
                    if mov_id is not None:
                        returned_ids.add(mov_id)
                    cat_name = r.get("categoria")
                    confianza_v = float(r.get("confianza", 0.5))
                    cat_id = cat_ids.get(cat_name) if cat_name else None
                    if cat_id is not None and confianza_v >= 0.3:
                        save_cl(mov_id, cat_id, r.get("subtipo"),
                                "llm", Decimal(str(confianza_v)),
                                r.get("explicacion", ""))
                        append_log("llm", r.get("merchant", "") or "",
                                   cat_name, confianza_v, r.get("explicacion", ""))
                        continue
                    append_log(
                        "failed", r.get("merchant", "") or "", "", 0.0,
                        "Categoría inválida o confianza baja en respuesta LLM",
                    )
                # El LLM puede devolver menos resultados que el lote: los IDs
                # no devueltos se marcan como fallidos (no se da por hecho).
                for p in chunk:
                    if p["id"] not in returned_ids:
                        append_log(
                            "failed", p.get("merchant", ""), "", 0.0,
                            f"El LLM no devolvió resultado para el movimiento {p['id']}",
                        )
            except LLMError as e:
                for p in chunk:
                    append_log(
                        "failed", p.get("merchant", ""), "", 0.0,
                        f"Error LLM ({type(e).__name__}): {str(e)[:160]}",
                    )
            except Exception as e:
                for p in chunk:
                    append_log(
                        "failed", p.get("merchant", ""), "", 0.0,
                        f"Error inesperado LLM ({type(e).__name__}): {str(e)[:160]}",
                    )
            save_job()

        save_job(final=True)
    except Exception as e:
        with _session() as s:
            s.query(ClassificationJob).filter_by(id=job_id).update(
                {"status": "failed", "error": str(e), "finished_at": datetime.utcnow()}
            )
            s.commit()
    finally:
        _cancel_flags.pop(job_id, None)

router = APIRouter(tags=["v2"])


def cleanup_stale_jobs() -> None:
    """Marca como failed jobs running/pending que sobreviven a reinicios."""
    from datetime import timedelta
    with _session() as s:
        stale = s.query(ClassificationJob).filter(
            ClassificationJob.status.in_(["pending", "running"])
        ).all()
        now = datetime.utcnow()
        for job in stale:
            job.status = "failed"
            job.error = "Stale job tras reinicio del backend"
            job.finished_at = now
        if stale:
            s.commit()


# ── Schemas ─────────────────────────────────────────────────────────────────

class V2MovFilter(BaseModel):
    estado: Optional[str] = None
    kind: Optional[str] = None
    origen: Optional[str] = None
    categoria_id: Optional[int] = None
    subtipo: Optional[str] = None
    desde: Optional[str] = None
    hasta: Optional[str] = None
    account_id: Optional[int] = None
    q: Optional[str] = None
    sort: str = "fecha_desc"
    page: int = 1
    page_size: int = 100


class V2MovementUpdate(BaseModel):
    estado: Optional[str] = None
    categoria_id: Optional[int] = None
    subtipo: Optional[str] = None
    merchant: Optional[str] = None
    nota: Optional[str] = None


class V2BulkAction(BaseModel):
    ids: list[int]
    action: str  # approve | reject | reopen | set_category (o alias ES)
    categoria_id: Optional[int] = None
    subtipo: Optional[str] = None


def _category_path_obj(category) -> str | None:
    if category is None:
        return None
    names = []
    current = category
    guard = 0
    while current is not None and guard < 32:
        names.append(current.nombre)
        current = current.parent
        guard += 1
    return " › ".join(reversed(names))


def _mov_to_dict(m: FinancialMovement, event, cl) -> dict:
    cl_data = None
    cat_name = None
    cat_path = None
    if cl:
        cat = cl.categoria
        if cat:
            cat_name = cat.nombre
            cat_path = _category_path_obj(cat)
        root = cat.parent if cat is not None and cat.parent is not None else cat
        child = cat if cat is not None and cat.parent is not None else None
        cl_data = {
            "categoria": cat_path or cat_name,
            "categoria_nombre": cat_name,
            "categoria_path": cat_path,
            "categoria_id": cl.categoria_id,
            "categoria_raiz_id": root.id if root is not None else None,
            "categoria_raiz_nombre": root.nombre if root is not None else None,
            "subcategoria_id": child.id if child is not None else None,
            "subcategoria_nombre": child.nombre if child is not None else None,
            "subtipo": cl.subtipo,
            "origen": cl.origen,
            "confianza": float(cl.confianza) if cl.confianza else None,
            "explicacion": cl.explicacion,
            "modelo": cl.modelo,
            "prompt_version": cl.prompt_version,
            "vigente": bool(cl.vigente),
            "creado_en": cl.creado_en.isoformat() if cl.creado_en else None,
        }

    account = getattr(m, "account", None)
    account_destino = getattr(m, "account_destino", None)
    account_data = (
        {"id": account.id, "nombre": account.nombre, "tipo": account.tipo}
        if account is not None
        else None
    )
    account_destino_data = (
        {
            "id": account_destino.id,
            "nombre": account_destino.nombre,
            "tipo": account_destino.tipo,
        }
        if account_destino is not None
        else None
    )
    return {
        "id": m.id,
        "kind": m.kind,
        "direction": m.direction,
        "amount": float(m.amount) if m.amount else None,
        "currency": m.currency,
        "value_date": m.value_date.isoformat() if m.value_date else None,
        "occurred_at": (
            event.occurred_at.isoformat()
            if event and event.occurred_at
            else None
        ),
        "estado": m.estado,
        "merchant": m.merchant,
        "description": event.description_clean if event else None,
        "description_clean": event.description_clean if event else None,
        "broker_type": event.broker_type if event else None,
        "mcc_code": event.mcc_code if event else None,
        "counterparty_name": event.counterparty_name if event else None,
        "counterparty_iban": event.counterparty_iban if event else None,
        "fee": float(event.fee) if event and event.fee else None,
        "tax": float(event.tax) if event and event.tax else None,
        "account_id": m.account_id,
        "account": account_data,
        "account_destino_id": m.account_destino_id,
        "account_destino": account_destino_data,
        "classification": cl_data,
        "clasificacion": cl_data,
    }


# ── Movements ────────────────────────────────────────────────────────────────

@router.get("/movements")
def list_movements(
    estado: Optional[str] = Query(default=None),
    kind: Optional[str] = Query(default=None),
    origen: Optional[str] = Query(default=None),
    categoria_id: Optional[int] = Query(default=None),
    subcategoria_id: Optional[int] = Query(default=None),
    subtipo: Optional[str] = Query(default=None),
    desde: Optional[str] = Query(default=None),
    hasta: Optional[str] = Query(default=None),
    from_: Optional[str] = Query(default=None, alias="from"),
    to_: Optional[str] = Query(default=None, alias="to"),
    account_id: Optional[int] = Query(default=None),
    q: Optional[str] = Query(default=None),
    tab: Optional[str] = Query(default=None),
    min_confidence: Optional[float] = Query(default=None, ge=0, le=1),
    sort: str = Query(default="fecha_desc"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, le=500),
):
    """Lista movimientos v2/v3 con filtros combinables. Sin duplicados."""
    desde = desde or from_
    hasta = hasta or to_
    with _session() as s:
        query = s.query(FinancialMovement)

        if estado:
            query = query.filter(FinancialMovement.estado == estado)

        # Tabs de la bandeja: se resuelven en servidor para que la paginación
        # y los contadores sean correctos (no solo la página visible).
        if tab == "por-revisar":
            query = query.filter(FinancialMovement.estado == "pendiente")
        elif tab == "transferencias":
            transfer_sub = (
                select(Classification.movement_id)
                .join(Categoria, Categoria.id == Classification.categoria_id)
                .where(
                    Classification.vigente == True,  # noqa: E712
                    Categoria.tratamiento == "transferencia",
                )
            )
            query = query.filter(
                or_(
                    FinancialMovement.kind == "transferencia_interna",
                    FinancialMovement.id.in_(transfer_sub),
                )
            )
        elif tab == "sin-categorizar":
            category_sub = (
                s.query(Classification.movement_id)
                .filter(
                    Classification.vigente == True,  # noqa: E712
                    Classification.categoria_id.isnot(None),
                )
                .subquery()
            )
            query = query.filter(~FinancialMovement.id.in_(category_sub))
        elif tab == "duplicados":
            query = query.filter(FinancialMovement.estado == "pendiente")
            dedup_sub = (
                s.query(DedupCandidate.movement_a)
                .filter(DedupCandidate.estado == "pendiente")
                .subquery()
            )
            dedup_sub_b = (
                s.query(DedupCandidate.movement_b)
                .filter(DedupCandidate.estado == "pendiente")
                .subquery()
            )
            query = query.filter(
                or_(
                    FinancialMovement.id.in_(dedup_sub),
                    FinancialMovement.id.in_(dedup_sub_b),
                )
            )
        if kind:
            query = query.filter(FinancialMovement.kind == kind)
        if desde:
            query = query.filter(FinancialMovement.value_date >= desde)
        if hasta:
            query = query.filter(FinancialMovement.value_date <= hasta)
        if account_id:
            query = query.filter(
                or_(FinancialMovement.account_id == account_id,
                    FinancialMovement.account_destino_id == account_id)
            )
        if q:
            like = f"%{q}%"
            query = query.filter(
                or_(FinancialMovement.merchant.ilike(like),
                    FinancialMovement.nota.ilike(like))
            )

        # Filtro por origen de clasificación
        if origen:
            cl_sub = (
                s.query(Classification.movement_id)
                .filter(Classification.vigente == True,
                        Classification.origen == origen)
                .subquery()
            )
            query = query.filter(FinancialMovement.id.in_(cl_sub))

        if subtipo:
            cl_sub = (
                s.query(Classification.movement_id)
                .filter(Classification.vigente == True,
                        Classification.subtipo == subtipo)
                .subquery()
            )
            query = query.filter(FinancialMovement.id.in_(cl_sub))

        if min_confidence is not None:
            confidence_sub = (
                s.query(Classification.movement_id)
                .filter(
                    Classification.vigente == True,  # noqa: E712
                    Classification.confianza.isnot(None),
                    Classification.confianza >= min_confidence,
                )
                .subquery()
            )
            query = query.filter(FinancialMovement.id.in_(confidence_sub))

        if subcategoria_id:
            cl_sub = (
                s.query(Classification.movement_id)
                .filter(
                    Classification.vigente == True,  # noqa: E712
                    Classification.categoria_id == subcategoria_id,
                )
                .subquery()
            )
            query = query.filter(FinancialMovement.id.in_(cl_sub))
        elif categoria_id:
            # Filtrar por una categoría raíz incluye todas sus subcategorías.
            category_ids = {categoria_id}
            pending = [categoria_id]
            while pending:
                current = pending.pop()
                for (child_id,) in (
                    s.query(Categoria.id)
                    .filter(Categoria.parent_id == current)
                    .all()
                ):
                    if child_id not in category_ids:
                        category_ids.add(child_id)
                        pending.append(child_id)
            cl_sub = (
                s.query(Classification.movement_id)
                .filter(Classification.vigente == True,
                        Classification.categoria_id.in_(category_ids))
                .subquery()
            )
            query = query.filter(FinancialMovement.id.in_(cl_sub))

        if sort == "fecha_desc":
            query = query.order_by(FinancialMovement.value_date.desc())
        elif sort == "fecha_asc":
            query = query.order_by(FinancialMovement.value_date.asc())
        elif sort == "confianza_asc":
            cl_sub = (
                s.query(Classification.movement_id, Classification.confianza)
                .filter(Classification.vigente == True)
                .subquery()
            )
            query = query.outerjoin(cl_sub, cl_sub.c.movement_id == FinancialMovement.id)
            query = query.order_by(cl_sub.c.confianza.asc().nullsfirst())

        total = query.count()
        movs = query.offset((page - 1) * page_size).limit(page_size).all()

        results = []
        for m in movs:
            event = s.query(NormalizedEvent).filter_by(id=m.event_id).first()
            cl = (
                s.query(Classification)
                .filter(Classification.movement_id == m.id,
                        Classification.vigente == True)
                .first()
            )
            results.append(_mov_to_dict(m, event, cl))

        return {
            "items": results,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size,
            # Compatibilidad con el cliente nuevo; la paginación actual es
            # por offset y no necesita cursor.
            "next_cursor": None,
        }


@router.get("/movements/stats")
def movement_stats():
    """Totales globales: total, pendientes, aprobados (sin paginación)."""
    with _session() as s:
        total = s.query(FinancialMovement).count()
        pendientes = s.query(FinancialMovement).filter(
            FinancialMovement.estado == "pendiente"
        ).count()
        aprobados = s.query(FinancialMovement).filter(
            FinancialMovement.estado == "aprobado"
        ).count()
        return {
            "total": total,
            "pendientes": pendientes,
            "aprobados": aprobados,
        }


@router.get("/movements/{mov_id}")
def get_movement_detail(mov_id: int):
    """Detalle completo de un movimiento: evento, clasificación, fuentes, vínculos."""
    with _session() as s:
        m = s.query(FinancialMovement).filter_by(id=mov_id).first()
        if not m:
            raise HTTPException(404, "Movimiento no encontrado")

        event = s.query(NormalizedEvent).filter_by(id=m.event_id).first()
        cl = (
            s.query(Classification)
            .filter(Classification.movement_id == mov_id,
                    Classification.vigente == True)
            .first()
        )

        sources = []
        for ms in s.query(MovementSource).filter_by(movement_id=mov_id).all():
            sf = s.query(SourceFile).filter_by(id=ms.source_file_id).first()
            sources.append({
                "source_file_id": ms.source_file_id,
                "filename": sf.filename if sf else None,
                "row_index": ms.raw_row_id,
                "match_type": ms.match_type,
                "first_seen": ms.first_seen_en.isoformat() if ms.first_seen_en else None,
            })

        links = []
        for ln in s.query(MovementLink).filter(
                or_(MovementLink.movement_a == mov_id,
                    MovementLink.movement_b == mov_id)).all():
            paired_id = ln.movement_b if ln.movement_a == mov_id else ln.movement_a
            links.append({
                "link_id": ln.id,
                "paired_movement_id": paired_id,
                "link_type": ln.link_type,
                "confianza": ln.confianza,
            })

        cl_data = None
        if cl:
            cat = cl.categoria
            cata_name = cat.nombre if cat else None
            cata_path = _category_path_obj(cat)
            root = cat.parent if cat is not None and cat.parent is not None else cat
            child = cat if cat is not None and cat.parent is not None else None
            cl_data = {
                "categoria": cata_path or cata_name,
                "categoria_nombre": cata_name,
                "categoria_path": cata_path,
                "categoria_id": cl.categoria_id,
                "categoria_raiz_id": root.id if root is not None else None,
                "categoria_raiz_nombre": root.nombre if root is not None else None,
                "subcategoria_id": child.id if child is not None else None,
                "subcategoria_nombre": child.nombre if child is not None else None,
                "subtipo": cl.subtipo,
                "origen": cl.origen,
                "confianza": float(cl.confianza) if cl.confianza else None,
                "explicacion": cl.explicacion,
                "modelo": cl.modelo,
                "creado_en": cl.creado_en.isoformat() if cl.creado_en else None,
            }

        event_data = None
        if event:
            event_data = {
                "source_txn_id": event.source_txn_id,
                "broker_type": event.broker_type,
                "occurred_at": event.occurred_at.isoformat() if event.occurred_at else None,
                "value_date": event.value_date.isoformat() if event.value_date else None,
                "amount": float(event.amount) if event.amount else None,
                "fee": float(event.fee) if event.fee else None,
                "tax": float(event.tax) if event.tax else None,
                "currency": event.currency,
                "original_amount": float(event.original_amount) if event.original_amount else None,
                "original_currency": event.original_currency,
                "fx_rate": float(event.fx_rate) if event.fx_rate else None,
                "asset_symbol": event.asset_symbol,
                "asset_name": event.asset_name,
                "asset_class": event.asset_class,
                "shares": float(event.shares) if event.shares else None,
                "price": float(event.price) if event.price else None,
                "counterparty_name": event.counterparty_name,
                "counterparty_iban": event.counterparty_iban,
                "mcc_code": event.mcc_code,
                "description_raw": event.description_raw,
                "description_clean": event.description_clean,
            }

        return {
            "id": m.id,
            "kind": m.kind,
            "direction": m.direction,
            "amount": float(m.amount) if m.amount else None,
            "currency": m.currency,
            "amount_eur": float(m.amount_eur) if m.amount_eur else None,
            "fx_rate_to_eur": (
                float(m.fx_rate_to_eur) if m.fx_rate_to_eur else None
            ),
            "fx_source": m.fx_source,
            "fx_date": m.fx_date.isoformat() if m.fx_date else None,
            "value_date": m.value_date.isoformat() if m.value_date else None,
            "estado": m.estado,
            "merchant": m.merchant,
            "nota": m.nota,
            "account_id": m.account_id,
            "account_destino_id": m.account_destino_id,
            "creado_en": m.creado_en.isoformat() if m.creado_en else None,
            "actualizado_en": m.actualizado_en.isoformat() if m.actualizado_en else None,
            "event": event_data,
            "clasificacion": cl_data,
            "sources": sources,
            "links": links,
        }


@router.patch("/movements/{mov_id}")
def update_movement(mov_id: int, body: V2MovementUpdate):
    """Edita un movimiento: estado, categoría, subtipo, merchant, nota."""
    with _session() as s:
        m = s.query(FinancialMovement).filter_by(id=mov_id).first()
        if not m:
            raise HTTPException(404, "Movimiento no encontrado")

        changed = {}

        if body.estado is not None:
            if body.estado not in {"pendiente", "aprobado", "rechazado"}:
                raise HTTPException(422, "estado debe ser pendiente, aprobado o rechazado")
            m.estado = body.estado
            changed["estado"] = body.estado

        if body.merchant is not None:
            m.merchant = body.merchant
            changed["merchant"] = body.merchant

        if "nota" in body.model_fields_set:
            # ``null`` borra la nota (antes se ignoraba).
            m.nota = body.nota or None
            changed["nota"] = m.nota

        fields = body.model_fields_set
        old_cl = (
            s.query(Classification)
            .filter(
                Classification.movement_id == mov_id,
                Classification.vigente == True,  # noqa: E712
            )
            .first()
        )
        cat_id = old_cl.categoria_id if old_cl is not None else None
        subtipo = old_cl.subtipo if old_cl is not None else None
        if "categoria_id" in fields:
            cat_id = body.categoria_id
        if "subtipo" in fields:
            subtipo = body.subtipo
        if cat_id is not None:
            resolved = resolve_assignable_category(s, cat_id)
            if resolved is not None:
                cat_id = resolved.id

        # Solo se versiona la clasificación si el cliente ha tocado categoría o
        # subtipo. Un cambio de estado/merchant no debe borrar la categoría.
        if {"categoria_id", "subtipo"} & fields:
            if old_cl:
                old_cl.vigente = False

            cl = Classification(
                movement_id=mov_id,
                categoria_id=cat_id,
                subtipo=subtipo,
                origen="user",
                confianza=Decimal("1.0"),
                explicacion="Clasificado manualmente por el usuario",
                vigente=True,
            )
            s.add(cl)

            # Feedback loop: record o correct en memoria. Quitar la categoría
            # no es un precedente que aprender.
            merchant_for_mem = m.merchant or ""
            if cat_id is None:
                pass
            elif old_cl and old_cl.categoria_id != cat_id:
                memory_correct(
                    mov_id, merchant_for_mem,
                    mcc=None, broker_type=None,
                    categoria_id=cat_id, subtipo=subtipo,
                    session=s,
                )
            else:
                memory_record(
                    mov_id, merchant_for_mem,
                    mcc=None, broker_type=None,
                    categoria_id=cat_id, subtipo=subtipo,
                    session=s,
                )

        s.flush()
        event = s.query(NormalizedEvent).filter_by(id=m.event_id).first()
        cl = (
            s.query(Classification)
            .filter(Classification.movement_id == mov_id,
                    Classification.vigente == True)
            .first()
        )
        return _mov_to_dict(m, event, cl)


@router.post("/movements/bulk")
def bulk_action(body: V2BulkAction):
    """Acciones masivas sobre movimientos."""
    with _session() as s:
        movs = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.id.in_(body.ids))
            .all()
        )
        if not movs:
            raise HTTPException(400, "Ningún movimiento válido")

        action = {
            "aprobar": "approve",
            "rechazar": "reject",
            "reabrir": "reopen",
            "categorizar": "set_category",
        }.get(body.action, body.action)

        if action == "approve":
            for m in movs:
                m.estado = "aprobado"
        elif action == "reject":
            for m in movs:
                m.estado = "rechazado"
        elif action == "reopen":
            for m in movs:
                m.estado = "pendiente"
        elif action not in {"set_category"}:
            raise HTTPException(400, f"Acción desconocida: {body.action}")
        if action == "set_category":
            if not body.categoria_id:
                raise HTTPException(400, "categoria_id requerido")
            cat = resolve_assignable_category(s, body.categoria_id)
            if not cat:
                raise HTTPException(400, "Categoría no encontrada")
            for m in movs:
                old_cl = (
                    s.query(Classification)
                    .filter(Classification.movement_id == m.id,
                            Classification.vigente == True)
                    .first()
                )
                if old_cl:
                    old_cl.vigente = False
                cl = Classification(
                    movement_id=m.id,
                    categoria_id=cat.id,
                    subtipo=body.subtipo,
                    origen="user",
                    confianza=Decimal("1.0"),
                    explicacion=f"Asignada en lote: {cat.nombre}",
                    vigente=True,
                )
                s.add(cl)

        s.commit()
        return {"ok": True, "affected": len(movs), "updated": len(movs)}


# ── Classify ─────────────────────────────────────────────────────────────────

class ClassifyNextResult(BaseModel):
    processed: int
    remaining: int
    method: str
    movement: Optional[dict] = None


@router.post("/classify-next")
def classify_next(limit: int = Query(default=1, ge=1, le=50)):
    """Clasifica el/los siguiente(s) movimiento(s) pendiente(s) con progreso.

    Procesa hasta `limit` movimientos, uno a uno con LLM por llamada.
    Devuelve cuántos procesó, cuántos quedan y el método usado.
    """
    # Obtener IDs pendientes en sesión corta
    with _session() as s:
        # Solo movimientos pendientes sin una categoría vigente. Los que ya
        # tienen categoría (broker/regla) están esperando aprobación humana,
        # no una nueva llamada al clasificador.
        already_categorized = (
            s.query(Classification.id)
            .filter(
                Classification.movement_id == FinancialMovement.id,
                Classification.vigente == True,  # noqa: E712
                Classification.categoria_id.isnot(None),
            )
            .exists()
        )
        pendientes_ids = [
            r[0] for r in s.query(FinancialMovement.id)
            .filter(
                FinancialMovement.estado == "pendiente",
                ~already_categorized,
            )
            .order_by(FinancialMovement.value_date)
            .limit(limit)
            .all()
        ]

    if not pendientes_ids:
        return {"processed": 0, "remaining": 0, "method": "none", "movement": None}

    # Procesar uno a uno (classify_one maneja su propia sesión)
    processed = 0
    last_method = "none"
    last_mov_id = None
    for mov_id in pendientes_ids:
        result = classify_one(mov_id)
        processed += 1
        last_method = result.get("method", "none") if result else "none"
        last_mov_id = mov_id

    # Contar restantes en sesión fresca
    with _session() as s:
        remaining = s.query(FinancialMovement).filter(FinancialMovement.estado == "pendiente").count()

    # Devolver último movimiento procesado
    last_mov = None
    if processed > 0 and last_mov_id:
        with _session() as s:
            mov = s.query(FinancialMovement).filter_by(id=last_mov_id).first()
            if mov:
                cl = (
                    s.query(Classification)
                    .filter(Classification.movement_id == mov.id, Classification.vigente == True)
                    .first()
                )
                event = s.query(NormalizedEvent).filter_by(id=mov.event_id).first()
                last_mov = _mov_to_dict(mov, event, cl)

    return {
        "processed": processed,
        "remaining": remaining,
        "method": last_method,
        "movement": last_mov,
    }


# ── Stats ────────────────────────────────────────────────────────────────────


# ── Analytics ────────────────────────────────────────────────────────────────

@router.get("/analytics/daily-density")
def daily_density(desde: Optional[str] = Query(default=None),
                  hasta: Optional[str] = Query(default=None)):
    """Movimientos por día: {date, count, total_abs, total_net}."""
    with _session() as s:
        q = s.query(
            FinancialMovement.value_date,
            func.count(FinancialMovement.id).label("cnt"),
            func.sum(FinancialMovement.amount).label("total"),
        )
        if desde:
            q = q.filter(FinancialMovement.value_date >= desde)
        if hasta:
            q = q.filter(FinancialMovement.value_date <= hasta)
        q = q.group_by(FinancialMovement.value_date)
        q = q.order_by(FinancialMovement.value_date)

        results = []
        for row in q.all():
            results.append({
                "date": row.value_date.isoformat() if row.value_date else None,
                "count": row.cnt,
                "total_abs": float(abs(row.total)) if row.total else 0,
                "total_net": float(row.total) if row.total else 0,
            })
        return results


# ── Config ────────────────────────────────────────────────────────────────────

@router.get("/config/auto-approve")
def get_auto_approve():
    """Devuelve la lista de kinds con auto-aprobación activada."""
    with _session() as s:
        row = s.query(AppConfig).filter_by(key="auto_approve_kinds").first()
        if row and row.value:
            try:
                return {"kinds": json.loads(row.value)}
            except Exception:
                pass
        return {"kinds": [
            "inversion_compra", "inversion_venta", "dividendo",
            "interes", "cashback", "aporte_activo", "transferencia_interna",
        ]}


@router.patch("/config/auto-approve")
def set_auto_approve(body: dict):
    """Guarda la lista de kinds con auto-aprobación."""
    kinds = body.get("kinds", [])
    if not isinstance(kinds, list):
        raise HTTPException(400, "kinds debe ser una lista")
    with _session() as s:
        row = s.query(AppConfig).filter_by(key="auto_approve_kinds").first()
        if row:
            row.value = json.dumps(kinds)
        else:
            s.add(AppConfig(key="auto_approve_kinds", value=json.dumps(kinds)))
        s.commit()
    return {"kinds": kinds}


# ── Classification Rules CRUD ─────────────────────────────────────────────────


class RuleCreate(BaseModel):
    prioridad: int = 100
    campo: str
    operador: str
    valor: str
    set_categoria_id: Optional[int] = None
    set_subtipo: Optional[str] = None
    set_merchant: Optional[str] = None
    set_kind: Optional[str] = None
    auto_aprobar: bool = False
    activa: bool = True


class RuleUpdate(BaseModel):
    prioridad: Optional[int] = None
    campo: Optional[str] = None
    operador: Optional[str] = None
    valor: Optional[str] = None
    set_categoria_id: Optional[int] = None
    set_subtipo: Optional[str] = None
    set_merchant: Optional[str] = None
    set_kind: Optional[str] = None
    auto_aprobar: Optional[bool] = None
    activa: Optional[bool] = None


def _rule_to_dict(r: ClassificationRule, cat_name: str | None = None) -> dict:
    return {
        "id": r.id,
        "prioridad": r.prioridad,
        "campo": r.campo,
        "operador": r.operador,
        "valor": r.valor,
        "set_categoria_id": r.set_categoria_id,
        "set_subtipo": r.set_subtipo,
        "set_merchant": r.set_merchant,
        "set_kind": r.set_kind,
        "auto_aprobar": r.auto_aprobar,
        "activa": r.activa,
        "categoria_nombre": cat_name,
        "creado_en": r.creado_en.isoformat() if r.creado_en else None,
    }


@router.get("/classification-rules")
def list_rules():
    """Lista todas las reglas activas."""
    with _session() as s:
        rules = s.query(ClassificationRule).order_by(ClassificationRule.prioridad).all()
        result = []
        for r in rules:
            cat_name = None
            if r.set_categoria_id:
                cat = s.query(Categoria).filter_by(id=r.set_categoria_id).first()
                if cat:
                    cat_name = category_path(s, cat)
            result.append(_rule_to_dict(r, cat_name))
        return result


@router.post("/classification-rules")
def create_rule(body: RuleCreate):
    """Crea una nueva regla."""
    with _session() as s:
        set_categoria_id = body.set_categoria_id
        if set_categoria_id is not None:
            resolved = resolve_assignable_category(s, set_categoria_id)
            set_categoria_id = resolved.id if resolved is not None else None
        r = ClassificationRule(
            prioridad=body.prioridad,
            campo=body.campo,
            operador=body.operador,
            valor=body.valor,
            set_categoria_id=set_categoria_id,
            set_subtipo=body.set_subtipo,
            set_merchant=body.set_merchant,
            set_kind=body.set_kind,
            auto_aprobar=body.auto_aprobar,
            activa=body.activa,
        )
        s.add(r)
        s.commit()
        s.refresh(r)
        return _rule_to_dict(r)


@router.patch("/classification-rules/{rule_id}")
def update_rule(rule_id: int, body: RuleUpdate):
    """Actualiza una regla."""
    with _session() as s:
        r = s.query(ClassificationRule).filter_by(id=rule_id).first()
        if not r:
            raise HTTPException(404, "Regla no encontrada")
        if body.prioridad is not None:
            r.prioridad = body.prioridad
        if body.campo is not None:
            r.campo = body.campo
        if body.operador is not None:
            r.operador = body.operador
        if body.valor is not None:
            r.valor = body.valor
        if body.set_categoria_id is not None:
            if body.set_categoria_id == 0:
                r.set_categoria_id = None
            else:
                resolved = resolve_assignable_category(s, body.set_categoria_id)
                r.set_categoria_id = resolved.id if resolved is not None else None
        if body.set_subtipo is not None:
            r.set_subtipo = body.set_subtipo or None
        if body.set_merchant is not None:
            r.set_merchant = body.set_merchant or None
        if body.set_kind is not None:
            r.set_kind = body.set_kind or None
        if body.auto_aprobar is not None:
            r.auto_aprobar = body.auto_aprobar
        if body.activa is not None:
            r.activa = body.activa
        s.commit()
        s.refresh(r)
        return _rule_to_dict(r)


@router.delete("/classification-rules/{rule_id}")
def delete_rule(rule_id: int):
    """Elimina una regla."""
    with _session() as s:
        r = s.query(ClassificationRule).filter_by(id=rule_id).first()
        if not r:
            raise HTTPException(404, "Regla no encontrada")
        s.delete(r)
        s.commit()
    return {"ok": True}


@router.post("/classification-rules/reapply")
def reapply_rules():
    """Re-ejecuta todas las reglas sobre movimientos pendientes sin clasificar."""
    from .classify.pipeline import classify_pending
    stats = classify_pending(limit=200)
    return stats


class AutolearnApply(BaseModel):
    reglas: list[dict]


@router.get("/classification-rules/autolearn")
def autolearn_analyze():
    """Analiza el histórico aprobado y propone reglas (solo lectura)."""
    from .classify.autolearn import analyze
    return analyze()


@router.post("/classification-rules/autolearn")
def autolearn_apply(body: AutolearnApply):
    """Crea las reglas autoconfiguradas seleccionadas por el usuario."""
    from .classify.autolearn import apply_proposals
    if not body.reglas:
        raise HTTPException(400, "Sin reglas que aplicar")
    return apply_proposals(body.reglas)



# ── Classification Jobs (background) ──────────────────────────────────────────


class JobStatusResult(BaseModel):
    id: int
    status: str
    total: int
    processed: int
    rule_count: int
    memory_count: int
    llm_count: int
    failed_count: int
    log_lines: list[dict]
    created_at: str
    finished_at: Optional[str] = None
    error: Optional[str] = None


def _job_to_dict(job: ClassificationJob) -> dict:
    try:
        logs = json.loads(job.log_lines) if job.log_lines else []
    except (json.JSONDecodeError, TypeError):
        logs = []
    return {
        "id": job.id,
        "status": job.status,
        "total": job.total or 0,
        "processed": job.processed or 0,
        "rule_count": job.rule_count or 0,
        "memory_count": job.memory_count or 0,
        "llm_count": job.llm_count or 0,
        "failed_count": job.failed_count or 0,
        "log_lines": logs,
        "created_at": job.created_at.isoformat() if job.created_at else "",
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
    }


@router.post("/classify-job")
def start_classify_job():
    """Crea un nuevo job de clasificación y lo arranca en background."""
    with _session() as s:
        # Auto-clean stale jobs (running without a thread, or older than 1 min)
        stale = s.query(ClassificationJob).filter(
            ClassificationJob.status.in_(["pending", "running"])
        ).all()
        now = datetime.utcnow()
        for job in stale:
            # Stale if: no thread running OR older than 1 min (thread died)
            has_thread = _cancel_flags.get(job.id) is not None
            is_old = job.created_at and (now - job.created_at).total_seconds() > 60
            if not has_thread or is_old:
                job.status = "failed"
                job.error = "Stale job auto-cleaned (sin hilo activo)"
                job.finished_at = now
        if any(j.status in ("pending", "running") for j in stale):
            active = [j for j in stale if j.status in ("pending", "running")][0]
            raise HTTPException(409, f"Stale job #{active.id} no se pudo limpiar. "
                                      "Contacta al admin o borra la tabla classification_jobs.")
        job = ClassificationJob(status="pending", log_lines="[]")
        s.add(job)
        s.flush()
        job_id = job.id
        s.commit()

    with _job_lock:
        _cancel_flags[job_id] = threading.Event()
        t = threading.Thread(target=_run_classify_job, args=(job_id,), daemon=True)
        t.start()

    return {"job_id": job_id}


@router.get("/classify-job/{job_id}")
def get_classify_job(job_id: int):
    """Devuelve estado y logs de un job."""
    with _session() as s:
        job = s.query(ClassificationJob).filter_by(id=job_id).first()
        if not job:
            raise HTTPException(404, "Job no encontrado")
        return _job_to_dict(job)


@router.get("/classify-jobs/active")
def get_active_classify_job():
    """Devuelve el job activo más reciente o None."""
    with _session() as s:
        job = s.query(ClassificationJob).filter(
            ClassificationJob.status.in_(["pending", "running"])
        ).order_by(ClassificationJob.id.desc()).first()
        if job:
            return _job_to_dict(job)
        return None


@router.post("/classify-job/{job_id}/cancel")
def cancel_classify_job(job_id: int):
    """Cancela un job de clasificación en ejecución."""
    with _job_lock:
        ev = _cancel_flags.get(job_id)
        if ev:
            ev.set()
            return {"ok": True, "status": "cancelling"}
        # No cancel flag → check if already done
        with _session() as s:
            job = s.query(ClassificationJob).filter_by(id=job_id).first()
            if not job:
                raise HTTPException(404, "Job no encontrado")
            if job.status in ("completed", "cancelled", "failed"):
                return {"ok": True, "status": job.status}
            return {"ok": False, "status": "not_running"}
