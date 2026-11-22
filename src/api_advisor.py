"""API v3 de la memoria del asistente, el asesor de cartera y los feeds de noticias."""

from __future__ import annotations

import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from . import news
from .agent import advisor, memory
from .agent import bots as bot_ops
from .auth.dependencies import require_csrf, require_user
from .db.session import _session
from .models import AgentMemory, Bot

router = APIRouter(
    prefix="/api/v3",
    tags=["v3-advisor"],
    dependencies=[Depends(require_user), Depends(require_csrf)],
)


# ── Memoria ──────────────────────────────────────────────────────────────────


class MemoryIn(BaseModel):
    key: str = Field(min_length=3, max_length=128)
    value: str = Field(min_length=1, max_length=2000)


class MemoryPatch(BaseModel):
    value: str = Field(min_length=1, max_length=2000)


@router.get("/agent/memories")
def list_memories(q: str | None = Query(default=None, max_length=200)) -> dict:
    return {"items": memory.search(q, limit=300)}


@router.post("/agent/memories", status_code=201)
def create_memory(body: MemoryIn) -> dict:
    try:
        return memory.upsert(body.key, body.value, source="user")
    except memory.MemoryRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.patch("/agent/memories/{memory_id}")
def update_memory(memory_id: int, body: MemoryPatch) -> dict:
    with _session() as s:
        row = s.query(AgentMemory).filter_by(id=memory_id).first()
        if row is None:
            raise HTTPException(404, "Recuerdo no encontrado")
        key = row.key
    try:
        return memory.upsert(key, body.value, source="user")
    except memory.MemoryRejected as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/agent/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory(memory_id: int) -> None:
    with _session() as s:
        row = s.query(AgentMemory).filter_by(id=memory_id).first()
        if row is None:
            raise HTTPException(404, "Recuerdo no encontrado")
        s.delete(row)


@router.delete("/agent/memories", status_code=status.HTTP_204_NO_CONTENT)
def clear_memories() -> None:
    with _session() as s:
        s.query(AgentMemory).delete(synchronize_session=False)


# ── Asesor ───────────────────────────────────────────────────────────────────


@router.get("/advisor/status")
def advisor_status() -> dict:
    return advisor.status()


@router.post("/advisor/setup", status_code=201)
def advisor_setup() -> dict:
    """Instala la skill ``asesor-cartera`` y crea el bot diario si no existe."""
    skill_id = advisor.install_skill()
    existing = advisor.advisor_bot()
    if existing is not None:
        return existing
    template = advisor.TEMPLATE
    with _session() as s:
        bot = Bot(
            name=template["name"],
            prompt=template["prompt"],
            cron=template["cron"],
            timezone="Europe/Madrid",
            template=advisor.TEMPLATE_ID,
            enabled=True,
            skill_ids_json=f"[{skill_id}]",
            next_run_at=bot_ops.next_run(template["cron"], "Europe/Madrid"),
            created_at=datetime.utcnow(),
        )
        s.add(bot)
        s.flush()
        payload = bot_ops.bot_payload(bot)
        s.expunge(bot)
    bot_ops.schedule(bot)
    return payload


@router.post("/advisor/skill", status_code=201)
def advisor_install_skill() -> dict:
    return {"skill_id": advisor.install_skill()}


@router.get("/advisor/latest")
def advisor_latest() -> dict:
    return advisor.latest()


@router.get("/advisor/history")
def advisor_history(
    symbol: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    return advisor.history(symbol, limit)


@router.get("/advisor/evaluation")
async def advisor_evaluation(min_age_days: int = Query(default=7, ge=0, le=365)) -> dict:
    return await asyncio.to_thread(advisor.evaluate, min_age_days)


# ── Feeds de noticias ────────────────────────────────────────────────────────


class Feed(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    url: str = Field(min_length=8, max_length=500)


class FeedsIn(BaseModel):
    items: list[Feed] = Field(max_length=news.MAX_FEEDS)


@router.get("/advisor/feeds")
def get_feeds() -> dict:
    return {"items": news.get_feeds(), "defaults": news.DEFAULT_FEEDS}


@router.put("/advisor/feeds")
async def put_feeds(body: FeedsIn) -> dict:
    try:
        items = await asyncio.to_thread(news.set_feeds, [f.model_dump() for f in body.items])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"items": items}


@router.get("/advisor/news")
async def get_news(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=30, ge=1, le=60),
) -> dict:
    return await asyncio.to_thread(news.market_news, q, limit)
