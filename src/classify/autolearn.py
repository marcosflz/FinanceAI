"""
Autoconfiguración de reglas a partir del histórico aprobado.

Mina los movimientos que el usuario ya aprobó (dando prioridad a sus
clasificaciones manuales, origen='user') y propone reglas deterministas
—marca de merchant, merchant completo y MCC— para clasificar y, opcionalmente,
auto-aprobar movimientos futuros con el mismo patrón.

Validaciones para evitar reglas peligrosas (topónimos, fragmentos de nombre):
- La categoría propuesta debe dominar en los movimientos aprobados.
- Si el patrón es un token genérico, debe dominar también entre los
  comercios distintos del corpus (aprobados + pendientes clasificados).
- Los patrones con una sola muestra aprobada se validan contra el corpus.

Solo lee: `analyze()` no modifica nada. `apply_proposals()` crea reglas.
"""

import re
from collections import Counter, defaultdict

from ..db.session import _session
from ..models import (
    Categoria,
    Classification,
    ClassificationRule,
    FinancialMovement,
    NormalizedEvent,
)

# Tokens que no identifican a un comercio (pasarelas, formas jurídicas, ruido).
STOPWORDS = {
    "PAYPAL", "BIZUM", "SUMUP", "STRIPE", "ADYEN", "SQUARE",
    "SA", "SL", "SLU", "SRL", "SOCIEDAD", "LIMITADA", "ANONIMA",
    "ESPANA", "SPAIN", "INTERNATIONAL", "EUROPE",
    "THE", "AND", "COM", "HTTP", "WWW", "NULL", "NONE",
    "CARD", "CASH", "SEPA", "IBAN", "TRANSFER", "TRANSFERENCIA",
    "PAGO", "COMPRA", "RECIBO", "DOMICILIACION",
    # Palabras genéricas de tipo de negocio (no identifican marca).
    "MARKET", "STORE", "SHOP", "MART", "SUPERMARKET", "SUPERMERCADO",
    "BOUTIQUE", "TALLER", "GRUPO", "SERVICIOS", "GESTION", "SOLUCIONES",
    "CENTRO", "LOCAL", "TIENDA",
}

MIN_TOKEN_LEN = 3
MIN_CONSISTENCY = 0.80
MIN_SAMPLES_MCC = 3

USER_WEIGHT = 5
APPROVED_WEIGHT = 2
PENDING_WEIGHT = 1


def _normalize(text: str | None) -> str:
    if not text:
        return ""
    s = text.upper()
    s = re.sub(r"\bPAYPAL\s*\*", " ", s)
    s = re.sub(r"[^A-ZÁÉÍÓÚÜÑ0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(merchant: str | None) -> list[str]:
    out = []
    for t in _normalize(merchant).split():
        if len(t) < MIN_TOKEN_LEN or t.isdigit() or t in STOPWORDS:
            continue
        out.append(t)
    return out


def _get_field(sample: dict, campo: str) -> str | None:
    if campo == "merchant":
        return sample.get("merchant")
    if campo == "kind":
        return sample.get("kind")
    if campo == "description_clean":
        return sample.get("description_clean")
    if campo == "mcc_code":
        return sample.get("mcc_code")
    if campo == "broker_type":
        return sample.get("broker_type")
    if campo == "counterparty_name":
        return sample.get("counterparty_name")
    if campo == "counterparty_iban":
        return sample.get("counterparty_iban")
    return None


def _match(operador: str, field: str, valor: str) -> bool:
    if operador == "equals":
        return field.upper() == valor.upper()
    if operador == "contains":
        return valor.upper() in field.upper()
    if operador == "regex":
        try:
            return bool(re.search(valor, field, re.IGNORECASE))
        except re.error:
            return False
    if operador == "mcc_in":
        return field in [v.strip() for v in valor.split(",")]
    return False


def _weight(sample: dict) -> int:
    if sample["origen"] == "user":
        return USER_WEIGHT
    if sample["estado"] == "aprobado":
        return APPROVED_WEIGHT
    return PENDING_WEIGHT


def _pick_category(samples: list[dict]) -> dict | None:
    """Categoría dominante (ponderada) y subtipo preferido dentro de ella."""
    cat_weights: dict[int, int] = defaultdict(int)
    for smp in samples:
        cat_weights[smp["categoria_id"]] += _weight(smp)
    total = sum(cat_weights.values()) or 1
    cat_id = max(cat_weights, key=lambda k: (cat_weights[k], -k))
    consistency = cat_weights[cat_id] / total
    if consistency < MIN_CONSISTENCY:
        return None

    in_cat = [s for s in samples if s["categoria_id"] == cat_id]
    user_sub = [s for s in in_cat if s["origen"] == "user" and s["subtipo"]]
    if user_sub:
        sub_weights: Counter = Counter()
        for s in user_sub:
            sub_weights[s["subtipo"]] += _weight(s)
        subtipo = sub_weights.most_common(1)[0][0]
        sub_cons = sub_weights[subtipo] / sum(sub_weights.values())
    elif in_cat:
        sub_weights = Counter()
        for s in in_cat:
            sub_weights[s["subtipo"]] += _weight(s)
        subtipo = sub_weights.most_common(1)[0][0]
        sub_cons = sub_weights[subtipo] / sum(sub_weights.values())
    else:
        subtipo, sub_cons = None, 0.0

    cat_name = max(in_cat, key=lambda s: _weight(s))["categoria_nombre"]
    return {
        "categoria_id": cat_id,
        "categoria_nombre": cat_name,
        "subtipo": subtipo,
        "consistencia": round(consistency, 3),
        "consistencia_subtipo": round(sub_cons, 3),
        "fuente": "user" if any(s["origen"] == "user" for s in in_cat) else "historico",
    }


def _distinct_merchants(samples: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Agrupa por (merchant normalizado, dirección): una regla de merchant
    también aplica a transferencias entrantes/salientes, así que validamos
    que la categoría domine en ambos sentidos por separado."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for smp in samples:
        key = _normalize(smp["merchant"])
        if key:
            groups[(key, smp.get("direction") or "")].append(smp)
    return groups


def _validate_generalization(samples: list[dict], cat_id: int) -> tuple[bool, float]:
    """Exige que la categoría domine también entre los comercios distintos."""
    merchants = _distinct_merchants(samples)
    if not merchants:
        return False, 0.0
    ok = 0
    for smps in merchants.values():
        cat = _pick_category(smps)
        if cat and cat["categoria_id"] == cat_id:
            ok += 1
    ratio = ok / len(merchants)
    return ratio >= MIN_CONSISTENCY, round(ratio, 3)


def analyze() -> dict:
    """Analiza el histórico aprobado y propone reglas (solo lectura)."""
    with _session() as s:
        labeled = (
            s.query(FinancialMovement, NormalizedEvent, Classification, Categoria)
            .join(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .join(Classification, (Classification.movement_id == FinancialMovement.id)
                  & (Classification.vigente == True))  # noqa: E712
            .join(Categoria, Categoria.id == Classification.categoria_id)
            .filter(
                FinancialMovement.estado.in_(["aprobado", "pendiente"]),
                FinancialMovement.kind.in_(["gasto", "ingreso"]),
            )
            .all()
        )

        corpus: list[dict] = []
        for m, e, c, cat in labeled:
            corpus.append({
                "mov_id": m.id,
                "merchant": m.merchant,
                "kind": m.kind,
                "direction": m.direction,
                "estado": m.estado,
                "value_date": m.value_date.isoformat() if m.value_date else None,
                "mcc_code": e.mcc_code,
                "description_clean": e.description_clean,
                "broker_type": e.broker_type,
                "counterparty_name": e.counterparty_name,
                "counterparty_iban": e.counterparty_iban,
                "categoria_id": cat.id,
                "categoria_nombre": cat.nombre,
                "subtipo": c.subtipo,
                "origen": c.origen,
            })

        pending = (
            s.query(FinancialMovement, NormalizedEvent, Classification)
            .join(NormalizedEvent, NormalizedEvent.id == FinancialMovement.event_id)
            .outerjoin(Classification, (Classification.movement_id == FinancialMovement.id)
                       & (Classification.vigente == True))  # noqa: E712
            .filter(FinancialMovement.estado == "pendiente")
            .all()
        )
        pending_rows = [{
            "merchant": m.merchant,
            "mcc_code": e.mcc_code,
            "categoria_id": c.categoria_id if c else None,
            "subtipo": c.subtipo if c else None,
        } for m, e, c in pending]

        rules = (
            s.query(ClassificationRule)
            .filter(ClassificationRule.activa == True)  # noqa: E712
            .order_by(ClassificationRule.prioridad)
            .all()
        )
        existing = [{
            "id": r.id,
            "prioridad": r.prioridad or 100,
            "campo": r.campo,
            "operador": r.operador,
            "valor": r.valor,
            "set_categoria_id": r.set_categoria_id,
            "set_subtipo": r.set_subtipo,
        } for r in rules]

    approved = [x for x in corpus if x["estado"] == "aprobado"]
    base_priority = 110
    if existing:
        base_priority = max(base_priority, max(r["prioridad"] for r in existing) + 10)

    def group_by(samples: list[dict], key_fn) -> dict:
        groups: dict = defaultdict(list)
        for smp in samples:
            for key in set(key_fn(smp)):
                groups[key].append(smp)
        return groups

    approved_by_token = group_by(approved, lambda s: _tokens(s["merchant"]))
    corpus_by_token = group_by(corpus, lambda s: _tokens(s["merchant"]))
    approved_by_mcc = group_by(approved, lambda s: [s["mcc_code"]] if s["mcc_code"] else [])
    corpus_by_mcc = group_by(corpus, lambda s: [s["mcc_code"]] if s["mcc_code"] else [])
    approved_by_broker = group_by(approved, lambda s: [s["broker_type"]] if s["broker_type"] else [])
    corpus_by_broker = group_by(corpus, lambda s: [s["broker_type"]] if s["broker_type"] else [])
    approved_by_merchant = group_by(
        approved, lambda s: [_normalize(s["merchant"])] if _normalize(s["merchant"]) else [],
    )

    proposals: list[dict] = []

    def make_proposal(campo: str, operador: str, valor: str,
                      ap_samples: list[dict], corpus_samples: list[dict],
                      min_samples: int) -> dict | None:
        if len(ap_samples) < min_samples:
            return None
        cat = _pick_category(ap_samples)
        if not cat:
            return None
        ok, merchant_cons = _validate_generalization(corpus_samples, cat["categoria_id"])
        if not ok:
            return None
        auto = cat["fuente"] == "user"
        if not auto and campo == "merchant":
            auto = cat["consistencia"] >= 0.9 and len(ap_samples) >= 3
        if not auto and campo == "mcc_code":
            auto = cat["fuente"] == "user" and len(ap_samples) >= 3
        return {
            "campo": campo,
            "operador": operador,
            "valor": valor,
            "set_categoria_id": cat["categoria_id"],
            "set_subtipo": cat["subtipo"],
            "auto_aprobar": auto,
            "muestras": len(ap_samples),
            "consistencia": cat["consistencia"],
            "consistencia_subtipo": cat["consistencia_subtipo"],
            "consistencia_comercios": merchant_cons,
            "fuente": cat["fuente"],
            "categoria_nombre": cat["categoria_nombre"],
            "ejemplos": sorted({s["merchant"] or "" for s in ap_samples})[:3],
        }

    token_proposals: dict[str, dict] = {}
    for token, ap_samples in approved_by_token.items():
        corpus_samples = corpus_by_token.get(token, ap_samples)
        n_merchants = len(_distinct_merchants(corpus_samples))
        if len(ap_samples) < 2 and n_merchants < 2:
            continue
        p = make_proposal(
            "merchant", "contains", token, ap_samples, corpus_samples, min_samples=1,
        )
        if p:
            token_proposals[token] = p
            proposals.append(p)

    for merchant, ap_samples in approved_by_merchant.items():
        user_samples = [s for s in ap_samples if s["origen"] == "user"]
        if not user_samples:
            continue
        corpus_samples = [s for s in corpus if _normalize(s["merchant"]) == merchant]
        p = make_proposal(
            "merchant", "contains", merchant, user_samples, corpus_samples, min_samples=1,
        )
        if not p:
            continue
        # Si ya hay una regla de token que cubre el mismo merchant, es redundante.
        redundant = any(
            tp["set_categoria_id"] == p["set_categoria_id"]
            and tp["set_subtipo"] == p["set_subtipo"]
            and tp["valor"] in merchant
            for tp in token_proposals.values()
        )
        if not redundant:
            proposals.append(p)

    for mcc, ap_samples in approved_by_mcc.items():
        corpus_samples = corpus_by_mcc.get(mcc, ap_samples)
        p = make_proposal(
            "mcc_code", "mcc_in", mcc, ap_samples, corpus_samples, MIN_SAMPLES_MCC,
        )
        if p:
            proposals.append(p)

    for broker, ap_samples in approved_by_broker.items():
        corpus_samples = corpus_by_broker.get(broker, ap_samples)
        min_samples = 1 if any(x["origen"] == "user" for x in ap_samples) else 2
        p = make_proposal(
            "broker_type", "contains", broker, ap_samples, corpus_samples, min_samples,
        )
        if p:
            p["auto_aprobar"] = False
            proposals.append(p)

    # Dedup exacto y sombras de reglas existentes
    seen: set[tuple] = set()
    final: list[dict] = []
    for p in proposals:
        dedup_key = (p["campo"], p["operador"], p["valor"].upper())
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        if p["campo"] == "merchant":
            samples = approved_by_token.get(p["valor"]) or approved_by_merchant.get(p["valor"]) or []
        elif p["campo"] == "broker_type":
            samples = approved_by_broker.get(p["valor"], [])
        else:
            samples = approved_by_mcc.get(p["valor"], [])
        shadow = None
        intercepted = 0
        for smp in samples:
            for r in existing:
                if r["prioridad"] >= base_priority:
                    break
                fv = _get_field(smp, r["campo"])
                if fv and _match(r["operador"], fv, r["valor"]):
                    intercepted += 1
                    if shadow is None:
                        shadow = r["id"]
                    break
        p["sombreada_por"] = shadow if intercepted >= max(1, len(samples) // 2) else None
        if p["campo"] == "merchant":
            p["prioridad"] = base_priority
        elif p["campo"] == "mcc_code":
            p["prioridad"] = base_priority + 10
        else:
            p["prioridad"] = base_priority + 20

        matches = ya = 0
        for mov in pending_rows:
            if p["campo"] == "merchant":
                hit = p["valor"].upper() in (mov["merchant"] or "").upper()
            else:
                hit = mov["mcc_code"] == p["valor"]
            if not hit:
                continue
            matches += 1
            if (mov["categoria_id"] == p["set_categoria_id"]
                    and (mov["subtipo"] or None) == (p["set_subtipo"] or None)):
                ya += 1
        p["pendientes_match"] = matches
        p["pendientes_ya_clasificados"] = ya
        p["sin_efecto"] = matches > 0 and ya == matches
        p["seleccionada"] = p["sombreada_por"] is None and not p["sin_efecto"]
        final.append(p)

    final.sort(key=lambda x: (-x["pendientes_match"], -x["muestras"], x["valor"]))

    return {
        "proposals": final,
        "base_prioridad": base_priority,
        "resumen": {
            "aprobados_analizados": len(approved),
            "con_decision_usuario": sum(1 for x in approved if x["origen"] == "user"),
            "pendientes": len(pending_rows),
            "reglas_existentes": len(existing),
        },
    }


def apply_proposals(proposals: list[dict]) -> dict:
    """Crea las reglas propuestas. Omite duplicados exactos de reglas activas."""
    created: list[dict] = []
    skipped = 0
    base_priority = 110

    with _session() as s:
        existing = (
            s.query(ClassificationRule)
            .filter(ClassificationRule.activa == True)  # noqa: E712
            .all()
        )
        if existing:
            base_priority = max(base_priority, max((r.prioridad or 100) for r in existing) + 10)

        for p in proposals:
            campo = p.get("campo")
            operador = p.get("operador")
            valor = p.get("valor")
            cat_id = p.get("set_categoria_id")
            if campo not in {
                "merchant", "kind", "description_clean", "mcc_code",
                "broker_type", "counterparty_name", "counterparty_iban",
            }:
                skipped += 1
                continue
            if operador not in {"equals", "contains", "regex", "mcc_in"}:
                skipped += 1
                continue
            if not valor or not cat_id:
                skipped += 1
                continue
            cat = s.query(Categoria).filter_by(id=cat_id).first()
            if not cat:
                skipped += 1
                continue
            dup = any(
                r.campo == campo and r.operador == operador
                and (r.valor or "").upper() == valor.upper()
                for r in existing
            )
            if dup:
                skipped += 1
                continue

            rule = ClassificationRule(
                prioridad=max(base_priority, int(p.get("prioridad") or base_priority)),
                campo=campo,
                operador=operador,
                valor=valor,
                set_categoria_id=cat_id,
                set_subtipo=p.get("set_subtipo") or None,
                auto_aprobar=bool(p.get("auto_aprobar")),
                activa=True,
            )
            s.add(rule)
            s.flush()
            existing.append(rule)
            created.append({
                "id": rule.id,
                "campo": campo,
                "operador": operador,
                "valor": valor,
                "categoria": cat.nombre,
                "subtipo": rule.set_subtipo,
                "auto_aprobar": rule.auto_aprobar,
            })

        s.commit()

    return {
        "created": len(created),
        "skipped": skipped,
        "prioridad": base_priority,
        "reglas": created,
    }
