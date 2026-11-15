"""Automatizaciones programadas («bots», estilo nexbots).

Un bot es un prompt que el asistente ejecuta según un cron. La programación
vive en la cola central (``central_jobs`` con ``kind="bot_run"`` y ``run_at``
= próxima ejecución): la BD central solo sabe *cuándo* toca, no *qué* hace.

El worker reclama el trabajo, abre el tenant con la concesión en RAM, ejecuta
el turno (misma política: las escrituras quedan pendientes de aprobación),
guarda el resultado en un hilo ``origin='routine'``, crea una notificación y
programa la siguiente ejecución. Sin concesión, el trabajo queda
``waiting_unlock`` y se reanuda una vez cuando el usuario vuelve a entrar.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

from ..db.session import _session, central_session
from ..db.tenant import current_tenant
from ..models import Bot, CentralJob, ChatThread, Notification

MIN_INTERVAL = timedelta(minutes=15)

TEMPLATES: dict[str, dict[str, str]] = {
    "cashflow_weekly": {
        "name": "Resumen semanal de flujo de caja",
        "cron": "0 8 * * 1",
        "prompt": (
            "Resume el flujo de caja de los últimos 7 días: ingresos, gastos, neto y las "
            "5 categorías con más gasto, comparando con la semana anterior. Señala cualquier "
            "gasto inusual. Termina con un gráfico de barras por categoría."
        ),
    },
    "pending_review": {
        "name": "Revisión diaria de pendientes",
        "cron": "0 9 * * *",
        "prompt": (
            "Revisa los movimientos pendientes. Para los que tengas claro, propone su "
            "categoría con una sola llamada a recategorize_movements (quedará pendiente de "
            "mi aprobación). Lista los dudosos con una pregunta breve para cada uno."
        ),
    },
    "portfolio_daily": {
        "name": "Análisis diario de cartera",
        "cron": "30 18 * * 1-5",
        "prompt": (
            "Analiza mi cartera: valor total, P&L, posiciones con mayor variación y peso "
            "de cada activo. Indica si alguna posición tiene el coste incompleto. "
            "No des recomendaciones de compra o venta."
        ),
    },
    "monthly_report": {
        "name": "Informe mensual",
        "cron": "0 9 1 * *",
        "prompt": (
            "Prepara el informe del mes pasado: ingresos, gastos, tasa de ahorro, "
            "evolución frente a los 3 meses anteriores y principales comercios. Incluye un "
            "gráfico de línea del neto mensual."
        ),
    },
}


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"Zona horaria desconocida: {name}") from exc


def validate_cron(expr: str, tz: str) -> None:
    if not croniter.is_valid(expr):
        raise ValueError("Expresión cron inválida (formato: min hora día mes día-semana)")
    zone = _zone(tz)
    base = datetime.now(zone)
    it = croniter(expr, base)
    first, second = it.get_next(datetime), it.get_next(datetime)
    if second - first < MIN_INTERVAL:
        raise ValueError("El intervalo mínimo entre ejecuciones es de 15 minutos")


def next_run(expr: str, tz: str, after: datetime | None = None) -> datetime:
    """Próxima ejecución en UTC *naive* (como el resto de timestamps)."""
    zone = _zone(tz)
    base = (after or datetime.utcnow()).replace(tzinfo=UTC).astimezone(zone)
    nxt = croniter(expr, base).get_next(datetime)
    return nxt.astimezone(UTC).replace(tzinfo=None)


def _user_id() -> int:
    ctx = current_tenant()
    if ctx is None:
        raise RuntimeError("Programar un bot requiere tenant")
    return ctx.user_id


def unschedule(bot_id: int, user_id: int | None = None) -> None:
    uid = user_id if user_id is not None else _user_id()
    with central_session() as db:
        db.query(CentralJob).filter(
            CentralJob.user_id == uid,
            CentralJob.kind == "bot_run",
            CentralJob.ref_id == bot_id,
            CentralJob.status.in_(("queued", "waiting_unlock")),
        ).delete(synchronize_session=False)


def schedule(bot: Bot, user_id: int | None = None) -> None:
    """Deja un único trabajo central pendiente con la próxima ejecución."""
    uid = user_id if user_id is not None else _user_id()
    unschedule(bot.id, uid)
    if not bot.enabled or bot.next_run_at is None:
        return
    with central_session() as db:
        db.add(
            CentralJob(
                user_id=uid,
                kind="bot_run",
                ref_id=bot.id,
                status="queued",
                run_at=bot.next_run_at,
                created_at=datetime.utcnow(),
            )
        )


def bot_payload(bot: Bot) -> dict[str, Any]:
    return {
        "id": bot.id,
        "name": bot.name,
        "template": bot.template,
        "prompt": bot.prompt,
        "cron": bot.cron,
        "timezone": bot.timezone,
        "enabled": bool(bot.enabled),
        "provider": bot.provider,
        "model": bot.model,
        "next_run_at": bot.next_run_at,
        "last_run_at": bot.last_run_at,
        "last_status": bot.last_status,
        "last_thread_id": bot.last_thread_id,
        "last_error": bot.last_error,
    }


def _prepare_run(bot_id: int) -> dict[str, Any] | None:
    with _session() as s:
        bot = s.query(Bot).filter_by(id=bot_id).first()
        if bot is None:
            return None
        thread = ChatThread(
            title=f"{bot.name} · {datetime.utcnow():%d/%m %H:%M}",
            origin="routine",
            bot_id=bot.id,
            provider=bot.provider,
            model=bot.model,
            status="idle",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        s.add(thread)
        s.flush()
        return {
            "thread_id": thread.id,
            "prompt": bot.prompt,
            "provider": bot.provider,
            "model": bot.model,
            "name": bot.name,
        }


def _record_result(
    bot_id: int, thread_id: int, status: str, error: str | None, *, reschedule: bool
) -> Bot | None:
    with _session() as s:
        bot = s.query(Bot).filter_by(id=bot_id).first()
        if bot is None:
            return None
        bot.last_run_at = datetime.utcnow()
        bot.last_status = status
        bot.last_thread_id = thread_id
        bot.last_error = error
        if reschedule and bot.enabled:
            bot.next_run_at = next_run(bot.cron, bot.timezone)
        title = {
            "completed": f"{bot.name}: listo",
            "interrupted": f"{bot.name}: necesita tu aprobación",
        }.get(status, f"{bot.name}: ha fallado")
        kind = {"completed": "bot_completed", "interrupted": "needs_approval"}.get(
            status, "bot_failed"
        )
        s.add(
            Notification(
                kind=kind,
                title=title,
                body=error,
                thread_id=thread_id,
                bot_id=bot.id,
                created_at=datetime.utcnow(),
            )
        )
        s.flush()
        s.expunge(bot)
        return bot


async def execute_bot(bot_id: int, *, reschedule: bool = True) -> dict[str, Any]:
    """Ejecuta un bot en el tenant actual. Devuelve ``{thread_id, status}``."""
    from .runtime import AgentConfigError, run_turn

    prepared = await asyncio.to_thread(_prepare_run, bot_id)
    if prepared is None:
        return {"status": "missing"}
    status, error = "error", None
    try:
        async for event in run_turn(
            prepared["thread_id"],
            message=prepared["prompt"],
            initiator="bot",
            provider=prepared["provider"],
            model_name=prepared["model"],
            extra_instruction=(
                "\nEstás ejecutando una automatización programada sin el usuario delante: "
                "termina con un resumen claro; las escrituras quedarán pendientes de su aprobación."
            ),
        ):
            if event["type"] == "RUN_FINISHED":
                status = event.get("status", "completed")
            elif event["type"] == "RUN_ERROR":
                status, error = "error", event.get("message")
    except AgentConfigError as exc:
        status, error = "error", str(exc)
    bot = await asyncio.to_thread(
        _record_result, bot_id, prepared["thread_id"], status, error, reschedule=reschedule
    )
    if reschedule and bot is not None:
        await asyncio.to_thread(schedule, bot)
    return {"thread_id": prepared["thread_id"], "status": status, "error": error}
