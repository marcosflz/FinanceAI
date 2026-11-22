"""Runs en segundo plano desacoplados del SSE.

El turno se ejecuta en una ``asyncio.Task`` propia (que copia el contexto del
tenant al crearse): si el navegador se desconecta, el run sigue y sus eventos
quedan en ``agent_run_events``. El SSE solo *sigue* el run; al reconectar se
reproducen desde la BD con ``after=seq``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from ..db.session import _session
from ..db.tenant import current_tenant
from ..models import AgentRun, AgentRunEvent

TERMINAL = {"RUN_FINISHED", "RUN_ERROR"}


@dataclass
class LiveRun:
    thread_id: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    done: bool = False
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)
    task: asyncio.Task | None = None


_runs: dict[tuple[str, int], LiveRun] = {}


def _key(run_id: int) -> tuple[str, int]:
    ctx = current_tenant()
    return (ctx.tenant_id if ctx is not None else "", run_id)


async def start(turn: AsyncIterator[dict[str, Any]]) -> int:
    """Arranca el turno y devuelve su ``run_id`` cuando el run ya existe."""
    first = await anext(turn)
    run_id = int(first["run_id"])
    live = LiveRun(thread_id=int(first["thread_id"]), events=[first])
    key = _key(run_id)
    _runs[key] = live

    async def publish(event: dict[str, Any]) -> None:
        async with live.changed:
            live.events.append(event)
            live.changed.notify_all()

    async def pump() -> None:
        # La cancelación (``cancel``) siempre se entrega *dentro* del turno, que
        # la convierte en ``RUN_ERROR status=cancelled`` y cierra el run en BD.
        pending_cancel = False
        try:
            while True:
                try:
                    if pending_cancel:
                        pending_cancel = False
                        event = await turn.athrow(asyncio.CancelledError())
                    else:
                        event = await anext(turn)
                except StopAsyncIteration:
                    break
                except asyncio.CancelledError:
                    break
                try:
                    await publish(event)
                except asyncio.CancelledError:
                    pending_cancel = True
                    await publish(event)
        finally:
            async with live.changed:
                live.done = True
                live.changed.notify_all()
            # Los eventos ya están en BD: se libera la memoria poco después.
            await asyncio.sleep(30)
            _runs.pop(key, None)

    live.task = asyncio.create_task(pump())
    return run_id


def cancel(run_id: int) -> bool:
    """Detiene un run en curso de este proceso. ``False`` si no está vivo aquí."""
    live = _runs.get(_key(run_id))
    if live is None or live.done or live.task is None:
        return False
    live.task.cancel()
    return True


def thread_is_live(thread_id: int) -> bool:
    tenant = _key(0)[0]
    return any(
        key[0] == tenant and live.thread_id == thread_id and not live.done
        for key, live in _runs.items()
    )


def _stored_events(run_id: int, after: int) -> tuple[list[dict[str, Any]], bool]:
    with _session() as s:
        run = s.query(AgentRun).filter_by(id=run_id).first()
        if run is None:
            raise LookupError("Run no encontrado")
        rows = (
            s.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run_id, AgentRunEvent.seq > after)
            .order_by(AgentRunEvent.seq)
            .all()
        )
        return [json.loads(r.payload_json) for r in rows], run.status != "running"


async def follow(run_id: int, after: int = 0) -> AsyncIterator[dict[str, Any]]:
    """Eventos con ``seq > after``: en vivo si el run sigue en este proceso."""
    live = _runs.get(_key(run_id))
    if live is None:
        events, _finished = await asyncio.to_thread(_stored_events, run_id, after)
        for event in events:
            yield event
        return
    index = 0
    while True:
        async with live.changed:
            while index >= len(live.events) and not live.done:
                await live.changed.wait()
            batch = live.events[index:]
            index = len(live.events)
            finished = live.done
        for event in batch:
            if event["seq"] > after:
                yield event
        if finished and index >= len(live.events):
            return


def sse(event: dict[str, Any]) -> bytes:
    return f"id: {event.get('seq', '')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n".encode()
