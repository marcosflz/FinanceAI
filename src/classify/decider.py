"""Puente entre el pipeline de clasificación y el decisor Jev.

Jev no ve PDFs ni imágenes: recibe un ``state`` estructurado y redactado y
responde preguntas atómicas. Este módulo construye esas preguntas, aplica los
umbrales del plan y devuelve una decisión normalizada que el pipeline puede
persistir como una ``Classification`` con ``origen='decider'``.

Sin ``TYPESAFE_API_KEY`` el módulo no se usa; el pipeline cae al LLM
OpenAI-compatible de siempre. Los tests inyectan un proveedor falso y nunca
hacen red.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

from ..ai.decision import DecisionOrchestrator
from ..ai.jev import JevProvider
from ..ai.schemas import DecisionQuestion
from ..config import get_settings
from ..model_settings import load_model_settings

logger = logging.getLogger(__name__)

JEV_PROMPT_VERSION = "jev-classify-2.0"
DEFAULT_MAX_CALLS = 50


class DeciderNotConfigured(RuntimeError):
    """No hay ``TYPESAFE_API_KEY``; el pipeline debe usar el fallback LLM."""


class DeciderProvider(Protocol):
    name: str

    def ask(self, state: Any, questions: Mapping[str, Any], *, timeout: float = 5.0) -> Any: ...


_CATEGORY_HINTS = {
    "Vivienda": "Alquiler, hipoteca, comunidad, agua, luz, gas, mantenimiento del hogar.",
    "Alimentación": "Supermercado, panadería, carnicería, restaurantes de comida habitual.",
    "Transporte": "Combustible, peajes, parking, metro, autobús, tren, taxi, movilidad.",
    "Servicios": "Gestoría, software, reparaciones, belleza, administración, servicios puntuales.",
    "Telecomunicaciones": "Móvil, fibra, internet, telefonía, televisión de pago.",
    "Salud": "Farmacia, médico, dentista, óptica, fisioterapia, seguro de salud.",
    "Ocio": "Restaurantes, bares, cine, streaming, videojuegos, viajes, deporte, cultura.",
    "Compras": "Ropa, electrónica, hogar, cosmética, librería, comercio minorista.",
    "Nómina": "Sueldo, salario, pagas extras y remuneración laboral.",
    "Inversiones": "Compra, venta o aportación de activos, fondos y cripto; "
    "los dividendos e intereses van a Ingresos.",
    "Transferencias": "Movimientos entre cuentas propias o transferencias neutras.",
    "Otros": "Gastos o ingresos que no encajan claramente en otra categoría.",
    "Alquiler": "Alquiler de vivienda.",
    "Facturas": "Facturas recurrentes de suministros o servicios.",
    "Suscripciones": "Cuotas recurrentes de servicios digitales.",
    "Coche": "Combustible, peajes, parking, mantenimiento del vehículo.",
    "Bizum": "Envíos o recepciones por Bizum.",
    "Ropa": "Prendas de vestir y calzado.",
    "Saldo/Efectivo": "Movimientos de efectivo o saldo.",
}


def _category_hint(name: str) -> str:
    if name in _CATEGORY_HINTS:
        return _CATEGORY_HINTS[name]
    leaf = name.split("›")[-1].strip()
    if leaf in _CATEGORY_HINTS:
        return _CATEGORY_HINTS[leaf]
    return f"Movimientos clasificados como {name}."


def build_questions(
    categories: Iterable[str], *, include_transfer: bool = False
) -> dict[str, DecisionQuestion]:
    """Construye preguntas atómicas y explicables para Jev."""
    names = [str(name) for name in categories if str(name).strip()]
    if not names:
        raise ValueError("No hay categorías para preguntar a Jev")
    questions = {
        "categoria": DecisionQuestion.choice(
            "Elige la categoría de negocio más específica para este movimiento. "
            "Usa 'Transferencias' solo si es un movimiento entre cuentas propias "
            "o una transferencia neutra; no la uses para un gasto con comercio.",
            {name: _category_hint(name) for name in names},
        ),
        "requiere_revision": DecisionQuestion.noul(
            "¿La información es contradictoria o insuficiente y conviene que "
            "una persona revise este movimiento?"
        ),
    }
    if include_transfer:
        questions["es_transferencia_interna"] = DecisionQuestion.noul(
            "¿El movimiento es una transferencia entre dos cuentas propias "
            "(misma persona/titular), incluida una recarga a Revolut/N26/Bunq?"
        )
    return questions


def _state_payload(
    snapshot: Mapping[str, Any],
    *,
    precedents: list[dict] | None = None,
    rule_hits: list[str] | None = None,
) -> dict:
    """State pequeño y redactado: nunca incluye PDFs ni imágenes."""
    return {
        "merchant": snapshot.get("merchant"),
        "description": (snapshot.get("descripcion") or snapshot.get("description") or "")[:500],
        "amount": snapshot.get("amount"),
        "currency": snapshot.get("currency", "EUR"),
        "kind": snapshot.get("kind"),
        "mcc": snapshot.get("mcc_code") or snapshot.get("mcc"),
        "broker_type": snapshot.get("broker_type"),
        "account": snapshot.get("account"),
        "counterparty": snapshot.get("counterparty_name") or snapshot.get("counterparty"),
        "rule_hits": list(rule_hits or []),
        "precedents": list(precedents or []),
    }


def is_configured() -> bool:
    """True si hay clave de TypeSafe configurada."""
    return get_settings().typesafe_api_key is not None


def decide_movement(
    snapshot: Mapping[str, Any],
    categories: Iterable[str],
    *,
    precedents: list[dict] | None = None,
    rule_hits: list[str] | None = None,
    provider: DeciderProvider | None = None,
    risk: str = "normal",
    timeout: float = 5.0,
) -> dict:
    """Pide una decisión a Jev y la normaliza para el pipeline.

    Returns:
        ``{categoria, confianza, needs_review, explicacion, provider, model,
        state_hash, answers}``. ``categoria`` puede ser ``None`` si Jev no
        eligió una categoría válida; en ese caso ``needs_review`` es True.
    """
    if provider is None:
        if not is_configured():
            raise DeciderNotConfigured("TYPESAFE_API_KEY no configurada")
        provider = JevProvider.from_env(model=load_model_settings().jev_model)

    broker_type = str(snapshot.get("broker_type") or "").upper()
    include_transfer = "TRANSFER" in broker_type or "DIRECT_DEBIT" in broker_type
    questions = build_questions(categories, include_transfer=include_transfer)
    orchestrator = DecisionOrchestrator(provider)
    result = orchestrator.decide(
        _state_payload(snapshot, precedents=precedents, rule_hits=rule_hits),
        questions,
        risk=risk,
        timeout=timeout,
    )

    category_answer = result.answers.get("categoria", {})
    choice = category_answer.get("choice")
    valid_categories = {str(name) for name in categories}
    category = choice if choice in valid_categories else None
    internal_answer = result.answers.get("es_transferencia_interna", {})
    internal_strength = internal_answer.get("decision_strength")
    if internal_strength is None:
        internal_strength = internal_answer.get("confidence")

    needs_review = bool(result.needs_review or category is None)
    return {
        "categoria": category,
        "confianza": float(result.confidence or 0.0),
        "needs_review": needs_review,
        "es_transferencia_interna": (
            bool(internal_strength is not None and internal_strength >= 0.95)
        ),
        "explicacion": result.explanation,
        "provider": result.provider,
        "model": result.model,
        "state_hash": result.state_hash,
        "answers": result.answers,
        "cached": result.cached,
    }


def max_calls_per_run() -> int:
    """Límite de llamadas a Jev por ejecución (editable en Ajustes)."""
    return load_model_settings().jev_max_calls_per_run


__all__ = [
    "DeciderNotConfigured",
    "JEV_PROMPT_VERSION",
    "build_questions",
    "decide_movement",
    "is_configured",
    "max_calls_per_run",
]
