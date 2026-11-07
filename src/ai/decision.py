"""Orquestador de decisión: preguntas atómicas, umbrales y cache.

El orquestador no habla con el LLM: recibe un ``state`` estructurado y un mapa
de ``DecisionQuestion``, llama a un ``DecisionProvider`` (Jev o un fake) y
aplica las políticas de auto-aceptación del plan:

============================  ==========================  =====================
Decisión                      Auto-aceptar                Revisar si
============================  ==========================  =====================
Categoría de gasto/ingreso    ``confidence ≥ 0.90`` y      ``< 0.75``
                              margen top-2 ``≥ 0.15``
Transferencia interna         ``P ≥ 0.95``                ``0.80 – 0.95``
Duplicado                     ``P ≥ 0.90``                ``0.70 – 0.90``
Documento válido              ``P ≥ 0.95``                ``0.80 – 0.95``
============================  ==========================  =====================

En la práctica, cualquier respuesta por debajo de su umbral de auto-aceptación
marca ``needs_review``. Las preguntas de revisión (``requiere_revision``) solo
fuerzan revisión cuando su probabilidad de "sí" es alta.

La cache se indexa por ``SHA-256(state + questions)`` y guarda las respuestas
crudas normalizadas; así un cambio de ``risk`` recalcula la decisión sin volver
a llamar al proveedor.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import OrderedDict
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from .jev import JevAnswer, JevResult
from .schemas import DecisionQuestion, DecisionResult


@dataclass(frozen=True)
class Thresholds:
    """Umbrales de decisión configurables (los del plan por defecto)."""

    category_auto: float = 0.90
    category_margin: float = 0.15
    category_review_below: float = 0.75

    transfer_auto: float = 0.95
    transfer_review_below: float = 0.80

    duplicate_auto: float = 0.90
    duplicate_review_below: float = 0.70

    document_auto: float = 0.95
    document_review_below: float = 0.80

    generic_auto: float = 0.90
    generic_review_below: float = 0.75


@dataclass(frozen=True)
class _Policy:
    kind: str
    auto: float
    review_below: float
    margin: float | None = None


@dataclass
class _CacheEntry:
    answers: dict[str, dict[str, Any]]
    model: str | None


@runtime_checkable
class DecisionProvider(Protocol):
    """Proveedor de decisión tipado (Jev o un fake en tests)."""

    name: str

    def ask(
        self,
        state: Any,
        questions: Mapping[str, DecisionQuestion | Mapping[str, Any]],
        *,
        timeout: float = 5.0,
    ) -> Any:
        """Devuelve ``JevResult``, un mapa de ``JevAnswer`` o dicts."""


def _normalize(text: Any) -> str:
    decomposed = unicodedata.normalize("NFKD", str(text))
    ascii_text = decomposed.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")


def _canonical(value: Any) -> Any:
    if isinstance(value, DecisionQuestion):
        return value.model_dump(mode="json")
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _coerce_answer(question_id: str, value: Any) -> JevAnswer:
    if isinstance(value, JevAnswer):
        return value
    if isinstance(value, (Mapping, str)) or (
        isinstance(value, (int, float)) and not isinstance(value, bool)
    ):
        return JevAnswer.from_payload(question_id, value)
    if isinstance(value, BaseModel):
        return JevAnswer.from_payload(question_id, value.model_dump())
    if hasattr(value, "__dict__"):
        return JevAnswer.from_payload(question_id, vars(value))
    raise TypeError(f"respuesta no soportada para '{question_id}': {type(value)!r}")


_YES_VALUES = {
    "si",
    "yes",
    "true",
    "1",
    "revisar",
    "review",
    "revision",
    "needs_review",
}


class DecisionOrchestrator:
    """Aplica umbrales a las respuestas de un proveedor de decisión."""

    def __init__(
        self,
        provider: DecisionProvider,
        *,
        thresholds: Thresholds | None = None,
        cache: MutableMapping[str, _CacheEntry] | None = None,
        max_cache_entries: int = 1024,
    ) -> None:
        self.provider = provider
        self.thresholds = thresholds or Thresholds()
        self._cache: MutableMapping[str, _CacheEntry] = (
            cache if cache is not None else OrderedDict()
        )
        self.max_cache_entries = max(1, max_cache_entries)

    # -- utilidades -------------------------------------------------------

    @staticmethod
    def state_hash(
        state: Any,
        questions: Mapping[str, DecisionQuestion | Mapping[str, Any]],
    ) -> str:
        """SHA-256 canónico de ``state + questions``."""
        payload = {
            "state": _canonical(state),
            "questions": {
                str(question_id): _canonical(question)
                for question_id, question in sorted(questions.items())
            },
        }
        serialized = json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def clear_cache(self) -> None:
        self._cache.clear()

    def _provider_name(self) -> str:
        return str(getattr(self.provider, "name", type(self.provider).__name__))

    def _provider_model(self) -> str | None:
        model = getattr(self.provider, "model", None)
        return str(model) if model is not None else None

    def _store_cache(
        self, key: str, answers: Mapping[str, JevAnswer], model: str | None
    ) -> None:
        self._cache[key] = _CacheEntry(
            answers={
                question_id: answer.model_dump(mode="json")
                for question_id, answer in answers.items()
            },
            model=model,
        )
        if isinstance(self._cache, OrderedDict):
            self._cache.move_to_end(key)
            while len(self._cache) > self.max_cache_entries:
                self._cache.popitem(last=False)
        else:
            while len(self._cache) > self.max_cache_entries:
                oldest = next(iter(self._cache))
                del self._cache[oldest]

    def _load_cache(self, key: str) -> tuple[dict[str, JevAnswer], str | None] | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        if isinstance(self._cache, OrderedDict):
            self._cache.move_to_end(key)
        answers = {
            question_id: JevAnswer.model_validate(payload)
            for question_id, payload in entry.answers.items()
        }
        return answers, entry.model

    # -- extracción de respuestas ----------------------------------------

    @staticmethod
    def _extract_answers(raw: Any) -> tuple[dict[str, JevAnswer], str | None]:
        if isinstance(raw, JevResult):
            return dict(raw.answers), raw.model
        if isinstance(raw, Mapping):
            if (
                "answers" in raw
                and isinstance(raw.get("answers"), Mapping)
                and not any(
                    key in raw for key in ("choice", "score", "noul", "probabilities")
                )
            ):
                answers_raw = raw["answers"]
                model = raw.get("model")
                return (
                    {
                        str(question_id): _coerce_answer(str(question_id), value)
                        for question_id, value in answers_raw.items()
                    },
                    str(model) if model is not None else None,
                )
            return (
                {
                    str(question_id): _coerce_answer(str(question_id), value)
                    for question_id, value in raw.items()
                },
                None,
            )
        raise TypeError(f"respuesta del proveedor no soportada: {type(raw)!r}")

    # -- políticas --------------------------------------------------------

    def _policy_for(self, question_id: str, question_type: str) -> _Policy:
        name = _normalize(question_id)
        t = self.thresholds

        if "transfer" in name or "traspaso" in name:
            return _Policy(
                "transfer", t.transfer_auto, t.transfer_review_below
            )
        if "duplicad" in name or "duplicate" in name:
            return _Policy(
                "duplicate", t.duplicate_auto, t.duplicate_review_below
            )
        if "document" in name and (
            "valid" in name or "valido" in name or "validez" in name
        ):
            return _Policy("document", t.document_auto, t.document_review_below)
        if "revision" in name or "review" in name:
            return _Policy(
                "review_flag", t.generic_auto, t.generic_review_below
            )
        if question_type == "choice":
            # El margen top-2 es una regla de categoría, no de cualquier choice.
            requires_margin = any(
                token in name
                for token in ("categoria", "category", "clasificacion", "classification")
            )
            return _Policy(
                "choice",
                t.category_auto,
                t.category_review_below,
                t.category_margin if requires_margin else None,
            )
        return _Policy("generic", t.generic_auto, t.generic_review_below)

    @staticmethod
    def _yes_probability(answer: JevAnswer) -> float | None:
        if answer.noul is not None:
            return answer.noul
        if answer.choice is not None:
            probability = answer.probabilities.get(answer.choice)
            if probability is None:
                return None
            if _normalize(answer.choice) in _YES_VALUES:
                return probability
            return 1.0 - probability
        if answer.score is not None:
            return answer.score
        return None

    @staticmethod
    def _decision_strength(
        answer: JevAnswer, policy: _Policy
    ) -> float | None:
        """Fuerza de la respuesta para comparar con el umbral de la política.

        En ``noul`` las políticas de transferencia/duplicado/documento se
        expresan como probabilidad (``P ≥ 0.95``), no como ``|2p-1|``. Se usa
        ``max(p, 1-p)`` para que un "no" muy seguro también sea auto-aceptable.
        En el resto de casos se usa la confianza efectiva.
        """
        if (
            policy.kind in {"transfer", "duplicate", "document"}
            and answer.noul is not None
        ):
            return max(answer.noul, 1.0 - answer.noul)
        return answer.effective_confidence

    # -- decisión ---------------------------------------------------------

    def decide(
        self,
        state: Any,
        questions: Mapping[str, DecisionQuestion | Mapping[str, Any]],
        *,
        risk: str = "normal",
        use_cache: bool = True,
        timeout: float = 5.0,
    ) -> DecisionResult:
        """Decide y devuelve respuestas, confianza y ``needs_review``."""
        if not questions:
            raise ValueError("decide requiere al menos una pregunta")

        normalized_questions: dict[str, DecisionQuestion] = {}
        for question_id, question in questions.items():
            if isinstance(question, DecisionQuestion):
                normalized_questions[str(question_id)] = question
            else:
                normalized_questions[str(question_id)] = (
                    DecisionQuestion.model_validate(question)
                )

        started = time.perf_counter()
        cache_key = self.state_hash(state, normalized_questions)
        cached = False
        answers: dict[str, JevAnswer] | None = None
        model: str | None = None

        if use_cache:
            loaded = self._load_cache(cache_key)
            if loaded is not None:
                answers, model = loaded
                cached = True

        if answers is None:
            raw = self.provider.ask(state, normalized_questions, timeout=timeout)
            answers, provider_model = self._extract_answers(raw)
            model = provider_model or self._provider_model()
            if use_cache:
                self._store_cache(cache_key, answers, model)

        risk_normalized = _normalize(risk)
        risky = risk_normalized in {"high", "alto", "riesgo_alto"}

        answers_out: dict[str, dict[str, Any]] = {}
        reasons: list[str] = []
        decision_confidences: list[float] = []
        all_confidences: list[float] = []

        for question_id, question in normalized_questions.items():
            answer = answers.get(question_id)
            question_type = question.type.value

            if answer is None:
                answers_out[question_id] = {
                    "type": question_type,
                    "missing": True,
                    "confidence": 0.0,
                }
                reasons.append(f"{question_id}: sin respuesta del decisor")
                continue

            effective = answer.effective_confidence
            all_confidences.append(effective if effective is not None else 0.0)
            policy = self._policy_for(question_id, question_type)
            margin = answer.top2_margin
            strength = self._decision_strength(answer, policy)

            answers_out[question_id] = {
                "type": answer.type or question_type,
                "choice": answer.choice,
                "score": answer.score,
                "noul": answer.noul,
                "probabilities": answer.probabilities,
                "confidence": (
                    round(effective, 4) if effective is not None else None
                ),
                "confidence_source": (
                    "derived" if answer.confidence_derived else "provider"
                ),
                "decision_strength": (
                    round(strength, 4) if strength is not None else None
                ),
                "top2_margin": round(margin, 4) if margin is not None else None,
                "selected_probability": answer.selected_probability,
            }

            if policy.kind == "review_flag":
                yes_probability = self._yes_probability(answer)
                if yes_probability is None:
                    reasons.append(
                        f"{question_id}: no se pudo leer la recomendación de revisión"
                    )
                elif yes_probability >= 0.5:
                    reasons.append(
                        f"{question_id}: el decisor recomienda revisión "
                        f"(P={yes_probability:.2f})"
                    )
                # Por debajo de 0.5 la recomendación es solo informativa: no
                # debe forzar una revisión si la categoría es sólida.
                # Esta pregunta no reduce la confianza global de la decisión.
                continue

            decision_confidences.append(effective if effective is not None else 0.0)

            metric = (
                "probabilidad"
                if policy.kind in {"transfer", "duplicate", "document"}
                and answer.noul is not None
                else "confianza"
            )
            if strength is None:
                reasons.append(f"{question_id}: confianza no disponible")
                continue

            if strength < policy.review_below:
                reasons.append(
                    f"{question_id}: {metric} {strength:.2f} "
                    f"< {policy.review_below:.2f} (revisión)"
                )
                continue
            if strength < policy.auto:
                reasons.append(
                    f"{question_id}: {metric} {strength:.2f} "
                    f"< {policy.auto:.2f} (auto-aceptación)"
                )
            if (
                policy.margin is not None
                and margin is not None
                and margin < policy.margin
            ):
                reasons.append(
                    f"{question_id}: margen top-2 {margin:.2f} "
                    f"< {policy.margin:.2f}"
                )

        if risky:
            reasons.append(f"riesgo '{risk}' exige revisión humana")

        confidence_values = decision_confidences or all_confidences
        confidence = min(confidence_values) if confidence_values else 0.0

        if reasons:
            explanation = "Revisión: " + "; ".join(reasons)
        else:
            summaries = []
            for question_id, payload in answers_out.items():
                if payload.get("missing"):
                    continue
                summary = (
                    payload.get("choice")
                    or payload.get("noul")
                    or payload.get("score")
                    or "—"
                )
                summaries.append(
                    f"{question_id}={summary} "
                    f"(conf {payload.get('confidence')})"
                )
            explanation = "Auto-aceptado: " + "; ".join(summaries)

        latency_ms = round((time.perf_counter() - started) * 1000.0, 3)

        return DecisionResult(
            provider=self._provider_name(),
            model=model,
            answers=answers_out,
            confidence=round(confidence, 4),
            needs_review=bool(reasons),
            explanation=explanation[:1000],
            state_hash=cache_key,
            cached=cached,
            latency_ms=latency_ms,
        )


__all__ = [
    "DecisionOrchestrator",
    "DecisionProvider",
    "Thresholds",
]
