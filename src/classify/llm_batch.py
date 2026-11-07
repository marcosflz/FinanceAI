"""
Clasificación batch vía LLM para gastos/ingresos CASH sin regla ni memoria.

Recibe N movimientos (~25/lote) y llama al LLM una sola vez con todos ellos
más el catálogo de categorías/subtipos. ``classify_one`` hace una llamada
individual con precedentes (few-shot).

Errores tipados (no se silencian):
- ``LLMConfigurationError``: falta API key / configuración inválida.
- ``LLMAPIError``: error de transporte/API tras reintentos.
- ``LLMResponseError``: respuesta no parseable o sin formato esperado.
"""

from __future__ import annotations

import json
import logging
import re
import time

from openai import OpenAI

from ..llm_config import resolve_llm_settings
from .redact import redact_text

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 0.5


class LLMError(RuntimeError):
    """Base de errores del clasificador LLM."""


class LLMConfigurationError(LLMError):
    """Configuración incompleta (API key, modelo, base URL…)."""


class LLMAPIError(LLMError):
    """Error de la API del proveedor tras agotar reintentos."""


class LLMResponseError(LLMError):
    """La respuesta no es JSON válido o no tiene el formato esperado."""


def _load_literals() -> list[str]:
    try:
        from .redact import get_redact_literals
        return get_redact_literals()
    except Exception as exc:  # la BD puede no estar disponible en tests aislados
        logger.warning("No se pudieron cargar los literales de redacción: %s", exc)
        return []


def _build_client(settings: dict) -> tuple[OpenAI, str]:
    api_key = (settings.get("api_key") or "").strip()
    model = (settings.get("model") or "").strip()
    if not api_key:
        raise LLMConfigurationError(
            "LLM_API_KEY no configurada: no se puede clasificar con LLM"
        )
    if not model:
        raise LLMConfigurationError("LLM_MODEL no configurado")
    try:
        client = OpenAI(
            api_key=api_key,
            base_url=settings.get("base_url") or None,
            timeout=60,
            max_retries=0,
        )
    except Exception as exc:
        raise LLMConfigurationError(f"Configuración de cliente LLM inválida: {exc}") from exc
    return client, model


def _chat_with_retries(
    client: OpenAI,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
    **kwargs,
):
    """Llama a Chat Completions con reintentos y errores tipados."""
    last_exc: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except Exception as exc:  # openai.APIError y errores de red
            last_exc = exc
            logger.warning(
                "Llamada LLM falló (intento %s/%s): %s: %s",
                attempt, attempts, type(exc).__name__, exc,
            )
            if attempt < attempts:
                time.sleep(RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1)))
    raise LLMAPIError(
        f"LLM API falló tras {attempts} intentos: "
        f"{type(last_exc).__name__}: {last_exc}"
    ) from last_exc


def _parse_json_content(raw: str, *, context: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Respuesta LLM no es JSON (%s): %s", context, raw[:500])
        raise LLMResponseError(
            f"Respuesta LLM no es JSON en {context}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise LLMResponseError(f"Respuesta LLM inesperada en {context}: {type(data).__name__}")
    return data


def classify_batch(
    movements: list[dict],
    categorias: list[str],
    subtipo_descriptions: dict | None = None,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
) -> list[dict]:
    """Clasifica N movimientos en una sola llamada LLM batch.

    Args:
        movements: Lista de dict con claves {id, merchant, descripcion,
                   amount, kind, mcc_code, broker_type}
        categorias: Lista de nombres de categorías activas.
        subtipo_descriptions: Dict {tipo: {subtipo: descripcion}}

    Returns:
        Lista de dict con claves {id, categoria, subtipo, merchant,
        descripcion, confianza, explicacion}. El orden coincide con el input.

    Raises:
        LLMConfigurationError, LLMAPIError, LLMResponseError.
    """
    if not movements:
        return []

    settings = resolve_llm_settings()
    client, model = _build_client(settings)
    literals = _load_literals()

    items = []
    for m in movements:
        merchant = redact_text(m.get("merchant") or "", literals)
        desc = redact_text(m.get("descripcion") or "", literals)
        amount = m.get("amount", 0)
        kind = m.get("kind", "gasto")
        mcc = m.get("mcc_code") or "—"
        broker = m.get("broker_type") or "—"
        items.append({
            "id": m["id"],
            "merchant": merchant,
            "descripcion_clean": desc,
            "importe": str(amount) if amount else "0",
            "direccion": kind,
            "mcc": mcc,
            "tipo_broker": broker,
        })

    cats_str = ", ".join(categorias)
    subtipo_rules = ""
    if subtipo_descriptions:
        subtipo_rules = "\nGuías de subtipo:\n"
        for key, desc in subtipo_descriptions.items():
            if desc:
                subtipo_rules += f"- {key}: {desc}\n"

    prompt = f"""Eres un clasificador financiero. Asigna categoría y subtipo a cada movimiento.

Categorías disponibles: {cats_str}{subtipo_rules}

Reglas:
- 'importe' > 0 = ingreso (dinero que entra), < 0 = gasto (dinero que sale)
- MCC puede ayudar a determinar la categoría
- Usa tu conocimiento sobre merchants para asignar la categoría más precisa
- 'confianza' = 0-1 según lo seguro que estés de la clasificación
- 'explicacion' ≤ 140 caracteres, en español

Responde ÚNICAMENTE con JSON con una clave 'results'.
{{"results": [
  {{
    "id": <int>,
    "categoria": "nombre categoría",
    "subtipo": "fijo|variable|inversion|null",
    "merchant": "nombre limpio del comercio (solo si mejoras el original)",
    "descripcion": "descripción corta del movimiento",
    "confianza": 0.95,
    "explicacion": "por qué esta clasificación"
  }}
]}}"""

    user_content = json.dumps(items, ensure_ascii=False, default=str)
    resp = _chat_with_retries(
        client,
        attempts=attempts,
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content if resp.choices else ""
    data = _parse_json_content(raw, context="classify_batch")

    results = None
    for key in ("results", "classifications", "movements", "data", "items"):
        if isinstance(data.get(key), list):
            results = data[key]
            break
    if results is None:
        logger.error("Respuesta LLM sin lista de resultados: %s", str(data)[:500])
        raise LLMResponseError("Respuesta LLM sin lista 'results'")
    return _validate(results, categorias)


def _validate(results: list, categorias: list[str]) -> list[dict]:
    """Valida y normaliza la respuesta del LLM."""
    valid = []
    cat_set = set(categorias)
    for r in results:
        if not isinstance(r, dict):
            logger.warning("Resultado LLM ignorado (no es objeto): %r", r)
            continue
        r["categoria"] = (
            r.get("categoria") if r.get("categoria") in cat_set else None
        )
        try:
            r["confianza"] = max(0.0, min(1.0, float(r.get("confianza", 0.5))))
        except (TypeError, ValueError):
            r["confianza"] = 0.0
        valid.append(r)
    return valid


def classify_one(
    movement_data: dict,
    categorias: list[str],
    subtipo_descriptions: dict | None = None,
    precedents: list[dict] | None = None,
    *,
    attempts: int = DEFAULT_ATTEMPTS,
) -> dict | None:
    """Clasifica UN movimiento con llamada LLM individual + contexto few-shot.

    Raises:
        LLMConfigurationError, LLMAPIError, LLMResponseError.
    """
    settings = resolve_llm_settings()
    client, model = _build_client(settings)
    literals = _load_literals()

    merchant = redact_text(movement_data.get("merchant") or "", literals)
    desc = redact_text(movement_data.get("descripcion") or "", literals)
    amount = movement_data.get("amount", "0")
    kind = movement_data.get("kind", "gasto")
    mcc = movement_data.get("mcc_code") or "—"
    broker = movement_data.get("broker_type") or "—"

    cats_str = ", ".join(categorias)
    subtipo_rules = ""
    if subtipo_descriptions:
        subtipo_rules = "\nGuías de subtipo:\n"
        for key, d in subtipo_descriptions.items():
            if d:
                subtipo_rules += f"- {key}: {d}\n"

    precedents_str = ""
    if precedents:
        precedents_str = "\nMovimientos similares ya clasificados:\n"
        for p in precedents:
            precedents_str += (
                f'- "{p.get("merchant", "?")}" → {p.get("categoria", "?")}'
                f' / {p.get("subtipo", "—")}'
                f' (confianza {p.get("confianza", 0.5)})\n'
            )

    prompt = f"""Eres un clasificador financiero. Asigna categoría y subtipo a 1 movimiento.

Categorías disponibles: {cats_str}{subtipo_rules}{precedents_str}

Reglas:
- 'importe' > 0 = ingreso (dinero que entra), < 0 = gasto (dinero que sale)
- MCC puede ayudar a determinar la categoría
- 'confianza' = 0-1 según lo seguro que estés
- 'explicacion' ≤ 140 caracteres, en español, de por qué esa categoría

Responde ÚNICAMENTE con JSON, sin texto adicional:
{{"categoria": "nombre categoría", "subtipo": "fijo|variable|inversion|null", "merchant": "nombre limpio", "descripcion": "descripción corta", "confianza": 0.95, "explicacion": "por qué"}}"""

    item = {
        "id": movement_data.get("id"),
        "merchant": merchant,
        "descripcion_clean": desc,
        "importe": str(amount) if amount else "0",
        "direccion": kind,
        "mcc": mcc,
        "tipo_broker": broker,
    }
    user_content = json.dumps(item, ensure_ascii=False, default=str)

    resp = _chat_with_retries(
        client,
        attempts=attempts,
        model=model,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content if resp.choices else ""
    data = _parse_json_content(raw, context="classify_one")

    if data.get("categoria") in set(categorias):
        return data
    if data.get("categoria"):
        # Categoría inventada: se devuelve con confianza baja para validación.
        data["confianza"] = 0.3
        return data
    logger.warning("Respuesta LLM sin categoría para movimiento %s", movement_data.get("id"))
    return None
