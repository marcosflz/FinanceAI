"""Ejecución de turnos del asistente (patrón de nexus ``run.py``/``executor.ts``).

Cada turno construye ``Agent`` + ``Runner`` de nas-adk con el modelo y la
credencial **del usuario**, siembra un ``InMemorySessionService`` con la
sesión guardada en ``chat_threads.session_json`` (la BD del tenant es la
fuente de verdad) y traduce los eventos a un protocolo sencillo inspirado en
AG-UI. Cada evento se guarda en ``agent_run_events`` antes de emitirse, de modo
que un cliente puede reconectarse y reproducir el run.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from nas.adk import Agent, Runner
from nas.adk.core.interrupts import ResumeEntry
from nas.adk.sessions.in_memory_session_service import InMemorySessionService
from nas.adk.sessions.session import Session as AdkSession
from nas.adk.tools.function_tool import FunctionTool

from ..db.session import _session
from ..models import (
    AgentApproval,
    AgentRun,
    AgentRunEvent,
    AiProvider,
    ChatMessage,
    ChatThread,
)
from . import policy
from . import tools as finance_tools
from .providers import build_model, fake_enabled, refresh_secret

APP_NAME = "financial-tools"
MAX_RESULT_CHARS = 6000

INSTRUCTION = """Eres el gestor financiero personal del usuario dentro de Financial Tools.
Responde en español, de forma concisa y con cifras concretas (formato 1.234,56 €).
Hoy es {today}.

Cómo trabajar:
- Consulta siempre los datos con las herramientas antes de responder; no inventes cifras.
- Los KPIs ya excluyen transferencias internas y compras/ventas de inversión.
- Las herramientas de escritura (recategorizar, editar movimientos, crear reglas o
  categorías) quedan pendientes de que el usuario las apruebe en una tarjeta. Agrupa
  los cambios relacionados en una sola llamada y explica brevemente por qué.
- Si un cambio es denegado, no lo repitas: pregunta qué prefiere el usuario.
- Para comparar periodos o categorías usa ``show_chart`` con los datos obtenidos.
- Las categorías tienen dos niveles: «Raíz › Subcategoría».
{extra}"""


class AgentConfigError(Exception):
    """No hay modelo configurado o la credencial es inválida."""


@dataclass
class Decision:
    call_id: str
    approved: bool
    # Para ``recategorize_movements``: subconjunto de movimientos aceptados.
    selected_ids: list[int] | None = None
    reason: str = ""


@dataclass
class TurnState:
    text: list[str] = field(default_factory=list)
    parts: list[dict[str, Any]] = field(default_factory=list)
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)


# ── Persistencia (síncrona, se llama con asyncio.to_thread) ──────────────────


def _load_thread(thread_id: int) -> dict[str, Any]:
    with _session() as s:
        thread = s.query(ChatThread).filter_by(id=thread_id).first()
        if thread is None:
            raise LookupError("Conversación no encontrada")
        return {
            "id": thread.id,
            "provider": thread.provider,
            "model": thread.model,
            "session_json": thread.session_json,
            "status": thread.status,
            "title": thread.title,
        }


def _resolve_credentials(provider_id: str | None, model: str | None) -> tuple[str, str | None, str | None]:
    if fake_enabled():
        return provider_id or "fake", None, model or "fake"
    with _session() as s:
        query = s.query(AiProvider).filter(AiProvider.enabled.is_(True))
        row = None
        if provider_id:
            row = query.filter(AiProvider.provider == provider_id).first()
        if row is None:
            row = query.filter(AiProvider.is_default.is_(True)).first() or query.first()
        if row is None:
            raise AgentConfigError(
                "Configura un proveedor de IA en Ajustes → Asistente para usar el chat"
            )
        return row.provider, row.api_key, model or row.model


def _store_secret(provider_id: str, secret: str) -> None:
    """Guarda el secreto renovado (el token de refresco de ChatGPT rota)."""
    with _session() as s:
        row = s.query(AiProvider).filter_by(provider=provider_id).first()
        if row is not None:
            row.api_key = secret
            row.updated_at = datetime.utcnow()


def _start_run(thread_id: int, initiator: str, provider: str, model: str | None) -> int:
    with _session() as s:
        run = AgentRun(
            thread_id=thread_id,
            initiator=initiator,
            status="running",
            provider=provider,
            model=model,
            started_at=datetime.utcnow(),
        )
        s.add(run)
        thread = s.query(ChatThread).filter_by(id=thread_id).one()
        thread.status = "running"
        thread.provider, thread.model = provider, model
        thread.updated_at = datetime.utcnow()
        s.flush()
        return run.id


def _store_event(run_id: int, seq: int, event: dict[str, Any]) -> None:
    with _session() as s:
        s.add(
            AgentRunEvent(
                run_id=run_id,
                seq=seq,
                type=event["type"],
                payload_json=json.dumps(event, ensure_ascii=False, default=str),
                created_at=datetime.utcnow(),
            )
        )
        run = s.query(AgentRun).filter_by(id=run_id).one()
        run.last_seq = seq


def _add_user_message(thread_id: int, run_id: int, text: str) -> None:
    with _session() as s:
        s.add(
            ChatMessage(
                thread_id=thread_id, run_id=run_id, role="user", content=text,
                created_at=datetime.utcnow(),
            )
        )
        thread = s.query(ChatThread).filter_by(id=thread_id).one()
        if thread.title in ("", "Nueva conversación"):
            thread.title = text.strip().splitlines()[0][:80] or thread.title


def _finish_run(
    thread_id: int,
    run_id: int,
    status: str,
    session_json: str | None,
    state: TurnState,
    error: str | None,
) -> None:
    with _session() as s:
        run = s.query(AgentRun).filter_by(id=run_id).one()
        run.status = status
        run.error = error
        run.usage_json = json.dumps(state.usage, default=str) if state.usage else None
        run.finished_at = datetime.utcnow()
        thread = s.query(ChatThread).filter_by(id=thread_id).one()
        if session_json is not None:
            thread.session_json = session_json
        thread.status = "awaiting_approval" if status == "interrupted" else "idle"
        thread.updated_at = datetime.utcnow()
        content = "".join(state.text).strip()
        if content or state.parts:
            s.add(
                ChatMessage(
                    thread_id=thread_id,
                    run_id=run_id,
                    role="assistant",
                    content=content or None,
                    parts_json=json.dumps(state.parts, ensure_ascii=False, default=str),
                    created_at=datetime.utcnow(),
                )
            )


def _resolve_decisions(thread_id: int, run_id: int, decisions: list[Decision]) -> list[ResumeEntry]:
    """Marca las aprobaciones y prepara la reanudación de nas-adk.

    - Aprobación total → ``approved`` (nas-adk ejecuta la tool sin volver a
      preguntar a la política).
    - Aprobación parcial de un lote → se ejecuta aquí solo con lo aceptado y
      se entrega como ``resolved``.
    - Denegación → ``denied``.
    """
    entries: list[ResumeEntry] = []
    with _session() as s:
        pending = {
            a.call_id: a
            for a in s.query(AgentApproval)
            .filter(AgentApproval.thread_id == thread_id, AgentApproval.status == "pending")
            .all()
        }
        snapshot = {
            call_id: (a.tool, json.loads(a.args_json)) for call_id, a in pending.items()
        }
    for decision in decisions:
        if decision.call_id not in snapshot:
            raise LookupError(f"No hay ninguna aprobación pendiente para {decision.call_id}")
    for decision in decisions:
        tool, args = snapshot[decision.call_id]
        status = "approved" if decision.approved else "denied"
        with _session() as s:
            approval = (
                s.query(AgentApproval)
                .filter_by(thread_id=thread_id, call_id=decision.call_id, status="pending")
                .one()
            )
            approval.status = status
            approval.decided_at = datetime.utcnow()
        policy.audit(run_id, tool, args, status, decision.reason or None)
        if not decision.approved:
            entries.append(
                ResumeEntry(decision.call_id, "denied", reason=decision.reason or "El usuario lo ha denegado")
            )
            continue
        if decision.selected_ids is not None and tool == "recategorize_movements":
            selected = set(decision.selected_ids)
            chosen = [c for c in args.get("changes", []) if c.get("movement_id") in selected]
            if not chosen:
                entries.append(ResumeEntry(decision.call_id, "denied", reason="Ningún cambio aceptado"))
                continue
            changes = [finance_tools.CategoryChange(**c) for c in chosen]
            result = finance_tools.recategorize_movements(changes=changes)
            result["skipped"] = sorted(
                c.get("movement_id") for c in args.get("changes", []) if c.get("movement_id") not in selected
            )
            policy.audit(run_id, tool, {"changes": chosen}, "executed", json.dumps(result, default=str))
            entries.append(ResumeEntry(decision.call_id, "resolved", payload=result))
            continue
        entries.append(ResumeEntry(decision.call_id, "approved"))
    return entries


def _pending_approvals(thread_id: int) -> list[dict[str, Any]]:
    with _session() as s:
        rows = (
            s.query(AgentApproval)
            .filter(AgentApproval.thread_id == thread_id, AgentApproval.status == "pending")
            .order_by(AgentApproval.id)
            .all()
        )
        return [approval_payload(a) for a in rows]


def approval_payload(a: AgentApproval) -> dict[str, Any]:
    return {
        "id": a.id,
        "call_id": a.call_id,
        "tool": a.tool,
        "args": json.loads(a.args_json),
        "preview": json.loads(a.preview_json) if a.preview_json else None,
        "status": a.status,
        "created_at": a.created_at,
    }


# ── Turno ────────────────────────────────────────────────────────────────────


def _parse_result(text: str | None) -> Any:
    if not text:
        return None
    if len(text) > MAX_RESULT_CHARS:
        return {"truncated": True, "preview": text[:MAX_RESULT_CHARS]}
    try:
        return json.loads(text)
    except ValueError:
        return text


def _build_runner(model: Any, thread_id: int, run_id: int, session_json: str | None, extra: str):
    service = InMemorySessionService()
    session_id = f"thread-{thread_id}"
    if session_json:
        stored = AdkSession.model_validate_json(session_json)
        service._sessions[stored.id] = stored  # siembra la sesión persistida
    else:
        service.create_session(APP_NAME, "owner", session_id)
    agent = Agent(
        name="finance_assistant",
        model=model,
        instruction=INSTRUCTION.format(today=date.today().isoformat(), extra=extra),
        tools=[FunctionTool(fn, parallel_safe=fn in finance_tools.READ_TOOLS) for fn in finance_tools.ALL_TOOLS],
    )
    runner = Runner(
        app_name=APP_NAME,
        agent=agent,
        session_service=service,
        callbacks=[policy.PolicyCallback(thread_id=thread_id, run_id=run_id)],
        max_model_calls=16,
        max_turns=10,
        timeout=240,
        max_tool_result_chars=MAX_RESULT_CHARS,
        max_context_tokens=24000,
    )
    return runner, service, session_id


async def run_turn(
    thread_id: int,
    *,
    message: str | None = None,
    decisions: list[Decision] | None = None,
    initiator: str = "user",
    provider: str | None = None,
    model_name: str | None = None,
    extra_instruction: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Ejecuta un turno y produce eventos ``{"type": …}`` ya persistidos."""
    if (message is None) == (decisions is None):
        raise ValueError("Indica un mensaje o decisiones de aprobación, no ambos")
    thread = await asyncio.to_thread(_load_thread, thread_id)
    if thread["status"] == "running":
        raise RuntimeError("La conversación ya tiene un turno en curso")
    if message is not None and thread["status"] == "awaiting_approval":
        raise RuntimeError("Resuelve antes las aprobaciones pendientes")
    provider_id, api_key, chosen_model = await asyncio.to_thread(
        _resolve_credentials, provider or thread["provider"], model_name or thread["model"]
    )
    try:
        renewed = await refresh_secret(provider_id, api_key)
    except Exception as exc:  # token de refresco revocado/caducado
        raise AgentConfigError(
            "No se pudo renovar la sesión de ChatGPT: vuelve a vincular la cuenta"
        ) from exc
    if renewed:
        api_key = renewed
        await asyncio.to_thread(_store_secret, provider_id, renewed)
    try:
        model = build_model(provider_id, api_key, chosen_model)
    except ValueError as exc:
        raise AgentConfigError(str(exc)) from exc

    run_id = await asyncio.to_thread(_start_run, thread_id, initiator, provider_id, chosen_model)
    seq = 0
    state = TurnState()
    final_status = "error"
    error: str | None = None
    service = None
    session_id = f"thread-{thread_id}"

    async def emit(event: dict[str, Any]) -> dict[str, Any]:
        nonlocal seq
        seq += 1
        event = {"seq": seq, "run_id": run_id, "thread_id": thread_id, **event}
        await asyncio.to_thread(_store_event, run_id, seq, event)
        return event

    try:
        yield await emit({"type": "RUN_STARTED", "initiator": initiator})
        resume = None
        if decisions is not None:
            resume = await asyncio.to_thread(_resolve_decisions, thread_id, run_id, decisions)
        else:
            await asyncio.to_thread(_add_user_message, thread_id, run_id, message or "")

        runner, service, session_id = _build_runner(
            model, thread_id, run_id, thread["session_json"], extra_instruction
        )
        streamed = False
        async for event in runner.run_async(
            "owner", session_id, message=message, stream=True, resume=resume
        ):
            if event.type == "stream" and event.content:
                streamed = True
                state.text.append(event.content)
                yield await emit({"type": "TEXT_DELTA", "delta": event.content})
                continue
            if event.type == "reasoning":
                continue
            if event.role == "assistant" and event.type == "message":
                if event.content and not streamed:
                    state.text.append(event.content)
                    yield await emit({"type": "TEXT_DELTA", "delta": event.content})
                if event.content:
                    state.parts.append({"type": "text", "text": event.content})
                streamed = False
                for call in event.tool_calls:
                    name = call["function"]["name"]
                    try:
                        args = json.loads(call["function"].get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    state.calls[call["id"]] = {"name": name, "args": args}
                    yield await emit(
                        {"type": "TOOL_CALL_START", "call_id": call["id"], "name": name, "args": args}
                    )
                if event.usage:
                    for key, value in event.usage.items():
                        if isinstance(value, int):
                            state.usage[key] = state.usage.get(key, 0) + value
                if event.final:
                    final_status = event.status or "completed"
                continue
            if event.role == "tool":
                call = state.calls.get(event.tool_call_id) or {"name": event.author, "args": {}}
                result = _parse_result(event.content)
                part = {
                    "type": "tool",
                    "call_id": event.tool_call_id,
                    "name": call["name"],
                    "args": call["args"],
                    "result": result,
                }
                state.parts.append(part)
                if call["name"] in finance_tools.WRITE_NAMES:
                    await asyncio.to_thread(
                        policy.audit, run_id, call["name"], call["args"], "executed",
                        (event.content or "")[:4000],
                    )
                yield await emit({**part, "type": "TOOL_CALL_RESULT"})
                continue
            if event.type == "status" and event.final:
                final_status = event.status or "error"
                if final_status == "interrupted":
                    approvals = await asyncio.to_thread(_pending_approvals, thread_id)
                    state.parts.append({"type": "approvals", "items": approvals})
                    yield await emit({"type": "APPROVAL_REQUIRED", "approvals": approvals})
                elif final_status != "completed":
                    error = event.content or final_status
                usage = (event.metrics or {}).get("total_usage")
                if isinstance(usage, dict) and usage:
                    state.usage = usage
        if final_status in {"completed", "interrupted"}:
            yield await emit({"type": "RUN_FINISHED", "status": final_status})
        else:
            yield await emit({"type": "RUN_ERROR", "status": final_status, "message": error or "Error del modelo"})
    except Exception as exc:
        final_status = "error"
        error = f"{type(exc).__name__}: {exc}"
        yield await emit({"type": "RUN_ERROR", "status": "error", "message": str(exc)})
    finally:
        session_json = None
        if service is not None:
            stored = service.get_session(session_id)
            if stored is not None:
                session_json = stored.model_dump_json()
        await asyncio.to_thread(
            _finish_run, thread_id, run_id, final_status, session_json, state, error
        )
        try:
            await model.aclose()
        except Exception:
            pass
