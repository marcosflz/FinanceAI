"""Política de herramientas del asistente (adaptada de nexus ``policy.py``).

Se resuelve en proceso, sin llamadas a un BFF:

- lectura y presentación → ``allow``;
- escritura → ``ask``: se registra la auditoría y la aprobación **antes** de
  detener el run, y el usuario decide en una tarjeta;
- cualquier otra herramienta → ``deny`` (sin regla = denegado).

Un bot programado usa la misma política: sus escrituras quedan pendientes y
se notifica al usuario.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from nas.adk.core.callbacks import BaseCallback
from nas.adk.core.interrupts import ToolDecision

from ..db.session import _session
from ..models import AgentApproval, AgentAudit
from . import tools as finance_tools


def decide(tool_name: str) -> str:
    if tool_name in finance_tools.READ_NAMES:
        return "allow"
    if tool_name in finance_tools.WRITE_NAMES:
        return "ask"
    return "deny"


def audit(run_id: int | None, tool: str, args: dict[str, Any], decision: str, detail: str | None = None) -> None:
    with _session() as s:
        s.add(
            AgentAudit(
                run_id=run_id,
                tool=tool,
                args_json=json.dumps(args, ensure_ascii=False, default=str),
                decision=decision,
                detail=(detail or None) and detail[:4000],
                created_at=datetime.utcnow(),
            )
        )


def _register_approval(
    thread_id: int, run_id: int, call_id: str, tool: str, args: dict[str, Any]
) -> dict[str, Any]:
    try:
        preview = finance_tools.preview(tool, args)
    except Exception:  # la vista previa nunca bloquea la aprobación
        preview = {"kind": "simple"}
    audit(run_id, tool, args, "ask")
    with _session() as s:
        approval = AgentApproval(
            thread_id=thread_id,
            run_id=run_id,
            call_id=call_id,
            tool=tool,
            args_json=json.dumps(args, ensure_ascii=False, default=str),
            preview_json=json.dumps(preview, ensure_ascii=False, default=str),
            status="pending",
            created_at=datetime.utcnow(),
        )
        s.add(approval)
        s.flush()
        return {"approval_id": approval.id, "tool": tool, "args": args, "preview": preview}


class PolicyCallback(BaseCallback):
    def __init__(self, *, thread_id: int, run_id: int) -> None:
        self.thread_id = thread_id
        self.run_id = run_id

    async def before_tool_call(
        self, tool_name: str, args: dict[str, Any], tool_call_id: str = "", **_: Any
    ) -> ToolDecision | None:
        decision = decide(tool_name)
        if decision == "allow":
            return None
        if decision == "deny":
            await asyncio.to_thread(audit, self.run_id, tool_name, args, "deny", "Sin regla")
            return ToolDecision.deny(f"La herramienta {tool_name} no está permitida")
        payload = await asyncio.to_thread(
            _register_approval, self.thread_id, self.run_id, tool_call_id, tool_name, args
        )
        return ToolDecision.interrupt("approval", payload)
