"""Cliente Python directo para la Inference API de OpenCode Go.

No hay ``opencode serve``, sidecar Node ni OpenRouter: este módulo habla HTTP
con ``https://opencode.ai/inference/go`` usando ``httpx``.

Familias de API:

- ``deepseek-v4.1-flash``, ``glm-5.3-flash``, ``mimo-v2.6-flash``, ``qwen3.8-flash``…
  → ``POST /openai/v1/chat/completions``.
- ``gpt-6-luna`` (y otros GPT/Grok/Muse) → ``POST /openai/v1/responses``.
- Claude → ``/anthropic/v1/messages`` (stub tipado, pendiente F4).
- Gemini → ``/google/v1beta/models/<model>:generateContent`` (stub tipado).

Go traduce los modelos de texto entre familias de API, por eso los modelos de
fallback del plan (GLM/Qwen/MiMo) se enrutan a Chat Completions aunque su API
nativa sea otra. El routing se puede sobrescribir con ``api_families``.

Fallback: ``OPENCODE_MODEL`` (default ``deepseek-v4.1-flash``) y luego
``OPENCODE_FALLBACK_MODELS`` (coma-separado). Solo se cambia de modelo ante
errores recuperables (429/5xx/modelo no disponible/timeout/JSON inválido) o si
el allowance restante baja del umbral configurado.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from .schemas import Allowance, LLMResult, Usage

DEFAULT_BASE_URL = "https://opencode.ai/inference/go"
DEFAULT_MODEL = "deepseek-v4.1-flash"
DEFAULT_FALLBACK_MODELS: tuple[str, ...] = (
    "glm-5.3-flash",
    "qwen3.8-flash",
    "mimo-v2.6-flash",
    "gpt-6-luna",
)
USER_AGENT = "financial-tools/0.1"
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5
DEFAULT_MIN_ALLOWANCE_RATIO = 0.20

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Errores tipados
# ---------------------------------------------------------------------------


class OpenCodeGoError(Exception):
    """Error base del cliente OpenCode Go.

    ``retryable`` indica si tiene sentido reintentar el mismo modelo.
    ``fallback_allowed`` indica si tiene sentido probar el siguiente modelo.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        fallback_allowed: bool = False,
        body: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.fallback_allowed = fallback_allowed
        self.body = body
        self.cause = cause


class OpenCodeAuthError(OpenCodeGoError):
    """401: API key ausente, inválida o revocada. Nunca se reintenta."""


class OpenCodeRateLimitError(OpenCodeGoError):
    """429: límite de peticiones/uso. Reintentable y con fallback."""


class OpenCodeQuotaError(OpenCodeRateLimitError):
    """402: saldo/allowance agotado para el modelo actual."""

    def __init__(self, message: str, **kwargs: Any) -> None:
        kwargs.setdefault("retryable", False)
        kwargs.setdefault("fallback_allowed", True)
        super().__init__(message, **kwargs)


class OpenCodeModelError(OpenCodeGoError):
    """403/404: modelo no permitido o inexistente. Fallback a otro modelo."""


class OpenCodeServerError(OpenCodeGoError):
    """5xx, timeout o error de red. Reintentable y con fallback."""


class OpenCodeResponseError(OpenCodeGoError):
    """Respuesta no parseable o que no cumple el JSON Schema/Pydantic."""


# ---------------------------------------------------------------------------
# Utilidades
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


def _parse_models(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(model.strip() for model in value.split(",") if model.strip())


def _min_allowance_ratio(value: float | str | None) -> float:
    if value is None or value == "":
        return DEFAULT_MIN_ALLOWANCE_RATIO
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_ALLOWANCE_RATIO
    if parsed > 1:
        parsed /= 100.0
    return max(0.0, min(1.0, parsed))


def _jsonable(value: Any) -> Any:
    """Convierte modelos/Decimal/fechas a algo serializable por httpx."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _jsonable_mapping(value: Any) -> dict[str, Any]:
    converted = _jsonable(value)
    return converted if isinstance(converted, dict) else {"value": converted}


def _truncate(text: str | None, limit: int = 500) -> str:
    if not text:
        return ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_text(text: str) -> Any:
    """Extrae JSON de la respuesta de un modelo, tolerando fences Markdown."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("respuesta vacía")

    candidates = [raw]
    without_fence = _FENCE_RE.sub("", raw).strip()
    if without_fence != raw:
        candidates.append(without_fence)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    # Último recurso: recortar prosa alrededor del primer objeto/array JSON.
    for opener, closer in (("{", "}"), ("[", "]")):
        start = without_fence.find(opener)
        end = without_fence.rfind(closer)
        if 0 <= start < end:
            try:
                return json.loads(without_fence[start : end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError("la respuesta no contiene JSON válido")


def _schema_info(
    schema: type[BaseModel] | Mapping[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None, type[BaseModel] | None]:
    """Devuelve (nombre, JSON Schema, modelo Pydantic opcional)."""
    if schema is None:
        return None, None, None
    if isinstance(schema, type) and issubclass(schema, BaseModel):
        return schema.__name__, schema.model_json_schema(), schema
    if isinstance(schema, Mapping):
        name = schema.get("title")
        return (str(name) if name else "structured_output"), dict(schema), None
    raise TypeError("schema debe ser un modelo Pydantic o un JSON Schema (dict)")


def _validate_parsed(parsed: Any, model_cls: type[BaseModel] | None) -> Any:
    if model_cls is None:
        return parsed
    return model_cls.model_validate(parsed)


def _extract_chat_text(data: Mapping[str, Any]) -> str:
    try:
        message = data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("respuesta Chat Completions sin choices[0].message") from exc

    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, str) and content.strip():
        return content
    if isinstance(content, Mapping):
        text = content.get("text")
        if isinstance(text, str) and text.strip():
            return text
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        if "".join(parts).strip():
            return "".join(parts)
    raise ValueError("respuesta Chat Completions sin contenido de texto")


def _extract_responses_text(data: Mapping[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    output = data.get("output")
    if isinstance(output, str) and output.strip():
        return output
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, Mapping):
                continue
            item_type = item.get("type")
            if item_type in {"output_text", "text"} and isinstance(
                item.get("text"), str
            ):
                parts.append(item["text"])
            content = item.get("content")
            if isinstance(content, str):
                parts.append(content)
            elif isinstance(content, list):
                for chunk in content:
                    if isinstance(chunk, str):
                        parts.append(chunk)
                    elif isinstance(chunk, Mapping) and isinstance(
                        chunk.get("text"), str
                    ):
                        parts.append(chunk["text"])
    if "".join(parts).strip():
        return "".join(parts)
    raise ValueError("respuesta Responses sin texto de salida")


def _usage_and_allowance(
    data: Mapping[str, Any], headers: Mapping[str, str] | None = None
) -> tuple[Usage, Allowance]:
    usage_raw = data.get("usage")
    usage = Usage.from_payload(usage_raw if isinstance(usage_raw, Mapping) else None)
    allowance_value = None
    if isinstance(usage_raw, Mapping):
        opencode = usage_raw.get("opencode")
        if isinstance(opencode, Mapping):
            allowance_value = opencode.get("allowance")
    return usage, Allowance.from_payload(allowance_value, headers)


def _input_to_messages(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list) and all(
        isinstance(item, Mapping) and "role" in item for item in value
    ):
        return [dict(item) for item in value]
    return [
        {
            "role": "user",
            "content": json.dumps(_jsonable(value), ensure_ascii=False),
        }
    ]


_RESPONSES_PREFIXES = ("gpt-", "grok-", "muse-")
_ANTHROPIC_PREFIXES = ("claude-",)
_GOOGLE_PREFIXES = ("gemini-",)


def api_family_for_model(
    model: str, overrides: Mapping[str, str] | None = None
) -> str:
    """Devuelve ``chat``, ``responses``, ``anthropic`` o ``google``."""
    if overrides:
        if model in overrides:
            return overrides[model]
        lowered = model.lower()
        if lowered in overrides:
            return overrides[lowered]

    name = model.lower()
    if name.startswith(_RESPONSES_PREFIXES):
        return "responses"
    if name.startswith(_ANTHROPIC_PREFIXES):
        return "anthropic"
    if name.startswith(_GOOGLE_PREFIXES):
        return "google"
    # Qwen/MiMo/GLM/DeepSeek y el resto: Chat Completions (Go traduce).
    return "chat"


# ---------------------------------------------------------------------------
# Cliente
# ---------------------------------------------------------------------------


class OpenCodeGoClient:
    """Cliente síncrono para OpenCode Go con retry, structured output y fallback."""

    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str | None = None,
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        session_id: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff_base: float | None = None,
        min_allowance_ratio: float | str | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] | None = None,
        user_agent: str = USER_AGENT,
        api_families: Mapping[str, str] | None = None,
        strict_schema: bool = True,
    ) -> None:
        self.api_key = (
            api_key if api_key is not None else os.getenv("OPENCODE_API_KEY", "")
        ).strip()
        self.base_url = (
            base_url or os.getenv("OPENCODE_BASE_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.getenv("OPENCODE_MODEL") or DEFAULT_MODEL

        if fallback_models is None:
            env_models = os.getenv("OPENCODE_FALLBACK_MODELS")
            configured = (
                _parse_models(env_models)
                if env_models is not None
                else DEFAULT_FALLBACK_MODELS
            )
        else:
            configured = tuple(fallback_models)
        seen = {self.model}
        fallbacks: list[str] = []
        for candidate in configured:
            if candidate and candidate not in seen:
                seen.add(candidate)
                fallbacks.append(candidate)
        self.fallback_models = tuple(fallbacks)

        self.session_id = (
            session_id or os.getenv("OPENCODE_SESSION_ID") or str(uuid.uuid4())
        )
        self.timeout = (
            timeout if timeout is not None else _env_float("OPENCODE_TIMEOUT", DEFAULT_TIMEOUT)
        )
        self.max_retries = max(
            0,
            max_retries
            if max_retries is not None
            else _env_int("OPENCODE_MAX_RETRIES", DEFAULT_MAX_RETRIES),
        )
        self.backoff_base = (
            backoff_base
            if backoff_base is not None
            else _env_float("OPENCODE_BACKOFF", DEFAULT_BACKOFF_BASE)
        )
        self.min_allowance_ratio = _min_allowance_ratio(
            min_allowance_ratio
            if min_allowance_ratio is not None
            else os.getenv("OPENCODE_MIN_ALLOWANCE_PCT")
        )
        self.user_agent = user_agent
        self.api_families = dict(api_families or {})
        self.strict_schema = strict_schema
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
    def from_env(cls, **overrides: Any) -> OpenCodeGoClient:
        """Construye el cliente leyendo ``OPENCODE_*`` del entorno."""
        return cls(**overrides)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenCodeGoClient:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    # -- cabeceras y errores ---------------------------------------------

    def _headers(self, session_id: str | None = None) -> dict[str, str]:
        if not self.api_key:
            raise OpenCodeAuthError(
                "OPENCODE_API_KEY no configurada; el cliente no puede llamar a Go",
                status_code=401,
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": self.user_agent,
            "x-opencode-session": session_id or self.session_id,
        }

    @staticmethod
    def _error_from_response(response: httpx.Response) -> OpenCodeGoError:
        status = response.status_code
        body = _truncate(response.text)
        message = f"OpenCode Go respondió HTTP {status}"
        if status == 401:
            return OpenCodeAuthError(message, status_code=status, body=body)
        if status == 402:
            return OpenCodeQuotaError(message, status_code=status, body=body)
        if status in (403, 404):
            return OpenCodeModelError(
                message, status_code=status, fallback_allowed=True, body=body
            )
        if status == 429:
            return OpenCodeRateLimitError(
                message, status_code=status, retryable=True, fallback_allowed=True, body=body
            )
        if status >= 500 or status in (408, 409, 425):
            return OpenCodeServerError(
                message, status_code=status, retryable=True, fallback_allowed=True, body=body
            )
        return OpenCodeResponseError(message, status_code=status, body=body)

    def _post(
        self,
        path: str,
        payload: Mapping[str, Any],
        *,
        session_id: str | None,
        parse: Callable[[Mapping[str, Any], httpx.Headers], T],
    ) -> T:
        """POST con retry exponencial para 429/5xx/timeout/JSON inválido."""
        url = f"{self.base_url}{path}"
        headers = self._headers(session_id)
        last_error: OpenCodeGoError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(
                    url,
                    json=_jsonable_mapping(payload),
                    headers=headers,
                    timeout=self.timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = OpenCodeServerError(
                    f"timeout tras {self.timeout:g}s",
                    retryable=True,
                    fallback_allowed=True,
                    cause=exc,
                )
            except httpx.HTTPError as exc:
                last_error = OpenCodeServerError(
                    f"error de red: {type(exc).__name__}",
                    retryable=True,
                    fallback_allowed=True,
                    cause=exc,
                )
            else:
                if response.status_code >= 400:
                    last_error = self._error_from_response(response)
                else:
                    try:
                        data = response.json()
                    except (json.JSONDecodeError, ValueError) as exc:
                        last_error = OpenCodeResponseError(
                            "la respuesta HTTP no es JSON",
                            status_code=response.status_code,
                            retryable=True,
                            fallback_allowed=True,
                            cause=exc,
                        )
                    else:
                        if not isinstance(data, Mapping):
                            last_error = OpenCodeResponseError(
                                "la respuesta JSON no es un objeto",
                                status_code=response.status_code,
                                retryable=True,
                                fallback_allowed=True,
                            )
                        else:
                            try:
                                return parse(data, response.headers)
                            except ValidationError as exc:
                                details = exc.errors()[:2]
                                last_error = OpenCodeResponseError(
                                    f"la respuesta no cumple el esquema: {details}",
                                    status_code=response.status_code,
                                    retryable=True,
                                    fallback_allowed=True,
                                    cause=exc,
                                )
                            except (ValueError, KeyError, TypeError) as exc:
                                last_error = OpenCodeResponseError(
                                    f"respuesta inválida: {exc}",
                                    status_code=response.status_code,
                                    retryable=True,
                                    fallback_allowed=True,
                                    cause=exc,
                                )

            assert last_error is not None
            if not last_error.retryable or attempt >= self.max_retries:
                raise last_error
            self._sleep(self.backoff_base * (2 ** attempt))

        assert last_error is not None
        raise last_error

    # -- llamadas por familia de API -------------------------------------

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]] | Mapping[str, Any],
        *,
        model: str | None = None,
        schema: type[BaseModel] | Mapping[str, Any] | None = None,
        session_id: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        """Chat Completions con JSON Schema opcional y validación Pydantic."""
        target_model = model or self.model
        schema_name, json_schema, model_cls = _schema_info(schema)
        normalized_messages = (
            [messages] if isinstance(messages, Mapping) else list(messages)
        )

        payload: dict[str, Any] = {
            "model": target_model,
            "messages": _jsonable(normalized_messages),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": self.strict_schema,
                    "schema": json_schema,
                },
            }
        if extra_body:
            payload.update(_jsonable_mapping(extra_body))

        def parse(
            data: Mapping[str, Any], headers: httpx.Headers
        ) -> LLMResult:
            text = _extract_chat_text(data)
            parsed = (
                _validate_parsed(parse_json_text(text), model_cls)
                if json_schema is not None
                else None
            )
            usage, allowance = _usage_and_allowance(data, headers)
            return LLMResult(
                text=text,
                parsed=parsed,
                usage=usage,
                allowance=allowance,
                model=str(data.get("model") or target_model),
                api="chat",
                raw=dict(data),
            )

        return self._post(
            "/openai/v1/chat/completions",
            payload,
            session_id=session_id,
            parse=parse,
        )

    def responses(
        self,
        input: Any,
        *,
        model: str | None = None,
        schema: type[BaseModel] | Mapping[str, Any] | None = None,
        session_id: str | None = None,
        temperature: float | None = None,
        max_output_tokens: int | None = None,
        extra_body: Mapping[str, Any] | None = None,
    ) -> LLMResult:
        """Responses API (GPT-6 Luna) con ``text.format`` JSON Schema."""
        target_model = model or self.model
        schema_name, json_schema, model_cls = _schema_info(schema)

        payload: dict[str, Any] = {
            "model": target_model,
            "input": _jsonable(input),
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_output_tokens is not None:
            payload["max_output_tokens"] = max_output_tokens
        if json_schema is not None:
            payload["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": self.strict_schema,
                    "schema": json_schema,
                }
            }
        if extra_body:
            payload.update(_jsonable_mapping(extra_body))

        def parse(
            data: Mapping[str, Any], headers: httpx.Headers
        ) -> LLMResult:
            text = _extract_responses_text(data)
            parsed = (
                _validate_parsed(parse_json_text(text), model_cls)
                if json_schema is not None
                else None
            )
            usage, allowance = _usage_and_allowance(data, headers)
            return LLMResult(
                text=text,
                parsed=parsed,
                usage=usage,
                allowance=allowance,
                model=str(data.get("model") or target_model),
                api="responses",
                raw=dict(data),
            )

        return self._post(
            "/openai/v1/responses",
            payload,
            session_id=session_id,
            parse=parse,
        )

    def anthropic(
        self,
        model: str | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
        *,
        schema: type[BaseModel] | Mapping[str, Any] | None = None,
        session_id: str | None = None,
        max_tokens: int = 1024,
    ) -> LLMResult:
        """Stub tipado para ``/anthropic/v1/messages`` (Claude Haiku 5.5)."""
        raise NotImplementedError(
            "La familia Anthropic de OpenCode Go se implementará en F4; "
            "usa un modelo Chat/Responses mientras tanto"
        )

    def google(
        self,
        model: str | None = None,
        contents: Any = None,
        *,
        schema: type[BaseModel] | Mapping[str, Any] | None = None,
        session_id: str | None = None,
    ) -> LLMResult:
        """Stub tipado para Gemini ``:generateContent``."""
        raise NotImplementedError(
            "La familia Google de OpenCode Go se implementará en F4; "
            "usa un modelo Chat/Responses mientras tanto"
        )

    # -- orquestación de fallback ----------------------------------------

    def _call_model(
        self,
        model: str,
        *,
        messages: Sequence[Mapping[str, Any]] | None,
        input: Any,
        schema: type[BaseModel] | Mapping[str, Any] | None,
        session_id: str | None,
        api: str | None,
        temperature: float | None,
        max_tokens: int | None,
    ) -> LLMResult:
        family = api or api_family_for_model(model, self.api_families)
        if family == "chat":
            chat_messages = (
                list(messages)
                if messages is not None
                else _input_to_messages(input)
            )
            return self.chat(
                chat_messages,
                model=model,
                schema=schema,
                session_id=session_id,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        if family == "responses":
            responses_input = input if input is not None else list(messages or [])
            return self.responses(
                responses_input,
                model=model,
                schema=schema,
                session_id=session_id,
                temperature=temperature,
                max_output_tokens=max_tokens,
            )
        raise OpenCodeModelError(
            f"familia de API '{family}' no implementada para '{model}'",
            fallback_allowed=True,
        )

    def complete(
        self,
        *,
        messages: Sequence[Mapping[str, Any]] | None = None,
        input: Any = None,
        schema: type[BaseModel] | Mapping[str, Any] | None = None,
        model: str | None = None,
        fallback_models: Sequence[str] | None = None,
        session_id: str | None = None,
        api: str | None = None,
        temperature: float | None = 0.0,
        max_tokens: int | None = None,
    ) -> LLMResult:
        """Llama al modelo principal y aplica la cadena de fallback si hace falta.

        El fallback solo se activa con errores recuperables
        (``error.fallback_allowed``) o cuando el allowance restante cae por
        debajo de ``min_allowance_ratio``. Un 401/400 nunca dispara fallback.
        """
        if messages is None and input is None:
            raise ValueError("complete requiere 'messages' o 'input'")
        if isinstance(messages, Mapping):
            messages = [messages]

        primary = model or self.model
        if fallback_models is None:
            candidates = [primary, *self.fallback_models]
        else:
            candidates = [primary, *fallback_models]

        ordered: list[str] = []
        for candidate in candidates:
            if candidate and candidate not in ordered:
                ordered.append(candidate)
        if not ordered:
            raise ValueError("no hay modelos candidatos")

        attempted: list[str] = []
        last_error: OpenCodeGoError | None = None
        last_success: LLMResult | None = None

        for index, candidate in enumerate(ordered):
            has_next = index < len(ordered) - 1
            try:
                result = self._call_model(
                    candidate,
                    messages=messages,
                    input=input,
                    schema=schema,
                    session_id=session_id,
                    api=api,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except OpenCodeGoError as exc:
                attempted.append(candidate)
                last_error = exc
                if exc.fallback_allowed and has_next:
                    continue
                if last_success is not None and exc.fallback_allowed:
                    # Ya había una respuesta válida (p. ej. con allowance bajo):
                    # si el fallback falla de forma recuperable, conservamos la
                    # respuesta original. Un 401/400 sí debe aflorar.
                    last_success.attempted_models = list(attempted)
                    return last_success
                raise

            result.fallback_used = index > 0
            result.attempted_models = [*attempted, candidate]
            last_success = result

            if result.allowance.is_low(self.min_allowance_ratio) and has_next:
                attempted.append(candidate)
                continue
            return result

        if last_success is not None:
            last_success.attempted_models = list(attempted) or [
                last_success.model
            ]
            return last_success
        if last_error is not None:
            raise last_error
        raise OpenCodeResponseError("sin respuesta de ningún modelo candidato")


__all__ = [
    "DEFAULT_BASE_URL",
    "DEFAULT_FALLBACK_MODELS",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT",
    "OpenCodeAuthError",
    "OpenCodeGoClient",
    "OpenCodeGoError",
    "OpenCodeModelError",
    "OpenCodeQuotaError",
    "OpenCodeRateLimitError",
    "OpenCodeResponseError",
    "OpenCodeServerError",
    "api_family_for_model",
    "parse_json_text",
]
