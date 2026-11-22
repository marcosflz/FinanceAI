"""Contexto del turno en curso, visible para las herramientas (``to_thread`` copia el contexto)."""

from __future__ import annotations

from contextvars import ContextVar

current_thread: ContextVar[int | None] = ContextVar("agent_thread", default=None)
current_run: ContextVar[int | None] = ContextVar("agent_run", default=None)
