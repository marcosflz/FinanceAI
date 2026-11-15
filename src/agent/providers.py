"""Catálogo de proveedores de IA y construcción del modelo nas-adk por usuario.

Adaptado de SLAnything (``webapp/authoring/providers.py`` y
``generation/models.py``). Diferencias:

- Las credenciales viven en la tabla ``ai_providers`` del SQLite del usuario
  (cifrado con su DEK): no hace falta una clave de servidor para envolverlas.
- Solo proveedores con URL fija: un usuario no puede apuntar el servidor a un
  host arbitrario (SSRF). Los endpoints locales (Ollama, LM Studio) quedan
  fuera.
- Suscripciones personales (Claude Pro/Max vía CLI de Claude Code, plan de
  ChatGPT vía «Sign in with ChatGPT»): el token es de cada usuario, vive en su
  BD y solo se usa en sus propias ejecuciones. El CLI de Claude recibe además un
  ``CLAUDE_CONFIG_DIR`` propio del usuario.
- ``ModelRouter`` recibe siempre ``provider``, ``base_url`` y ``api_key``
  explícitos para no heredar nada del entorno del servidor.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal

from nas.adk.models.base_llm import (
    BaseLlm,
    LlmRequest,
    LlmResponse,
    ModelCapabilities,
    ToolCall,
)


@dataclass(frozen=True)
class Provider:
    id: str
    label: str
    adk_provider: str
    base_url: str | None
    models: tuple[str, ...]
    notes: str
    requires_key: bool = True
    kind: Literal["api", "subscription"] = "api"
    # Cómo se conecta: clave pegada o vinculación de cuenta.
    link: Literal["key", "claude", "chatgpt"] = "key"


PROVIDERS: tuple[Provider, ...] = (
    Provider(
        id="opencode-go",
        label="OpenCode Go",
        adk_provider="opencode",
        base_url="https://opencode.ai/inference/go",
        models=("deepseek-v4.1-flash", "glm-5.3", "glm-5.3-flash", "kimi-k3", "mimo-v2.6-flash"),
        notes="Suscripción de OpenCode Go. Pega la API key del Console de OpenCode.",
        kind="subscription",
    ),
    Provider(
        id="claude-code",
        label="Claude · mi suscripción (Pro/Max)",
        adk_provider="claude-code",
        base_url=None,
        models=("default", "sonnet", "opus", "haiku"),
        notes=(
            "Tu suscripción personal de Claude a través del CLI oficial de Claude Code. "
            "Vincúlala desde aquí o pega el token de `claude setup-token`. Solo se usa en "
            "tus conversaciones y automatizaciones."
        ),
        kind="subscription",
        link="claude",
    ),
    Provider(
        id="chatgpt",
        label="ChatGPT · mi plan (Plus/Pro)",
        adk_provider="chatgpt",
        base_url=None,
        models=(),
        notes=(
            "Tu plan de ChatGPT con «Sign in with ChatGPT» (vía oficial de OpenAI para apps "
            "de terceros). Solo se usa en tus conversaciones y automatizaciones."
        ),
        kind="subscription",
        link="chatgpt",
    ),
    Provider(
        id="anthropic",
        label="Anthropic (API)",
        adk_provider="anthropic",
        base_url=None,
        models=("claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"),
        notes="API key de console.anthropic.com (facturación por uso).",
    ),
    Provider(
        id="openrouter",
        label="OpenRouter",
        adk_provider="openrouter",
        base_url="https://openrouter.ai/api/v1",
        models=("anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol", "google/gemini-4-argon"),
        notes="Un solo proveedor para cientos de modelos; usa el ID completo del modelo.",
    ),
    Provider(
        id="openai",
        label="OpenAI",
        adk_provider="openai-compatible",
        base_url="https://api.openai.com/v1",
        models=("gpt-6.1-sol", "gpt-6-luna", "gpt-5.6-luna"),
        notes="API key de platform.openai.com.",
    ),
    Provider(
        id="google",
        label="Google Gemini",
        adk_provider="openai-compatible",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        models=("gemini-4-argon", "gemini-3-pro"),
        notes="API key de Google AI Studio (endpoint compatible con OpenAI).",
    ),
    Provider(
        id="deepseek",
        label="DeepSeek",
        adk_provider="openai-compatible",
        base_url="https://api.deepseek.com/v1",
        models=("deepseek-chat", "deepseek-reasoner"),
        notes="API directa de DeepSeek.",
    ),
)

PROVIDER_MAP = {item.id: item for item in PROVIDERS}


def get_provider(provider_id: str) -> Provider:
    try:
        return PROVIDER_MAP[provider_id]
    except KeyError as exc:
        raise ValueError(f"Proveedor desconocido: {provider_id!r}") from exc


def catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": item.id,
            "label": item.label,
            "models": list(item.models),
            "notes": item.notes,
            "requires_key": item.requires_key,
            "kind": item.kind,
            "link": item.link,
        }
        for item in PROVIDERS
    ]


def key_hint(api_key: str | None, provider_id: str | None = None) -> str | None:
    if not api_key:
        return None
    if provider_id == "chatgpt":
        try:
            return json.loads(api_key).get("account") or "ChatGPT"
        except ValueError:
            return "ChatGPT"
    if provider_id == "claude-code":
        return "Claude vinculado"
    return f"…{api_key[-4:]}" if len(api_key) > 8 else "…"


# ── Suscripciones ────────────────────────────────────────────────────────────

CHATGPT_REFRESH_MARGIN_S = 300


def claude_config_dir(owner: str) -> Path:
    """``CLAUDE_CONFIG_DIR`` propio de cada usuario (sin el token: va por entorno)."""
    from ..config import get_settings
    from ..db.tenant import tenant_root

    settings = get_settings()
    if settings.per_user:
        base = tenant_root(owner) / "claude"
    else:
        base = settings.data_dir.parent / "claude" / owner
    base.mkdir(parents=True, exist_ok=True)
    try:
        base.chmod(0o700)
    except OSError:
        pass
    return base


def _owner() -> str:
    from ..db.tenant import current_tenant

    ctx = current_tenant()
    if ctx is None:
        raise ValueError("La suscripción requiere un usuario")
    return ctx.tenant_id if ctx.tenant_id != "single" else f"u{ctx.user_id}"


def _user_transport(extra_env: Mapping[str, str]):
    from nas.adk.models.claude_code import AsyncioProcessTransport

    class UserEnvTransport(AsyncioProcessTransport):
        """Procesos del CLI con el entorno de una sola persona."""

        async def spawn(self, argv: Sequence[str], *, env: Mapping[str, str], cwd: str):
            merged = dict(env)
            merged.update(extra_env)
            return await super().spawn(argv, env=merged, cwd=cwd)

    return UserEnvTransport()


def claude_executable() -> str:
    return os.getenv("CLAUDE_CODE_BIN", "claude")


async def refresh_secret(provider_id: str, secret: str | None) -> str | None:
    """Renueva el token del plan de ChatGPT si caduca pronto. Devuelve el secreto
    nuevo (con el token de refresco rotado) o ``None`` si no ha cambiado."""
    if provider_id != "chatgpt" or not secret:
        return None
    from nas.adk.models.chatgpt import oauth

    creds = oauth.ChatGptCredentials.from_json(secret)
    if not creds.expires_within(CHATGPT_REFRESH_MARGIN_S):
        return None
    renewed = await oauth.refresh(creds)
    return renewed.to_json()


def fake_enabled() -> bool:
    return os.getenv("AGENT_FAKE_LLM", "").strip().lower() in {"1", "true", "yes"}


def build_model(provider_id: str, api_key: str | None, model: str | None) -> BaseLlm:
    """Modelo listo para un ``Runner``. Lanza ``ValueError`` si falta algo."""
    if fake_enabled():
        return EchoFinanceLlm()
    info = get_provider(provider_id)
    key = (api_key or "").strip()
    chosen = (model or "").strip() or (info.models[0] if info.models else "")
    if info.requires_key and not key:
        raise ValueError(
            f"Vuelve a vincular {info.label}" if info.link != "key" else f"Falta la API key de {info.label}"
        )
    if info.link == "claude":
        from nas.adk.models.claude_code import ClaudeCodeLlm

        home = claude_config_dir(_owner())
        return ClaudeCodeLlm(
            model="" if chosen == "default" else chosen,
            oauth_token=key,
            executable=claude_executable(),
            timeout=300.0,
            env_policy="scrub",
            max_concurrency=1,
            transport=_user_transport({"CLAUDE_CONFIG_DIR": str(home), "HOME": str(home)}),
        )
    if info.link == "chatgpt":
        from nas.adk.models.chatgpt import ChatGptPlanLlm, oauth

        creds = oauth.ChatGptCredentials.from_json(key)
        if creds.expires_at <= time.time():
            raise ValueError("La sesión de ChatGPT ha caducado: vuelve a vincular la cuenta")
        if not chosen:
            raise ValueError("Elige un modelo de ChatGPT")
        return ChatGptPlanLlm(model=chosen, access_token=creds.access_token, timeout=180.0)
    if not chosen:
        raise ValueError(f"Falta el modelo de {info.label}")
    if info.adk_provider == "anthropic":
        from nas.adk.models.anthropic import AnthropicLlm

        return AnthropicLlm(api_key=key, model=chosen, base_url="", timeout=180.0)
    from nas.adk.models import ModelRouter

    return ModelRouter(
        provider=info.adk_provider,
        model=chosen,
        api_key=key,
        base_url=info.base_url,
        fallback_models=(),
        timeout=180.0,
        max_retries=2,
    )


class EchoFinanceLlm(BaseLlm):
    """Modelo determinista sin red para desarrollo (``AGENT_FAKE_LLM=1``).

    - «resumen» → llama a ``get_overview`` y luego resume el resultado.
    - «recategoriza N a Categoría» → propone ``recategorize_movements``.
    - Cualquier otra cosa → eco.
    """

    model: str = "fake"
    capabilities: ClassVar[ModelCapabilities | None] = ModelCapabilities(
        tool_calling="native", usage="reported"
    )

    async def generate_content_async(self, request: LlmRequest) -> LlmResponse:
        messages = request.messages
        last = messages[-1] if messages else {}
        usage = {"input_tokens": 10, "output_tokens": 5}
        if last.get("role") == "tool":
            return LlmResponse(content=f"Hecho. Resultado: {last.get('content', '')[:400]}", usage=usage)
        text = str(last.get("content") or "").lower()
        if "resumen" in text:
            return LlmResponse(
                tool_calls=[ToolCall(id="fake-overview", function={"name": "get_overview", "arguments": "{}"})],
                finish_reason="tool_calls",
                usage=usage,
            )
        if text.startswith("recategoriza"):
            parts = text.split()
            try:
                movement_id = int(parts[1])
                category = " ".join(parts[3:]) or "Otros"
            except (IndexError, ValueError):
                return LlmResponse(content="Formato: recategoriza <id> a <categoría>", usage=usage)
            args = {"changes": [{"movement_id": movement_id, "category": category.title()}]}
            return LlmResponse(
                tool_calls=[
                    ToolCall(
                        id=f"fake-recat-{movement_id}",
                        function={"name": "recategorize_movements", "arguments": json.dumps(args)},
                    )
                ],
                finish_reason="tool_calls",
                usage=usage,
            )
        return LlmResponse(content=f"Eco: {last.get('content', '')}", usage=usage)
