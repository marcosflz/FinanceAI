"""
Pipeline de clasificación: reglas → memoria → LLM → validación → feedback.

``classify_pending`` carga pendientes + eventos en una sola consulta, evalúa
reglas y memoria en memoria y persiste en lote (un commit por fase). El LLM
solo se invoca para lo que queda y sus errores se propagan como fallos
explícitos, nunca como un ``completed`` vacío.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from ..ingest.accounts import base_broker_type
from .review_policy import keep_transfers_in_review
from ..db.lookups import get_categorias_nombres, get_subtipo_descriptions
from ..db.session import _session
from ..model_settings import load_model_settings
from ..models import (
    Categoria,
    Classification,
    FinancialMovement,
    MovementSource,
    NormalizedEvent,
)
from ..taxonomy import (
    DefaultSubcategoryMissing,
    category_path,
    category_paths,
    ensure_default_child,
    resolve_assignable_category,
    resolve_category_reference,
)
from .decider import (
    JEV_PROMPT_VERSION,
    DeciderNotConfigured,
    decide_movement,
)
from .decider import (
    is_configured as decider_is_configured,
)
from .llm_batch import LLMError
from .llm_batch import classify_batch as llm_classify_batch
from .llm_batch import classify_one as llm_classify_one
from .memory import (
    CONFIANZA_MIN_AUTO,
    _normalize_pattern,
    load_memory_index,
)
from .memory import (
    lookup as memory_lookup,
)
from .memory import (
    record as memory_record,
)
from .rules import RuleEngine

logger = logging.getLogger(__name__)

# Categoría por defecto para hechos deterministas del broker.
_BROKER_DEFAULT_CATEGORY = {
    "inversion_compra": "Inversiones › Compras",
    "inversion_venta": "Inversiones › Ventas",
    "dividendo": "Ingresos › Dividendos",
    "interes": "Ingresos › Intereses",
    # El cashback de Trade Republic es saveback en activo. Ingresos › Cashback
    # queda disponible para cashback fiat manual.
    "cashback": "Inversiones › Cashback",
    "aporte_activo": "Inversiones › Aportaciones",
    "transferencia_interna": "Transferencias › Otros",
}

_BROKER_TYPE_CATEGORY = {
    "BENEFITS_SAVEBACK": "Inversiones › Cashback",
}


@keep_transfers_in_review
def classify_one(movement_id: int) -> dict:
    """Clasifica UN movimiento por su ID a través del pipeline completo."""
    with _session() as s:
        mov = s.query(FinancialMovement).filter_by(id=movement_id).first()
        if not mov:
            return {"method": "skipped", "reason": "not_found"}
        if mov.estado != "pendiente":
            return {"method": "skipped", "reason": "not_pending"}

        event = s.query(NormalizedEvent).filter_by(id=mov.event_id).first()
        if not event:
            return {"method": "skipped", "reason": "no_event"}

        existing = (
            s.query(Classification)
            .filter(
                Classification.movement_id == mov.id,
                Classification.vigente == True,  # noqa: E712
            )
            .all()
        )
        if any(cl.categoria_id is not None for cl in existing):
            return {"method": "skipped", "reason": "already_classified"}

        engine = RuleEngine.from_session(s)
        snap = _snapshot(mov, event)
        mov_id = snap["id"]
        auto_threshold = Decimal(str(load_model_settings().auto_approve_threshold))
        hit = engine.evaluate(
            merchant=snap["merchant"], kind=snap["kind"],
            description_clean=snap["descripcion"], mcc_code=snap["mcc_code"],
            broker_type=snap["broker_type"],
            counterparty_name=snap["counterparty_name"],
            counterparty_iban=snap["counterparty_iban"],
        )
        if hit is not None:
            _apply_actions(mov, hit.actions)
            if hit.categoria_id:
                cl = _make_classification(
                    mov.id, hit.categoria_id, hit.subtipo, "rule",
                    Decimal("0.99"), hit.explicacion, session=s,
                )
                auto_approved = Decimal("0.99") >= auto_threshold
                if auto_approved:
                    mov.estado = "aprobado"
                _replace_vigente(s, mov.id, cl)
                s.flush()
                return {
                    "method": "rule",
                    "auto_approved": auto_approved,
                    "classification_id": cl.id,
                    "explicacion": cl.explicacion,
                }

        mem = memory_lookup(
            mov.id, snap["merchant"], snap["mcc_code"], snap["broker_type"],
            session=s,
        )
        if mem and mem.get("confianza", Decimal("0")) >= CONFIANZA_MIN_AUTO:
            cl = _make_classification(
                mov.id, mem["categoria_id"], mem.get("subtipo"), "memory",
                mem["confianza"],
                f"Precedente: {mem.get('categoria_nombre', '?')} "
                f"(confianza {mem['confianza']})",
                session=s,
            )
            auto_approved = (mem.get("confianza") or Decimal("0")) >= auto_threshold
            if auto_approved:
                mov.estado = "aprobado"
            _replace_vigente(s, mov.id, cl)
            s.flush()
            memory_result = {
                "method": "memory",
                "classification_id": cl.id,
                "categoria_id": mem["categoria_id"],
                "subtipo": mem.get("subtipo"),
                "confianza": mem["confianza"],
                "auto_approved": auto_approved,
            }
        else:
            memory_result = None

    if memory_result is not None:
        # Fuera de la sesión para no anidar transacciones.
        memory_record(
            movement_id, snap["merchant"], snap["mcc_code"], snap["broker_type"],
            memory_result["categoria_id"], subtipo=memory_result["subtipo"],
            origen="memory",
        )
        return {
            "method": "memory",
            "auto_approved": memory_result.get("auto_approved", False),
            "classification_id": memory_result["classification_id"],
        }

    # Paso 3: decisor tipado Jev (si está configurado). Solo recibe hechos
    # estructurados; nunca PDFs ni imágenes.
    categorias = get_categorias_nombres()
    subtipos = get_subtipo_descriptions()

    if decider_is_configured():
        try:
            decision = decide_movement(
                snap,
                categorias,
                precedents=_get_precedents(snap["merchant"]),
            )
        except DeciderNotConfigured:
            decision = None
        except Exception as exc:  # pragma: no cover - fallback defensivo
            logger.warning("Jev no pudo decidir el movimiento %s: %s", mov_id, exc)
            decision = None

        if decision and decision.get("categoria"):
            model_settings = load_model_settings()
            confidence = float(decision.get("confianza", 0) or 0)
            auto_approved = confidence >= model_settings.auto_approve_threshold
            with _session() as s:
                cat = resolve_category_reference(s, decision["categoria"])
                if cat:
                    cl = _make_classification(
                        mov_id,
                        cat.id,
                        None,
                        "decider",
                        Decimal(str(round(confidence, 3))),
                        (decision.get("explicacion") or "Decisión Jev")[:500],
                        session=s,
                    )
                    cl.modelo = (decision.get("model") or "jev-latest")[:60]
                    cl.prompt_version = JEV_PROMPT_VERSION
                    if auto_approved:
                        cl.explicacion = (
                            f"{cl.explicacion or 'Decisión Jev'} · autoaprobado "
                            f"(confianza {confidence:.2f} ≥ {model_settings.auto_approve_threshold:.2f})"
                        )[:500]
                        movement = s.query(FinancialMovement).filter_by(id=mov_id).first()
                        if movement is not None:
                            movement.estado = "aprobado"
                    _replace_vigente(s, mov_id, cl)
                    s.flush()
                    classification_id = cl.id
                else:
                    classification_id = None
            if classification_id is not None:
                return {
                    "method": (
                        "decider_auto"
                        if auto_approved
                        else (
                            "decider_review"
                            if decision.get("needs_review")
                            else "decider"
                        )
                    ),
                    "auto_approved": auto_approved,
                    "classification_id": classification_id,
                    "categoria": decision["categoria"],
                    "confianza": decision.get("confianza"),
                    "needs_review": (
                        False if auto_approved else bool(decision.get("needs_review"))
                    ),
                }

    # Paso 4: LLM (fuera de la sesión; no mantener transacciones abiertas)
    try:
        result = llm_classify_one(
            movement_data={
                "id": snap["id"],
                "merchant": snap["merchant"] or "",
                "descripcion": snap["descripcion"],
                "amount": snap["amount"],
                "kind": snap["kind"],
                "mcc_code": snap["mcc_code"],
                "broker_type": snap["broker_type"],
            },
            categorias=categorias,
            subtipo_descriptions=subtipos,
            precedents=_get_precedents(snap["merchant"]),
        )
    except LLMError as exc:
        return {"method": "failed", "error": str(exc)}

    if result and result.get("categoria"):
        with _session() as s:
            cat = resolve_category_reference(s, result["categoria"])
            if cat:
                cl = _make_classification(
                    mov_id, cat.id, result.get("subtipo"), "llm",
                    Decimal(str(result.get("confianza", 0.5))),
                    result.get("explicacion", "")[:500],
                    session=s,
                )
                _replace_vigente(s, mov_id, cl)
                s.flush()
                return {
                    "method": "llm",
                    "classification_id": cl.id,
                    "confianza": result.get("confianza"),
                }

    return {"method": "failed"}


@keep_transfers_in_review
def classify_batch(
    *,
    limit: int | None = None,
    import_id: int | None = None,
    movement_ids: list[int] | None = None,
) -> dict:
    """Clasifica un lote pequeño y devuelve las sugerencias sin aprobarlas.

    Las referencias crecen con las clasificaciones que el usuario ya aceptó
    (``origen='user'``). Jev solo decide categoría; la aprobación sigue siendo
    humana. Los aciertos deterministas de reglas/memoria no llaman a Jev.
    """
    model_settings = load_model_settings()
    effective_limit = model_settings.classification_batch_size if limit is None else limit
    limit = max(1, min(int(effective_limit), 50))
    results: list[dict] = []
    need_jev: list[dict] = []
    stats = {"rule": 0, "memory": 0, "decider": 0, "failed": 0}

    with _session() as s:
        query = (
            s.query(FinancialMovement, NormalizedEvent)
            .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .filter(FinancialMovement.estado == "pendiente")
        )
        if import_id is not None:
            query = query.join(
                MovementSource,
                MovementSource.movement_id == FinancialMovement.id,
            ).filter(MovementSource.source_file_id == import_id)
        if movement_ids:
            query = query.filter(FinancialMovement.id.in_(movement_ids))
        already_categorized = (
            s.query(Classification.id)
            .filter(
                Classification.movement_id == FinancialMovement.id,
                Classification.vigente.is_(True),
                Classification.categoria_id.isnot(None),
            )
            .exists()
        )
        candidates = (
            query.filter(~already_categorized)
            .order_by(FinancialMovement.value_date, FinancialMovement.id)
            .limit(limit)
            .all()
        )
        if not candidates:
            return {
                "items": [],
                "processed": 0,
                "remaining": 0,
                "reference_count": 0,
                "stats": stats,
            }

        engine = RuleEngine.from_session(s)
        memory_index = load_memory_index(s)
        category_names = {
            cat_id: name for cat_id, name in s.query(Categoria.id, Categoria.nombre).all()
        }
        from .references import load_accepted_references

        accepted_examples = load_accepted_references(s)
        auto_threshold = Decimal(str(model_settings.auto_approve_threshold))

        for movement, event in candidates:
            snap = _snapshot(movement, event)
            base = {
                "movement_id": movement.id,
                "value_date": movement.value_date.isoformat() if movement.value_date else None,
                "merchant": movement.merchant,
                "amount": str(movement.amount) if movement.amount is not None else None,
                "kind": movement.kind,
            }
            hit = engine.evaluate(
                merchant=snap["merchant"],
                kind=snap["kind"],
                description_clean=snap["descripcion"],
                mcc_code=snap["mcc_code"],
                broker_type=snap["broker_type"],
                counterparty_name=snap["counterparty_name"],
                counterparty_iban=snap["counterparty_iban"],
            )
            if hit is not None and hit.categoria_id:
                _apply_actions(movement, hit.actions)
                cl = _make_classification(
                    movement.id,
                    hit.categoria_id,
                    hit.subtipo,
                    "rule",
                    Decimal("0.99"),
                    hit.explicacion,
                    session=s,
                )
                rule_auto = Decimal("0.99") >= auto_threshold
                if rule_auto:
                    movement.estado = "aprobado"
                _replace_vigente(s, movement.id, cl)
                s.flush()
                results.append(
                    {
                        **base,
                        "method": "rule",
                        "auto_approved": rule_auto,
                        "categoria": category_names.get(cl.categoria_id),
                        "categoria_id": cl.categoria_id,
                        "subtipo": hit.subtipo,
                        "confianza": 0.99,
                        "needs_review": False,
                        "explicacion": hit.explicacion,
                        "reference_count": 0,
                    }
                )
                stats["rule"] += 1
                continue

            pattern = _normalize_pattern(snap["merchant"] or "")
            mem = memory_index.get(pattern)
            if mem and mem.get("confianza", Decimal("0")) >= CONFIANZA_MIN_AUTO:
                cl = _make_classification(
                    movement.id,
                    mem["categoria_id"],
                    mem.get("subtipo"),
                    "memory",
                    mem["confianza"],
                    f"Precedente: {mem.get('categoria_nombre', '?')}",
                    session=s,
                )
                memory_auto = (mem.get("confianza") or Decimal("0")) >= auto_threshold
                if memory_auto:
                    movement.estado = "aprobado"
                _replace_vigente(s, movement.id, cl)
                s.flush()
                results.append(
                    {
                        **base,
                        "method": "memory",
                        "auto_approved": memory_auto,
                        "categoria": category_names.get(cl.categoria_id),
                        "categoria_id": cl.categoria_id,
                        "subtipo": mem.get("subtipo"),
                        "confianza": float(mem["confianza"]),
                        "needs_review": False,
                        "explicacion": cl.explicacion,
                        "reference_count": 0,
                    }
                )
                stats["memory"] += 1
                continue

            need_jev.append(snap)
            results.append(
                {
                    **base,
                    "method": "pending_jev",
                    "categoria": None,
                    "categoria_id": None,
                    "subtipo": None,
                    "confianza": None,
                    "needs_review": True,
                    "explicacion": None,
                    "reference_count": 0,
                }
            )

        remaining = (
            s.query(FinancialMovement)
            .filter(FinancialMovement.estado == "pendiente")
            .count()
        )

    if need_jev and decider_is_configured():
        from .references import select_references

        call_limit = model_settings.jev_max_calls_per_run
        for snap in need_jev[:call_limit]:
            precedents = select_references(
                accepted_examples,
                current=snap,
                limit=model_settings.jev_reference_max,
            )
            try:
                decision = decide_movement(snap, get_categorias_nombres(), precedents=precedents)
            except Exception as exc:  # pragma: no cover - red/API
                logger.warning("Jev falló en lote %s: %s", snap.get("id"), exc)
                stats["failed"] += 1
                continue
            category_name = decision.get("categoria")
            confidence = float(decision.get("confianza", 0) or 0)
            auto_approved = (
                category_name is not None
                and confidence >= model_settings.auto_approve_threshold
            )
            with _session() as s:
                cat = (
                    resolve_category_reference(s, category_name)
                    if category_name
                    else None
                )
                if cat is None:
                    stats["failed"] += 1
                    continue
                cl = _make_classification(
                    snap["id"],
                    cat.id,
                    None,
                    "decider",
                    Decimal(str(round(float(decision.get("confianza", 0)), 3))),
                    (decision.get("explicacion") or "Decisión Jev")[:500],
                    session=s,
                )
                cl.modelo = (decision.get("model") or "jev-latest")[:60]
                cl.prompt_version = JEV_PROMPT_VERSION
                if auto_approved:
                    cl.explicacion = (
                        f"{cl.explicacion or 'Decisión Jev'} · autoaprobado "
                        f"(confianza {confidence:.2f} ≥ {model_settings.auto_approve_threshold:.2f})"
                    )[:500]
                _replace_vigente(s, snap["id"], cl)
                if auto_approved:
                    movement = s.query(FinancialMovement).filter_by(id=snap["id"]).first()
                    if movement is not None:
                        movement.estado = "aprobado"
                s.flush()
                classification_id = cl.id
                category_id = cl.categoria_id
                resolved_category_path = category_path(s, cl.categoria_id)
            for item in results:
                if item["movement_id"] == snap["id"]:
                    item.update(
                        {
                            "method": "decider_auto"
                            if auto_approved
                            else (
                                "decider_review"
                                if decision.get("needs_review")
                                else "decider"
                            ),
                            "categoria": resolved_category_path,
                            "categoria_id": category_id,
                            "subtipo": None,
                            "confianza": decision.get("confianza"),
                            "needs_review": (
                                False if auto_approved else bool(decision.get("needs_review"))
                            ),
                            "auto_approved": auto_approved,
                            "explicacion": decision.get("explicacion"),
                            "reference_count": len(precedents),
                            "classification_id": classification_id,
                        }
                    )
                    break
            stats["decider"] += 1
            if auto_approved:
                stats["auto_approved"] = stats.get("auto_approved", 0) + 1

    if stats.get("auto_approved"):
        with _session() as s:
            remaining = (
                s.query(FinancialMovement)
                .filter(FinancialMovement.estado == "pendiente")
                .count()
            )

    return {
        "items": results,
        "processed": len(results),
        "remaining": remaining,
        "reference_count": len(accepted_examples),
        "reference_cap": model_settings.jev_reference_max,
        "stats": stats,
    }


def _get_precedents(merchant: str | None) -> list[dict]:
    """Busca precedentes similares en memoria para usar como few-shot."""
    precedents: list[dict] = []
    if not merchant:
        return precedents
    with _session() as s:
        from ..models import ClassificationMemory
        key = _normalize_pattern(merchant)
        entries = (
            s.query(ClassificationMemory)
            .filter(
                ClassificationMemory.activo == True,  # noqa: E712
                ClassificationMemory.pattern_key.ilike(f"%{key[:20]}%"),
            )
            .order_by(ClassificationMemory.confianza.desc())
            .limit(3)
            .all()
        )
        for e in entries:
            precedents.append({
                "merchant": e.merchant or key,
                "categoria": category_path(s, e.categoria_id),
                "subtipo": e.subtipo,
                "confianza": float(e.confianza) if e.confianza else 0,
            })
    return precedents


@keep_transfers_in_review
def classify_pending(limit: int = 1000) -> dict:
    """Clasifica movimientos pendientes con reglas, memoria y LLM en lote.

    Returns:
        Dict con contadores {rule, memory, llm, failed, total} y, si aplica,
        ``failed_ids``/``error``.
    """
    stats: dict = {
        "rule": 0, "memory": 0, "llm": 0, "decider": 0,
        "decider_review": 0, "failed": 0, "total": 0,
        "broker": 0, "skipped": 0, "auto_approved": 0, "failed_ids": [],
    }

    need_llm: list[dict] = []
    auto_threshold = Decimal(str(load_model_settings().auto_approve_threshold))
    with _session() as s:
        pendientes = (
            s.query(FinancialMovement, NormalizedEvent)
            .outerjoin(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .filter(FinancialMovement.estado == "pendiente")
            .order_by(FinancialMovement.value_date, FinancialMovement.id)
            .limit(limit)
            .all()
        )
        if not pendientes:
            return stats

        engine = RuleEngine.from_session(s)
        memory_index = load_memory_index(s)
        category_ids_by_name = {
            nombre: cat_id for cat_id, nombre in engine.category_names.items()
        }
        mov_ids = [mov.id for mov, _ in pendientes]
        vigentes: dict[int, list[Classification]] = {}
        if mov_ids:
            for cl in (
                s.query(Classification)
                .filter(
                    Classification.movement_id.in_(mov_ids),
                    Classification.vigente == True,  # noqa: E712
                )
                .all()
            ):
                vigentes.setdefault(cl.movement_id, []).append(cl)

        for mov, event in pendientes:
            snap = _snapshot(mov, event)
            stats["total"] += 1

            # Ya clasificado (p. ej. transferencia interna o hecho broker):
            # no gastar LLM ni reabrir la decisión determinista.
            existing = vigentes.get(mov.id, [])
            if existing:
                if any(cl.categoria_id is not None for cl in existing):
                    if any(
                        (cl.confianza or Decimal("0")) >= auto_threshold
                        for cl in existing
                        if cl.categoria_id is not None
                    ):
                        mov.estado = "aprobado"
                        stats["auto_approved"] += 1
                    else:
                        stats["skipped"] += 1
                    continue
                broker_cl = next(
                    (cl for cl in existing if cl.origen == "broker"), None
                )
                default_cat = _BROKER_TYPE_CATEGORY.get(
                    base_broker_type(snap.get("broker_type"))
                ) or _BROKER_DEFAULT_CATEGORY.get(mov.kind)
                default_id = (
                    category_ids_by_name.get(default_cat)
                    or category_ids_by_name.get(default_cat.split("›")[0].strip())
                    if default_cat
                    else None
                )
                if broker_cl is not None and default_id is not None:
                    resolved_default = resolve_assignable_category(s, default_id)
                    broker_cl.categoria_id = (
                        resolved_default.id if resolved_default is not None else default_id
                    )
                    if (broker_cl.confianza or Decimal("0")) >= auto_threshold:
                        mov.estado = "aprobado"
                        stats["auto_approved"] += 1
                    stats["broker"] += 1
                    continue

            hit = engine.evaluate(
                merchant=snap["merchant"], kind=snap["kind"],
                description_clean=snap["descripcion"], mcc_code=snap["mcc_code"],
                broker_type=snap["broker_type"],
                counterparty_name=snap["counterparty_name"],
                counterparty_iban=snap["counterparty_iban"],
            )
            if hit is not None:
                _apply_actions(mov, hit.actions)
                if hit.categoria_id:
                    cl = _make_classification(
                        mov.id, hit.categoria_id, hit.subtipo, "rule",
                        Decimal("0.99"), hit.explicacion, session=s,
                    )
                    _replace_vigente(s, mov.id, cl, vigentes)
                    if Decimal("0.99") >= auto_threshold:
                        mov.estado = "aprobado"
                        stats["auto_approved"] += 1
                    stats["rule"] += 1
                    continue

            pattern = _normalize_pattern(snap["merchant"] or "")
            mem = memory_index.get(pattern)
            if mem and mem.get("confianza", Decimal("0")) >= CONFIANZA_MIN_AUTO:
                cl = _make_classification(
                    mov.id, mem["categoria_id"], mem.get("subtipo"), "memory",
                    mem["confianza"],
                    f"Precedente: {mem.get('categoria_nombre', '?')} "
                    f"(confianza {mem['confianza']})",
                    session=s,
                )
                _replace_vigente(s, mov.id, cl, vigentes)
                if (mem.get("confianza") or Decimal("0")) >= auto_threshold:
                    mov.estado = "aprobado"
                    stats["auto_approved"] += 1
                stats["memory"] += 1
                continue

            need_llm.append(snap)

    if need_llm and decider_is_configured():
        need_llm = _classify_with_decider(need_llm, stats)

    if need_llm:
        _classify_with_llm(need_llm, stats)

    return stats


def _classify_with_decider(need_llm: list[dict], stats: dict) -> list[dict]:
    """Intenta Jev para los movimientos que quedaron sin regla/memoria.

    Devuelve los que deben pasar al LLM. Las decisiones con categoría se
    persisten (aunque necesiten revisión) para no repetir la llamada; las que
    fallan se dejan al fallback LLM.
    """
    categorias = get_categorias_nombres()
    if not categorias:
        return need_llm

    remaining: list[dict] = []
    model_settings = load_model_settings()
    call_limit = model_settings.jev_max_calls_per_run
    calls = 0
    from .references import load_accepted_references, select_references

    with _session() as s:
        examples = load_accepted_references(s)

    for item in need_llm:
        if calls >= call_limit:
            remaining.append(item)
            continue
        calls += 1
        try:
            precedents = select_references(
                examples,
                current=item,
                limit=model_settings.jev_reference_max,
            )
            decision = decide_movement(item, categorias, precedents=precedents)
        except Exception as exc:  # pragma: no cover - depende de red/API
            logger.warning("Jev falló en lote: %s", exc)
            remaining.append(item)
            remaining.extend(need_llm[calls:])
            break

        category_name = decision.get("categoria")
        if not category_name:
            remaining.append(item)
            continue

        confidence = float(decision.get("confianza", 0) or 0)
        auto_approved = confidence >= model_settings.auto_approve_threshold
        with _session() as s:
            cat = resolve_category_reference(s, category_name)
            if cat is None:
                remaining.append(item)
                continue
            cl = _make_classification(
                item["id"],
                cat.id,
                None,
                "decider",
                Decimal(str(round(confidence, 3))),
                (decision.get("explicacion") or "Decisión Jev")[:500],
                session=s,
            )
            cl.modelo = (decision.get("model") or "jev-latest")[:60]
            cl.prompt_version = JEV_PROMPT_VERSION
            if auto_approved:
                cl.explicacion = (
                    f"{cl.explicacion or 'Decisión Jev'} · autoaprobado "
                    f"(confianza {confidence:.2f} ≥ {model_settings.auto_approve_threshold:.2f})"
                )[:500]
                movement = s.query(FinancialMovement).filter_by(id=item["id"]).first()
                if movement is not None:
                    movement.estado = "aprobado"
            _replace_vigente(s, item["id"], cl)

        if auto_approved:
            stats["decider"] += 1
            stats["auto_approved"] = stats.get("auto_approved", 0) + 1
        elif decision.get("needs_review"):
            stats["decider_review"] += 1
        else:
            stats["decider"] += 1

    return remaining


def _classify_with_llm(need_llm: list[dict], stats: dict) -> None:
    categorias = get_categorias_nombres()
    subtipos = get_subtipo_descriptions()
    batch_size = 25

    for start in range(0, len(need_llm), batch_size):
        chunk = need_llm[start:start + batch_size]
        try:
            results = llm_classify_batch(chunk, categorias, subtipos)
        except LLMError as exc:
            stats["failed"] += len(chunk)
            stats["failed_ids"].extend(item["id"] for item in chunk)
            stats["error"] = str(exc)
            # Un error de configuración afecta a todos los lotes: no seguir
            # intentando llamadas condenadas a fallar.
            from .llm_batch import LLMConfigurationError
            if isinstance(exc, LLMConfigurationError):
                pending = need_llm[start + batch_size:]
                stats["failed"] += len(pending)
                stats["failed_ids"].extend(item["id"] for item in pending)
                return
            continue

        returned_ids = {r.get("id") for r in results if r.get("id") is not None}
        valid_results = [
            r for r in results
            if r.get("categoria") and float(r.get("confianza", 0)) >= 0.5
        ]

        with _session() as s:
            cat_names = {
                path: cat_id for cat_id, path in category_paths(s).items()
            }
            ids = [r["id"] for r in valid_results if r.get("id") is not None]
            vigentes: dict[int, list[Classification]] = {}
            successful_ids: set[int] = set()
            if ids:
                for cl in (
                    s.query(Classification)
                    .filter(
                        Classification.movement_id.in_(ids),
                        Classification.vigente == True,  # noqa: E712
                    )
                    .all()
                ):
                    vigentes.setdefault(cl.movement_id, []).append(cl)

            for r in valid_results:
                mov_id = r.get("id")
                cat_id = cat_names.get(r.get("categoria"))
                if mov_id is None or cat_id is None:
                    continue
                cl = _make_classification(
                    mov_id, cat_id, r.get("subtipo"), "llm",
                    Decimal(str(r.get("confianza", 0.5))),
                    (r.get("explicacion") or "")[:500],
                    session=s,
                )
                _replace_vigente(s, mov_id, cl, vigentes)
                stats["llm"] += 1
                successful_ids.add(mov_id)

        failed_ids = [item["id"] for item in chunk if item["id"] not in successful_ids]
        stats["failed"] += len(failed_ids)
        stats["failed_ids"].extend(failed_ids)
        if returned_ids and not successful_ids:
            stats.setdefault("error", "El LLM no devolvió ninguna clasificación válida")


def _snapshot(mov: FinancialMovement, event: NormalizedEvent | None) -> dict:
    return {
        "id": mov.id,
        "merchant": mov.merchant,
        "kind": mov.kind,
        "amount": str(mov.amount) if mov.amount is not None else "0",
        "descripcion": event.description_clean if event else "",
        "mcc_code": event.mcc_code if event else None,
        "broker_type": event.broker_type if event else None,
        "counterparty_name": event.counterparty_name if event else None,
        "counterparty_iban": event.counterparty_iban if event else None,
    }


def _apply_actions(mov: FinancialMovement, actions: dict) -> None:
    if not actions:
        return
    if actions.get("set_kind"):
        mov.kind = actions["set_kind"]
    if actions.get("set_merchant"):
        mov.merchant = actions["set_merchant"]
    if actions.get("auto_aprobar"):
        mov.estado = "aprobado"


def _make_classification(
    movement_id: int,
    categoria_id: int | None,
    subtipo: str | None,
    origen: str,
    confianza: Decimal,
    explicacion: str,
    *,
    session=None,
) -> Classification:
    if categoria_id is not None and session is not None:
        try:
            resolved = resolve_assignable_category(session, categoria_id)
            if resolved is not None:
                categoria_id = resolved.id
        except DefaultSubcategoryMissing:
            # Una agrupadora antigua sin ``Otros``: se repara al vuelo y se
            # asigna el movimiento a la nueva hoja por defecto.
            category = session.query(Categoria).filter_by(id=categoria_id).first()
            if category is not None:
                child = ensure_default_child(session, category)
                categoria_id = child.id
    return Classification(
        movement_id=movement_id,
        categoria_id=categoria_id,
        subtipo=subtipo,
        origen=origen,
        confianza=confianza,
        explicacion=explicacion,
        vigente=True,
    )


def _replace_vigente(
    session,
    movement_id: int,
    cl: Classification,
    vigentes: dict[int, list[Classification]] | None = None,
) -> None:
    """Desactiva la clasificación vigente anterior y añade la nueva."""
    old = None
    if vigentes is not None:
        old = vigentes.get(movement_id)
    if old is None:
        old = (
            session.query(Classification)
            .filter(
                Classification.movement_id == movement_id,
                Classification.vigente == True,  # noqa: E712
            )
            .all()
        )
    for previous in old:
        previous.vigente = False
    session.add(cl)
    if vigentes is not None:
        vigentes[movement_id] = [cl]
