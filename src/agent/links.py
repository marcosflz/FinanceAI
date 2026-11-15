"""Vinculación de suscripciones personales (adaptado de SLAnything ``links.py``).

- **Claude**: ``claude setup-token`` (CLI oficial) en un pseudo-terminal con un
  HOME temporal (``SetupTokenSession`` de nas-adk). El usuario abre la URL,
  autoriza y pega el código; el token se guarda en *su* BD.
- **ChatGPT**: «Sign in with ChatGPT» (OAuth con PKCE). La redirección va a
  ``http://127.0.0.1:1455/…`` (el equipo del navegador): el usuario copia esa
  dirección y la pega.

Las vinculaciones en curso viven en memoria de este proceso, ligadas a su
usuario (tenant), una por persona y tipo, con caducidad.
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any

from ..config import get_settings

TTL_SECONDS = 600.0
MAX_ACTIVE = 20


class LinkError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class _Pending:
    owner: str
    kind: str
    payload: Any
    expires: float


_pending: dict[str, _Pending] = {}
_lock = threading.Lock()


async def _close(item: _Pending) -> None:
    close = getattr(item.payload, "close", None)
    if close is not None:
        try:
            await close()
        except Exception:  # noqa: BLE001 - cerrar es de mejor esfuerzo
            pass


def _expired_locked() -> list[_Pending]:
    now = time.monotonic()
    keys = [k for k, v in _pending.items() if now >= v.expires]
    return [_pending.pop(k) for k in keys]


async def _put(owner: str, kind: str, payload: Any) -> str:
    with _lock:
        stale = _expired_locked()
        mine = [k for k, v in _pending.items() if v.owner == owner and v.kind == kind]
        stale += [_pending.pop(k) for k in mine]
        full = len(_pending) >= MAX_ACTIVE
        link_id = secrets.token_urlsafe(24)
        if not full:
            _pending[link_id] = _Pending(owner, kind, payload, time.monotonic() + TTL_SECONDS)
    for item in stale:
        await _close(item)
    if full:
        await _close(_Pending(owner, kind, payload, 0))
        raise LinkError(429, "Hay demasiadas vinculaciones en curso. Prueba en unos minutos.")
    return link_id


async def _take(link_id: str, owner: str, kind: str) -> _Pending:
    with _lock:
        stale = _expired_locked()
        item = _pending.get(link_id)
        found = item is not None and item.owner == owner and item.kind == kind
        if found:
            del _pending[link_id]
    for old in stale:
        await _close(old)
    if not found or item is None:
        raise LinkError(404, "La vinculación ha caducado. Vuelve a empezar.")
    return item


async def cancel(link_id: str, owner: str) -> None:
    with _lock:
        item = _pending.get(link_id)
        mine = item is not None and item.owner == owner
        if mine:
            del _pending[link_id]
    if mine and item is not None:
        await _close(item)


# ── Claude ───────────────────────────────────────────────────────────────────


async def start_claude(owner: str) -> tuple[str, str]:
    from nas.adk.models.claude_code import SetupTokenSession
    from nas.adk.models.errors import LlmError

    from .providers import claude_executable

    session = SetupTokenSession(executable=claude_executable())
    try:
        url = await session.start()
    except LlmError as exc:
        await session.close()
        raise LinkError(
            503, "No se pudo iniciar la vinculación con Anthropic (¿está instalado el CLI de Claude Code?)."
        ) from exc
    return await _put(owner, "claude", session), url


async def finish_claude(link_id: str, owner: str, code: str) -> str:
    from nas.adk.models.errors import LlmAuthError, LlmError, LlmTimeoutError

    item = await _take(link_id, owner, "claude")
    try:
        return str(await item.payload.submit(code))
    except LlmAuthError as exc:
        raise LinkError(400, "Anthropic no ha aceptado el código: vuelve a empezar.") from exc
    except LlmTimeoutError as exc:
        raise LinkError(408, "La vinculación ha caducado. Vuelve a empezar.") from exc
    except LlmError as exc:
        raise LinkError(503, "Claude Code no respondió al vincular la cuenta.") from exc
    finally:
        await _close(item)


# ── ChatGPT ──────────────────────────────────────────────────────────────────


def chatgpt_host_id() -> str:
    """Identificador opaco de esta instalación para OpenAI (uno por instancia)."""
    from nas.adk.models.chatgpt import oauth

    path = get_settings().data_dir.parent / "chatgpt-host-id"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    except OSError:
        pass
    value = oauth.new_host_id()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return value


async def start_chatgpt(owner: str) -> tuple[str, str]:
    from nas.adk.models.chatgpt import oauth

    pending = oauth.start_login(host_id=chatgpt_host_id(), app_name="Financial Tools")
    return await _put(owner, "chatgpt", pending), pending.url


async def finish_chatgpt(link_id: str, owner: str, redirect_url: str) -> tuple[str, list[str]]:
    """Devuelve ``(credenciales_json, modelos_disponibles)``."""
    from nas.adk.models.chatgpt import oauth
    from nas.adk.models.errors import LlmAuthError, LlmError, LlmPermissionError

    item = await _take(link_id, owner, "chatgpt")
    try:
        creds = await oauth.exchange_code(redirect_url, item.payload)
    except LlmPermissionError as exc:
        raise LinkError(403, "No se activó el uso del plan de ChatGPT, o tu cuenta no puede usarlo.") from exc
    except LlmAuthError as exc:
        raise LinkError(
            400,
            "OpenAI no ha aceptado esa dirección. Copia la dirección completa a la que te lleva "
            "ChatGPT (empieza por http://127.0.0.1:1455/) y vuelve a empezar si ha pasado tiempo.",
        ) from exc
    except LlmError as exc:
        raise LinkError(503, "No se pudo contactar con OpenAI. Inténtalo de nuevo.") from exc
    try:
        models = [m["id"] for m in await oauth.list_models(creds.access_token) if m.get("id")]
    except LlmError:
        models = []
    return creds.to_json(), models

