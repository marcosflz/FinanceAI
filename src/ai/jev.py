"""Cliente tipado para el decisor Jev de TypeSafe.

Endpoint: ``POST https://api.typesafe.ai/v1/systemone``.

Contrato (resumido):

- Request: ``state`` (texto u objeto), ``model`` (default ``jev-latest``) y
  ``questions`` (mapa id → pregunta ``choice``/``score``/``noul``).
- Response: ``model``, ``answers`` (mapa id → respuesta) y ``usage``.

Las respuestas ``noul`` no traen ``confidence``; se calcula ``abs(2p - 1)``.
Por privacidad no se loguea la API key ni el ``state`` completo, y los errores
no incluyen el cuerpo de la petición.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .schemas import DecisionQuestion, Usage

DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MODEL = "jev-latest"
DEFAULT_TIMEOUT = 5.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_BACKOFF_BASE = 0.5
USER_AGENT = "financial-tools/0.1"


# ---------------------------------------------------------------------------
# Errores
# ---------------------------------------------------------------------------


class JevError(Exception):
    """Error base de Jev."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.cause = cause


class JevAuthError(JevError):
    """401/403: API key ausente o inválida."""


class JevRateLimitError(JevError):
    """429: límite de peticiones."""


class JevServerError(JevError):
    """5xx, timeout o error de red."""


class JevResponseError(JevError):
    """Respuesta no parseable o con una forma inesperada."""


# ---------------------------------------------------------------------------
# Respuestas tipadas
# ---------------------------------------------------------------------------


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


class JevAnswer(BaseModel):
    """Una respuesta de Jev normalizada, independiente del tipo de pregunta."""

    model_config = ConfigDict(extra="ignore")

    question_id: str = ""
    type: str = "noul"
    choice: str | None = None
    score: float | None = None
    noul: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float | None = None
    confidence_derived: bool = False
    legend: dict[str, str] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, question_id: str, payload: Any) -> JevAnswer:
        """Normaliza una respuesta cruda de la API de TypeSafe."""
        if isinstance(payload, str):
            payload = {"type": "choice", "choice": payload}
        elif isinstance(payload, (int, float)) and not isinstance(payload, bool):
            payload = {"type": "noul", "noul": float(payload)}
        data: Mapping[str, Any] = payload if isinstance(payload, Mapping) else {}

        raw_type = data.get("type")
        if isinstance(raw_type, str) and raw_type:
            answer_type = raw_type
        elif data.get("noul") is not None:
            answer_type = "noul"
        elif data.get("score") is not None:
            answer_type = "score"
        elif data.get("choice") is not None or data.get("probabilities"):
            answer_type = "choice"
        else:
            answer_type = "noul"

        probabilities: dict[str, float] = {}
        raw_probabilities = data.get("probabilities")
        if isinstance(raw_probabilities, Mapping):
            for option, probability in raw_probabilities.items():
                parsed = _as_float(probability)
                if parsed is not None:
                    probabilities[str(option)] = _clamp01(parsed)

        choice = data.get("choice")
        choice = str(choice) if choice is not None else None
        if choice is None and probabilities:
            choice = max(probabilities, key=probabilities.get)

        noul = _as_float(data.get("noul"))
        if noul is not None:
            noul = _clamp01(noul)
        score = _as_float(data.get("score"))

        confidence = _as_float(data.get("confidence"))
        confidence_derived = False
        if confidence is None:
            if answer_type == "noul" and noul is not None:
                # Jev no devuelve confidence en noul; |2p-1| es la confianza.
                confidence = abs(2.0 * noul - 1.0)
                confidence_derived = True
            elif probabilities:
                confidence = max(probabilities.values())
                confidence_derived = True
        if confidence is not None:
            confidence = _clamp01(confidence)

        legend: dict[str, str] = {}
        raw_legend = data.get("legend")
        if isinstance(raw_legend, Mapping):
            legend = {str(key): str(value) for key, value in raw_legend.items()}

        return cls(
            question_id=question_id,
            type=answer_type,
            choice=choice,
            score=score,
            noul=noul,
            probabilities=probabilities,
            confidence=confidence,
            confidence_derived=confidence_derived,
            legend=legend,
            raw=dict(data),
        )

    # -- lecturas de conveniencia ---------------------------------------

    def __getitem__(self, key: str) -> Any:
        """Permite usar la respuesta como mapping además de como objeto."""
        if key not in type(self).model_fields:
            raise KeyError(key)
        return getattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def effective_confidence(self) -> float | None:
        if self.confidence is not None:
            return self.confidence
        if self.noul is not None:
            return abs(2.0 * self.noul - 1.0)
        if self.probabilities:
            return max(self.probabilities.values())
        return None

    @property
    def selected_probability(self) -> float | None:
        if self.type == "noul":
            return self.noul
        if self.choice is not None and self.choice in self.probabilities:
            return self.probabilities[self.choice]
        if self.probabilities:
            return max(self.probabilities.values())
        return None

    @property
    def top2_margin(self) -> float | None:
        if len(self.probabilities) >= 2:
            ordered = sorted(self.probabilities.values(), reverse=True)
            return ordered[0] - ordered[1]
        if len(self.probabilities) == 1:
            return next(iter(self.probabilities.values()))
        return None


class JevResult(BaseModel):
    """Respuesta completa de ``/v1/systemone``."""

    model_config = ConfigDict(extra="ignore")

    model: str
    requested_model: str | None = None
    answers: dict[str, JevAnswer] = Field(default_factory=dict)
    usage: Usage = Field(default_factory=Usage)
    raw: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Utilidades internas
# ---------------------------------------------------------------------------


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _question_payload(question: DecisionQuestion | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(question, DecisionQuestion):
        payload: dict[str, Any] = {
            "type": question.type.value,
            "instructions": question.instructions,
        }
        if question.criteria is not None:
            payload["criteria"] = _jsonable(question.criteria)
        return payload
    if isinstance(question, Mapping):
        return _jsonable(dict(question))
    raise TypeError("cada pregunta debe ser DecisionQuestion o un mapping")


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


class JevProvider:
    """Proveedor de decisión tipado contra la API de TypeSafe/Jev."""

    name = "jev"

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_base: float | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("TYPESAFE_API_KEY", "")
        ).strip()
        self.base_url = (
            base_url or os.getenv("JEV_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.getenv("JEV_MODEL") or DEFAULT_MODEL
        self.timeout = (
            timeout if timeout is not None else _env_float("JEV_TIMEOUT", DEFAULT_TIMEOUT)
        )
        self.max_retries = max(
            0,
            max_retries
            if max_retries is not None
            else _env_int("JEV_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        )
        self.backoff_base = (
            backoff_base
            if backoff_base is not None
            else _env_float("JEV_BACKOFF", DEFAULT_BACKOFF_BASE)
        )
        self.user_agent = user_agent
        self._sleep = sleep or time.sleep

        if http_client is not None:
            self._client = http_client
            self._owns_client = False
        else:
            self._client = httpx.Client(
                timeout=httpx.Timeout(self.timeout),
                transport=transport,
            )
            self._owns_client = True

    # -- ciclo de vida ----------------------------------------------------

    @classmethod
    def from_env(cls, **overrides: Any) -> JevProvider:
        """Construye el proveedor leyendo ``TYPESAFE_*``/``JEV_*`` del entorno."""
        return cls(**overrides)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> JevProvider:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- API --------------------------------------------------------------

    def ask(
        self,
        state: Any,
        questions: Mapping[str, DecisionQuestion | Mapping[str, Any]],
        *,
        timeout: float | None = None,
    ) -> dict[str, JevAnswer]:
        """Devuelve solo las respuestas normalizadas (interfaz del decisor)."""
        return dict(self.system_one(state, questions, timeout=timeout).answers)

    def system_one(
        self,
        state: Any,
        questions: Mapping[str, DecisionQuestion | Mapping[str, Any]],
        *,
        model: str | None = None,
        timeout: float | None = None,
    ) -> JevResult:
        """Llama a ``/v1/systemone`` con retry y devuelve un resultado tipado."""
        if not questions:
            raise ValueError("Jev requiere al menos una pregunta")

        target_model = model or self.model
        payload = {
            "state": _jsonable(state),
            "model": target_model,
            "questions": {
                str(question_id): _question_payload(question)
                for question_id, question in questions.items()
            },
        }

        data = self._post(payload, timeout=timeout)

        answers_raw = data.get("answers")
        if not isinstance(answers_raw, Mapping):
            # Tolerancia a respuestas de una sola pregunta sin envoltorio.
            if any(key in data for key in ("choice", "score", "noul", "probabilities")):
                first_id = next(iter(questions))
                answers_raw = {str(first_id): data}
            else:
                raise JevResponseError("la respuesta de Jev no contiene 'answers'")

        answers: dict[str, JevAnswer] = {}
        for question_id, raw_answer in answers_raw.items():
            answers[str(question_id)] = JevAnswer.from_payload(
                str(question_id), raw_answer
            )

        return JevResult(
            model=str(data.get("model") or target_model),
            requested_model=target_model,
            answers=answers,
            usage=Usage.from_payload(
                data.get("usage") if isinstance(data.get("usage"), Mapping) else None
            ),
            raw=dict(data),
        )

    # -- transporte -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise JevAuthError(
                "TYPESAFE_API_KEY no configurada; el proveedor Jev no puede decidir",
                status_code=401,
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }

    @staticmethod
    def _error_from_response(response: httpx.Response) -> JevError:
        status = response.status_code
        # No se incluye el cuerpo: podría contener datos del state.
        message = f"Jev respondió HTTP {status}"
        if status in (401, 403):
            return JevAuthError(message, status_code=status)
        if status == 429:
            return JevRateLimitError(message, status_code=status, retryable=True)
        if status >= 500 or status in (408, 409, 425):
            return JevServerError(message, status_code=status, retryable=True)
        return JevResponseError(message, status_code=status)

    def _post(
        self, payload: Mapping[str, Any], *, timeout: float | None = None
    ) -> Mapping[str, Any]:
        headers = self._headers()
        effective_timeout = timeout if timeout is not None else self.timeout
        last_error: JevError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    self.base_url,
                    json=_jsonable(dict(payload)),
                    headers=headers,
                    timeout=effective_timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = JevServerError(
                    f"timeout tras {effective_timeout:g}s",
                    retryable=True,
                    cause=exc,
                )
            except httpx.HTTPError as exc:
                last_error = JevServerError(
                    f"error de red: {type(exc).__name__}",
                    retryable=True,
                    cause=exc,
                )
            else:
                if response.status_code >= 400:
                    last_error = self._error_from_response(response)
                else:
                    try:
                        data = response.json()
                    except (ValueError, TypeError) as exc:
                        last_error = JevResponseError(
                            "la respuesta HTTP no es JSON",
                            status_code=response.status_code,
                            retryable=True,
                            cause=exc,
                        )
                    else:
                        if not isinstance(data, Mapping):
                            last_error = JevResponseError(
                                "la respuesta JSON no es un objeto",
                                status_code=response.status_code,
                                retryable=True,
                            )
                        else:
                            return data

            assert last_error is not None
            if not last_error.retryable or attempt >= self.max_retries:
                raise last_error
            self._sleep(self.backoff_base * (2 ** attempt))

        assert last_error is not None
        raise last_error


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "JevAnswer",
    "JevAuthError",
    "JevError",
    "JevProvider",
    "JevRateLimitError",
    "JevResponseError",
    "JevResult",
    "JevServerError",
]
