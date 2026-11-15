"""API v3 del asistente de IA y de las automatizaciones.

Todo vive en la BD del tenant del usuario autenticado. Los turnos se emiten
como Server-Sent Events (``text/event-stream``) vía ``POST`` (el frontend usa
``fetch`` + stream porque necesita la cabecera CSRF).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent import bots as bot_ops
from .agent import hub, links
from .agent.providers import catalog_payload, fake_enabled, get_provider, key_hint
from .agent.runtime import AgentConfigError, Decision, approval_payload, run_turn
from .auth.dependencies import require_csrf, require_user
from .db.session import _session
from .models import (
    AgentApproval,
    AgentRun,
    AiProvider,
    Bot,
    ChatMessage,
    ChatThread,
    Notification,
)

router = APIRouter(
    prefix="/api/v3",
    tags=["v3-agent"],
    dependencies=[Depends(require_user), Depends(require_csrf)],
)

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


# ── Proveedores de IA del usuario ────────────────────────────────────────────


class ProviderUpdate(BaseModel):
    api_key: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    is_default: bool | None = None


def _provider_payload(row: AiProvider) -> dict[str, Any]:
    info = get_provider(row.provider)
    return {
        "provider": row.provider,
        "label": info.label,
        "model": row.model,
        "enabled": bool(row.enabled),
        "is_default": bool(row.is_default),
        "has_key": bool(row.api_key),
        "key_hint": key_hint(row.api_key, row.provider),
        "kind": info.kind,
        "link": info.link,
        "updated_at": row.updated_at,
    }


@router.get("/ai/catalog")
def ai_catalog() -> dict:
    return {"items": catalog_payload(), "fake": fake_enabled()}


@router.get("/ai/providers")
def list_ai_providers() -> dict:
    with _session() as s:
        rows = s.query(AiProvider).order_by(AiProvider.provider).all()
        return {"items": [_provider_payload(r) for r in rows if r.provider in _known()]}


def _known() -> set[str]:
    return {item["id"] for item in catalog_payload()}


@router.put("/ai/providers/{provider_id}")
def upsert_ai_provider(provider_id: str, body: ProviderUpdate) -> dict:
    try:
        info = get_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    with _session() as s:
        row = s.query(AiProvider).filter_by(provider=provider_id).first()
        if row is None:
            row = AiProvider(provider=provider_id, created_at=datetime.utcnow())
            s.add(row)
        if body.api_key is not None:
            if info.link == "chatgpt":
                raise HTTPException(400, "ChatGPT se vincula con «Sign in with ChatGPT»")
            row.api_key = body.api_key.strip() or None
        if body.model is not None:
            row.model = body.model.strip() or None
        if body.enabled is not None:
            row.enabled = body.enabled
        if info.requires_key and not row.api_key:
            raise HTTPException(422, f"{info.label} necesita una API key")
        others = s.query(AiProvider).filter(AiProvider.provider != provider_id).all()
        if body.is_default or not any(o.is_default for o in others):
            for other in others:
                other.is_default = False
            row.is_default = True
        row.updated_at = datetime.utcnow()
        s.flush()
        return _provider_payload(row)


class LinkFinish(BaseModel):
    link_id: str = Field(min_length=8, max_length=200)
    code: str | None = Field(default=None, max_length=2000)
    redirect_url: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=120)


class LinkCancel(BaseModel):
    link_id: str = Field(min_length=8, max_length=200)


def _link_owner() -> str:
    from .db.tenant import current_tenant

    ctx = current_tenant()
    if ctx is None:
        raise HTTPException(401, "No autenticado")
    return f"{ctx.tenant_id}:{ctx.user_id}"


def _subscription(provider_id: str):
    try:
        info = get_provider(provider_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    if info.link == "key":
        raise HTTPException(400, f"{info.label} se configura con una API key")
    return info


@router.post("/ai/providers/{provider_id}/link/start")
async def start_link(provider_id: str) -> dict:
    """Inicia la vinculación de una suscripción personal: devuelve la URL a abrir."""
    info = _subscription(provider_id)
    owner = _link_owner()
    try:
        if info.link == "claude":
            link_id, url = await links.start_claude(owner)
        else:
            link_id, url = await links.start_chatgpt(owner)
    except links.LinkError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    return {"link_id": link_id, "url": url}


def _save_secret(provider_id: str, secret: str, model: str | None) -> dict:
    with _session() as s:
        row = s.query(AiProvider).filter_by(provider=provider_id).first()
        if row is None:
            row = AiProvider(provider=provider_id, created_at=datetime.utcnow())
            s.add(row)
        row.api_key = secret
        if model:
            row.model = model
        row.enabled = True
        others = s.query(AiProvider).filter(AiProvider.provider != provider_id).all()
        if not any(o.is_default for o in others):
            row.is_default = True
        row.updated_at = datetime.utcnow()
        s.flush()
        return _provider_payload(row)


@router.post("/ai/providers/{provider_id}/link/finish")
async def finish_link(provider_id: str, body: LinkFinish) -> dict:
    """Completa la vinculación: el token queda en la BD cifrada del usuario."""
    info = _subscription(provider_id)
    owner = _link_owner()
    models: list[str] = []
    try:
        if info.link == "claude":
            if not body.code:
                raise HTTPException(422, "Pega el código que te muestra Anthropic")
            secret = await links.finish_claude(body.link_id, owner, body.code.strip())
            model = body.model or "default"
        else:
            if not body.redirect_url:
                raise HTTPException(422, "Pega la dirección completa de la redirección")
            secret, models = await links.finish_chatgpt(body.link_id, owner, body.redirect_url.strip())
            model = body.model or (models[0] if models else None)
    except links.LinkError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    payload = await asyncio.to_thread(_save_secret, provider_id, secret, model)
    return {**payload, "models": models}


@router.post("/ai/providers/{provider_id}/link/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_link(provider_id: str, body: LinkCancel) -> None:
    _subscription(provider_id)
    await links.cancel(body.link_id, _link_owner())


@router.get("/ai/providers/chatgpt/models")
async def chatgpt_models() -> dict:
    """Modelos disponibles en el plan de ChatGPT vinculado (consulta en vivo)."""
    from nas.adk.models.chatgpt import oauth
    from nas.adk.models.errors import LlmError

    from .agent.providers import refresh_secret

    def load() -> str | None:
        with _session() as s:
            row = s.query(AiProvider).filter_by(provider="chatgpt").first()
            return row.api_key if row else None

    secret = await asyncio.to_thread(load)
    if not secret:
        raise HTTPException(404, "ChatGPT no está vinculado")
    try:
        renewed = await refresh_secret("chatgpt", secret)
        if renewed:
            await asyncio.to_thread(_save_secret, "chatgpt", renewed, None)
            secret = renewed
        creds = oauth.ChatGptCredentials.from_json(secret)
        items = await oauth.list_models(creds.access_token)
    except LlmError as exc:
        raise HTTPException(503, "No se pudo consultar ChatGPT; vuelve a vincular la cuenta") from exc
    return {"items": [m["id"] for m in items if m.get("id")]}


@router.delete("/ai/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ai_provider(provider_id: str) -> None:
    with _session() as s:
        row = s.query(AiProvider).filter_by(provider=provider_id).first()
        if row is None:
            raise HTTPException(404, "Proveedor no configurado")
        was_default = row.is_default
        s.delete(row)
        s.flush()
        if was_default:
            other = s.query(AiProvider).filter(AiProvider.enabled.is_(True)).first()
            if other is not None:
                other.is_default = True


# ── Conversaciones ───────────────────────────────────────────────────────────


class ThreadCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    provider: str | None = None
    model: str | None = None


class DecisionIn(BaseModel):
    call_id: str
    approved: bool
    selected_ids: list[int] | None = None
    reason: str = Field(default="", max_length=500)


class ResumeRequest(BaseModel):
    decisions: list[DecisionIn] = Field(min_length=1)


def _thread_payload(t: ChatThread) -> dict[str, Any]:
    return {
        "id": t.id,
        "title": t.title,
        "origin": t.origin,
        "bot_id": t.bot_id,
        "provider": t.provider,
        "model": t.model,
        "status": t.status,
        "created_at": t.created_at,
        "updated_at": t.updated_at,
    }


def _message_payload(m: ChatMessage) -> dict[str, Any]:
    return {
        "id": m.id,
        "role": m.role,
        "content": m.content,
        "parts": json.loads(m.parts_json) if m.parts_json else [],
        "run_id": m.run_id,
        "created_at": m.created_at,
    }


@router.get("/agent/threads")
def list_threads(origin: Literal["chat", "routine", "all"] = Query(default="all")) -> dict:
    with _session() as s:
        query = s.query(ChatThread)
        if origin != "all":
            query = query.filter(ChatThread.origin == origin)
        rows = query.order_by(ChatThread.updated_at.desc()).limit(200).all()
        return {"items": [_thread_payload(t) for t in rows]}


@router.post("/agent/threads", status_code=201)
def create_thread(body: ThreadCreate) -> dict:
    with _session() as s:
        thread = ChatThread(
            title=(body.title or "").strip() or "Nueva conversación",
            origin="chat",
            status="idle",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        s.add(thread)
        s.flush()
        return _thread_payload(thread)


def _heal_thread(s, thread: ChatThread) -> None:
    """Un turno interrumpido por un reinicio no debe bloquear el hilo."""
    if thread.status != "running" or hub.thread_is_live(thread.id):
        return
    pending = (
        s.query(AgentApproval)
        .filter(AgentApproval.thread_id == thread.id, AgentApproval.status == "pending")
        .count()
    )
    thread.status = "awaiting_approval" if pending else "idle"
    for run in s.query(AgentRun).filter_by(thread_id=thread.id, status="running"):
        run.status = "cancelled"
        run.finished_at = datetime.utcnow()


@router.get("/agent/threads/{thread_id}")
def get_thread(thread_id: int) -> dict:
    with _session() as s:
        thread = s.query(ChatThread).filter_by(id=thread_id).first()
        if thread is None:
            raise HTTPException(404, "Conversación no encontrada")
        _heal_thread(s, thread)
        messages = (
            s.query(ChatMessage)
            .filter_by(thread_id=thread_id)
            .order_by(ChatMessage.id)
            .all()
        )
        approvals = (
            s.query(AgentApproval)
            .filter_by(thread_id=thread_id, status="pending")
            .order_by(AgentApproval.id)
            .all()
        )
        active = (
            s.query(AgentRun)
            .filter_by(thread_id=thread_id, status="running")
            .order_by(AgentRun.id.desc())
            .first()
        )
        return {
            "thread": _thread_payload(thread),
            "messages": [_message_payload(m) for m in messages],
            "pending_approvals": [approval_payload(a) for a in approvals],
            "active_run_id": active.id if active else None,
        }


@router.delete("/agent/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_thread(thread_id: int) -> None:
    with _session() as s:
        thread = s.query(ChatThread).filter_by(id=thread_id).first()
        if thread is None:
            raise HTTPException(404, "Conversación no encontrada")
        if hub.thread_is_live(thread_id):
            raise HTTPException(409, "La conversación tiene un turno en curso")
        s.delete(thread)


def _prepare_turn(thread_id: int) -> None:
    with _session() as s:
        thread = s.query(ChatThread).filter_by(id=thread_id).first()
        if thread is None:
            raise HTTPException(404, "Conversación no encontrada")
        _heal_thread(s, thread)


async def _stream(turn) -> StreamingResponse:
    try:
        run_id = await hub.start(turn)
    except AgentConfigError as exc:
        raise HTTPException(409, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc

    async def body():
        async for event in hub.follow(run_id, 0):
            yield hub.sse(event)

    return StreamingResponse(body(), media_type="text/event-stream", headers=_SSE_HEADERS)


@router.post("/agent/threads/{thread_id}/messages")
async def post_message(thread_id: int, body: MessageCreate) -> StreamingResponse:
    await asyncio.to_thread(_prepare_turn, thread_id)
    return await _stream(
        run_turn(thread_id, message=body.message, provider=body.provider, model_name=body.model)
    )


@router.post("/agent/threads/{thread_id}/resume")
async def resume_thread(thread_id: int, body: ResumeRequest) -> StreamingResponse:
    await asyncio.to_thread(_prepare_turn, thread_id)
    decisions = [
        Decision(
            call_id=d.call_id,
            approved=d.approved,
            selected_ids=d.selected_ids,
            reason=d.reason,
        )
        for d in body.decisions
    ]
    return await _stream(run_turn(thread_id, decisions=decisions))


@router.get("/agent/runs/{run_id}/events")
async def run_events(run_id: int, after: int = Query(default=0, ge=0)) -> StreamingResponse:
    async def body():
        try:
            async for event in hub.follow(run_id, after):
                yield hub.sse(event)
        except LookupError:
            return

    return StreamingResponse(body(), media_type="text/event-stream", headers=_SSE_HEADERS)


# ── Automatizaciones ─────────────────────────────────────────────────────────


class BotCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=4000)
    cron: str = Field(min_length=9, max_length=120)
    timezone: str = "Europe/Madrid"
    template: str | None = None
    enabled: bool = True
    provider: str | None = None
    model: str | None = None


class BotUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    prompt: str | None = Field(default=None, max_length=4000)
    cron: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    enabled: bool | None = None
    provider: str | None = None
    model: str | None = None


@router.get("/agent/bots/templates")
def bot_templates() -> dict:
    return {"items": [{"id": key, **value} for key, value in bot_ops.TEMPLATES.items()]}


@router.get("/agent/bots")
def list_bots() -> dict:
    with _session() as s:
        return {"items": [bot_ops.bot_payload(b) for b in s.query(Bot).order_by(Bot.id)]}


@router.post("/agent/bots", status_code=201)
def create_bot(body: BotCreate) -> dict:
    try:
        bot_ops.validate_cron(body.cron, body.timezone)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with _session() as s:
        bot = Bot(
            name=body.name.strip(),
            prompt=body.prompt.strip(),
            cron=body.cron.strip(),
            timezone=body.timezone,
            template=body.template,
            enabled=body.enabled,
            provider=body.provider,
            model=body.model,
            next_run_at=bot_ops.next_run(body.cron, body.timezone) if body.enabled else None,
            created_at=datetime.utcnow(),
        )
        s.add(bot)
        s.flush()
        payload = bot_ops.bot_payload(bot)
        s.expunge(bot)
    bot_ops.schedule(bot)
    return payload


@router.patch("/agent/bots/{bot_id}")
def update_bot(bot_id: int, body: BotUpdate) -> dict:
    with _session() as s:
        bot = s.query(Bot).filter_by(id=bot_id).first()
        if bot is None:
            raise HTTPException(404, "Automatización no encontrada")
        for field in ("name", "prompt", "provider", "model", "enabled"):
            value = getattr(body, field)
            if value is not None:
                setattr(bot, field, value.strip() if isinstance(value, str) else value)
        if body.cron is not None:
            bot.cron = body.cron.strip()
        if body.timezone is not None:
            bot.timezone = body.timezone
        try:
            bot_ops.validate_cron(bot.cron, bot.timezone)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        bot.next_run_at = bot_ops.next_run(bot.cron, bot.timezone) if bot.enabled else None
        bot.updated_at = datetime.utcnow()
        s.flush()
        payload = bot_ops.bot_payload(bot)
        s.expunge(bot)
    bot_ops.schedule(bot)
    return payload


@router.delete("/agent/bots/{bot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_bot(bot_id: int) -> None:
    with _session() as s:
        bot = s.query(Bot).filter_by(id=bot_id).first()
        if bot is None:
            raise HTTPException(404, "Automatización no encontrada")
        s.delete(bot)
    bot_ops.unschedule(bot_id)


@router.post("/agent/bots/{bot_id}/run")
async def run_bot_now(bot_id: int) -> dict:
    """Ejecuta ahora (en la petición, con tu sesión) sin mover la programación."""
    result = await bot_ops.execute_bot(bot_id, reschedule=False)
    if result.get("status") == "missing":
        raise HTTPException(404, "Automatización no encontrada")
    return result


# ── Notificaciones ───────────────────────────────────────────────────────────


def _notification_payload(n: Notification) -> dict[str, Any]:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "thread_id": n.thread_id,
        "bot_id": n.bot_id,
        "read": n.read_at is not None,
        "created_at": n.created_at,
    }


@router.get("/agent/notifications")
def list_notifications(unread: bool = Query(default=False)) -> dict:
    with _session() as s:
        query = s.query(Notification)
        if unread:
            query = query.filter(Notification.read_at.is_(None))
        rows = query.order_by(Notification.id.desc()).limit(50).all()
        unread_count = s.query(Notification).filter(Notification.read_at.is_(None)).count()
        return {"items": [_notification_payload(n) for n in rows], "unread": unread_count}


@router.post("/agent/notifications/read")
def mark_notifications_read(ids: list[int] | None = None) -> dict:
    with _session() as s:
        query = s.query(Notification).filter(Notification.read_at.is_(None))
        if ids:
            query = query.filter(Notification.id.in_(ids))
        count = 0
        for n in query:
            n.read_at = datetime.utcnow()
            count += 1
        return {"updated": count}
