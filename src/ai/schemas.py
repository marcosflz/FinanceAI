"""Esquemas Pydantic v2 compartidos por la capa de IA (fases F3/F4).

Contratos estables entre:

- OpenCode Go: ``LLMResult`` / ``Usage`` / ``Allowance``.
- Jev: ``DecisionQuestion`` / ``DecisionResult``.
- Agente documental: ``DocumentEnvelope`` y sus piezas.

Notas de diseño:

- El dinero se representa con ``Decimal`` para no perder precisión.
- Las confianzas son floats en ``[0, 1]`` (las probabilidades de Jev también).
- Los esquemas ignoran campos extra para tolerar cambios de proveedor; los
  campos que sí importan se validan explícitamente.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Schema(BaseModel):
    """Base común: tolerante a campos nuevos de los proveedores."""

    model_config = ConfigDict(extra="ignore")


def _as_decimal(value: Any) -> Decimal | None:
    """Convierte a Decimal sin romper por valores raros del proveedor."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _first_decimal(payload: Mapping[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        if key in payload:
            parsed = _as_decimal(payload.get(key))
            if parsed is not None:
                return parsed
    return None


def _first_float(payload: Mapping[str, Any], *keys: str) -> float | None:
    for key in keys:
        if key in payload:
            parsed = _as_float(payload.get(key))
            if parsed is not None:
                return parsed
    return None


# ---------------------------------------------------------------------------
# Uso, coste y allowance de OpenCode Go
# ---------------------------------------------------------------------------


class Usage(_Schema):
    """Uso normalizado de tokens/coste de una llamada a un LLM."""

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: Decimal | None = None
    list_cost_usd: Decimal | None = None
    billing_source: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, usage: Mapping[str, Any] | None) -> Usage:
        """Normaliza ``usage`` de Chat Completions/Responses de OpenCode Go.

        Soporta tanto el formato OpenAI (``prompt_tokens``/``completion_tokens``)
        como el de Responses (``input_tokens``/``output_tokens``) y el bloque
        extra ``usage.opencode`` que añade Go.
        """
        payload: Mapping[str, Any] = usage if isinstance(usage, Mapping) else {}
        opencode = payload.get("opencode")
        opencode = opencode if isinstance(opencode, Mapping) else {}
        tokens = opencode.get("tokens")
        tokens = tokens if isinstance(tokens, Mapping) else {}
        input_details = payload.get("input_tokens_details")
        input_details = input_details if isinstance(input_details, Mapping) else {}
        output_details = payload.get("output_tokens_details")
        output_details = output_details if isinstance(output_details, Mapping) else {}

        input_tokens = _as_int(
            payload.get("prompt_tokens", payload.get("input_tokens")), 0
        )
        output_tokens = _as_int(
            payload.get("completion_tokens", payload.get("output_tokens")), 0
        )
        if not input_tokens:
            input_tokens = _as_int(tokens.get("input"), 0)
        if not output_tokens:
            output_tokens = _as_int(tokens.get("output"), 0)
        total_tokens = _as_int(payload.get("total_tokens"), 0)
        if not total_tokens:
            total_tokens = input_tokens + output_tokens

        reasoning_tokens = _as_int(
            tokens.get("reasoning", output_details.get("reasoning_tokens")), 0
        )
        cache_read_tokens = _as_int(
            tokens.get("cache_read", input_details.get("cached_tokens")), 0
        )
        cache_write_tokens = _as_int(tokens.get("cache_write_5m"), 0) + _as_int(
            tokens.get("cache_write_1h"), 0
        )
        if not cache_write_tokens:
            cache_write_tokens = _as_int(
                payload.get("cache_creation_input_tokens"), 0
            )

        cost_usd = _as_decimal(payload.get("cost"))
        list_cost_usd = _as_decimal(opencode.get("list_cost"))
        billing_source = opencode.get("billing_source")
        if not isinstance(billing_source, str) or not billing_source:
            billing_source = None

        return cls(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            reasoning_tokens=reasoning_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_write_tokens=cache_write_tokens,
            cost_usd=cost_usd,
            list_cost_usd=list_cost_usd,
            billing_source=billing_source,
            raw=dict(payload),
        )


class Allowance(_Schema):
    """Consumo de la cuota de OpenCode Go asociado a una petición.

    ``usage.opencode.allowance`` documenta cuánto ha contado la petición contra
    el límite mensual (un importe en USD). Algunos proxies devuelven además el
    límite y lo restante; cuando existen, se usan para decidir el fallback.
    """

    spent_usd: Decimal | None = None
    limit_usd: Decimal | None = None
    remaining_usd: Decimal | None = None
    remaining_pct: float | None = None
    raw: Any = None

    @classmethod
    def from_payload(
        cls,
        value: Any,
        headers: Mapping[str, str] | None = None,
    ) -> Allowance:
        """Parsea un allowance numérico u objeto y, si hay, cabeceras de límite."""
        spent: Decimal | None = None
        limit: Decimal | None = None
        remaining: Decimal | None = None
        pct: float | None = None

        if isinstance(value, Mapping):
            spent = _first_decimal(value, "spent", "used", "amount", "cost", "usd")
            limit = _first_decimal(value, "limit", "monthly_limit", "total")
            remaining = _first_decimal(
                value, "remaining", "remaining_usd", "left", "remaining_allowance"
            )
            pct = _first_float(
                value,
                "remaining_pct",
                "percent_remaining",
                "remaining_ratio",
                "pct_remaining",
            )
        elif value is not None:
            # Forma documentada: un número con el importe contado por la petición.
            spent = _as_decimal(value)

        header_map = {
            str(key).lower(): header_value
            for key, header_value in (headers or {}).items()
        }
        if remaining is None:
            remaining = _as_decimal(
                header_map.get("x-opencode-allowance-remaining")
                or header_map.get("x-ratelimit-remaining")
            )
        if limit is None:
            limit = _as_decimal(header_map.get("x-opencode-allowance-limit"))
        if spent is None:
            spent = _as_decimal(header_map.get("x-opencode-allowance-used"))
        if pct is None:
            pct = _as_float(header_map.get("x-opencode-allowance-remaining-pct"))

        if pct is None and remaining is None and spent is not None and limit is not None:
            remaining = max(limit - spent, Decimal("0"))
        if pct is None and remaining is not None and limit is not None and limit > 0:
            pct = float(remaining / limit)
        if (
            pct is None
            and remaining is not None
            and limit is None
            and Decimal("0") <= remaining <= Decimal("1")
        ):
            # Algunos proxies devuelven solo la fracción restante.
            pct = float(remaining)
        if pct is not None:
            pct = _clamp01(pct)

        return cls(
            spent_usd=spent,
            limit_usd=limit,
            remaining_usd=remaining,
            remaining_pct=pct,
            raw=value,
        )

    @property
    def remaining_ratio(self) -> float | None:
        """Fracción restante de la cuota, si el proveedor la expone."""
        if self.remaining_pct is not None:
            return self.remaining_pct
        if (
            self.remaining_usd is not None
            and self.limit_usd is not None
            and self.limit_usd > 0
        ):
            return _clamp01(float(self.remaining_usd / self.limit_usd))
        return None

    def is_low(self, threshold: float = 0.20) -> bool:
        """``True`` si queda menos de ``threshold`` de cuota (por defecto 20 %)."""
        ratio = self.remaining_ratio
        return ratio is not None and ratio < threshold


class LLMResult(_Schema):
    """Resultado de una llamada a OpenCode Go."""

    text: str = ""
    parsed: Any = None
    usage: Usage = Field(default_factory=Usage)
    allowance: Allowance = Field(default_factory=Allowance)
    model: str = ""
    api: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)
    fallback_used: bool = False
    attempted_models: list[str] = Field(default_factory=list)

    @property
    def billing_source(self) -> str | None:
        return self.usage.billing_source


# ---------------------------------------------------------------------------
# Decisión tipada
# ---------------------------------------------------------------------------


class QuestionType(str, Enum):
    choice = "choice"
    score = "score"
    noul = "noul"


class DecisionQuestion(_Schema):
    """Pregunta atómica para el decisor (Jev u otro proveedor tipado)."""

    type: QuestionType
    instructions: str = ""
    criteria: dict[str, Any] | list[Any] | None = None

    @classmethod
    def choice(
        cls, instructions: str, criteria: Mapping[str, Any]
    ) -> DecisionQuestion:
        return cls(
            type=QuestionType.choice,
            instructions=instructions,
            criteria=dict(criteria),
        )

    @classmethod
    def score(cls, instructions: str, criteria: list[Any]) -> DecisionQuestion:
        return cls(
            type=QuestionType.score,
            instructions=instructions,
            criteria=list(criteria),
        )

    @classmethod
    def noul(cls, instructions: str) -> DecisionQuestion:
        return cls(type=QuestionType.noul, instructions=instructions)


class DecisionResult(_Schema):
    """Respuesta normalizada del orquestador de decisión.

    ``confidence`` es la mínima confianza efectiva de las preguntas que
    participan en la decisión (excluye las preguntas de tipo "¿requiere
    revisión?"). En ``noul`` la confianza es ``|2p-1|``; la probabilidad usada
    contra el umbral de la política queda en
    ``answers[q]["decision_strength"]``. ``needs_review`` es conservador: si
    cualquier respuesta no alcanza el umbral de auto-aceptación de su política,
    va a revisión.
    """

    provider: str
    model: str | None = None
    answers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    confidence: float = 0.0
    needs_review: bool = True
    explanation: str = ""
    state_hash: str | None = None
    cached: bool = False
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# DocumentEnvelope (contrato del agente documental)
# ---------------------------------------------------------------------------


class DocumentType(str, Enum):
    bank_statement = "bank_statement"
    receipt = "receipt"
    invoice = "invoice"
    position_statement = "position_statement"
    unknown = "unknown"


class AccountRef(_Schema):
    iban_masked: str | None = None
    name: str | None = None
    kind: str | None = None


class DocumentPeriod(_Schema):
    start: date | None = None
    end: date | None = None


class Balances(_Schema):
    opening: Decimal | None = None
    closing: Decimal | None = None
    currency: str = "EUR"


class DocumentUnit(_Schema):
    """Una fila/bloque extraído, siempre con evidencia asociada."""

    kind: str = "transaction"
    page: int | None = None
    bbox: list[float] | None = None
    raw_text: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence_id: str | None = None


class CandidateMovement(_Schema):
    """Candidato normalizado antes de pasar por dedup/resolución de cuentas."""

    dedup_key: str | None = None
    kind: str | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    score: float | None = None


class DocumentIssue(_Schema):
    code: str
    severity: Literal["info", "warning", "error"] = "warning"
    message: str = ""
    evidence_id: str | None = None


class EnvelopeConfidence(_Schema):
    overall: float = Field(default=0.0, ge=0.0, le=1.0)
    extraction: float = Field(default=0.0, ge=0.0, le=1.0)
    account: float = Field(default=0.0, ge=0.0, le=1.0)


class TraceStep(_Schema):
    step: str
    ms: float | None = None
    detail: str | None = None


class DocumentEnvelope(_Schema):
    """Hechos extraídos de un documento, con evidencia e incidencias."""

    document_type: DocumentType = DocumentType.unknown
    bank: str | None = None
    account: AccountRef | None = None
    period: DocumentPeriod | None = None
    balances: Balances | None = None
    units: list[DocumentUnit] = Field(default_factory=list)
    candidates: list[CandidateMovement] = Field(default_factory=list)
    issues: list[DocumentIssue] = Field(default_factory=list)
    confidence: EnvelopeConfidence = Field(default_factory=EnvelopeConfidence)
    trace: list[TraceStep] = Field(default_factory=list)
    needs_review: bool = False
    source_file: str | None = None

    @field_validator("document_type", mode="before")
    @classmethod
    def _document_type_from_string(cls, value: Any) -> Any:
        if isinstance(value, str):
            try:
                return DocumentType(value)
            except ValueError:
                return DocumentType.unknown
        return value


__all__ = [
    "AccountRef",
    "Allowance",
    "Balances",
    "CandidateMovement",
    "DecisionQuestion",
    "DecisionResult",
    "DocumentEnvelope",
    "DocumentIssue",
    "DocumentPeriod",
    "DocumentType",
    "DocumentUnit",
    "EnvelopeConfidence",
    "LLMResult",
    "QuestionType",
    "TraceStep",
    "Usage",
]
