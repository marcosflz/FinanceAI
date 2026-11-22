"""API v3 de skills: biblioteca, borradores del creador asistido y publicación.

Flujo (equivalente a nexus ``app/api/skill-drafts``):

1. ``POST /agent/skill-drafts`` crea un borrador con su conversación
   (``origin='skill_creator'``), vacío o desde una skill existente.
2. ``POST /agent/skill-drafts/{id}/messages`` habla con el creador: es un
   turno normal del hub (SSE reanudable) cuyo agente solo puede editar el borrador.
3. ``PATCH`` guarda ediciones manuales con bloqueo optimista por ``revision``.
4. ``POST .../publish`` valida y crea una versión inmutable en la biblioteca.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from nas.adk.skills import SkillPackage, export_zip, import_zip
from pydantic import BaseModel, Field

from .agent import hub
from .agent import skills as skill_ops
from .agent.runtime import run_turn
from .api_agent import MessageCreate, _heal_thread, _message_payload, _prepare_turn, _stream
from .auth.dependencies import require_csrf, require_user
from .db.session import _session
from .models import AgentRun, Bot, ChatMessage, ChatThread, Skill, SkillDraft, SkillVersion

router = APIRouter(
    prefix="/api/v3/agent",
    tags=["v3-skills"],
    dependencies=[Depends(require_user), Depends(require_csrf)],
)


# ── Biblioteca ───────────────────────────────────────────────────────────────


def _skill_payload(s, skill: Skill) -> dict[str, Any]:
    versions = (
        s.query(SkillVersion.id, SkillVersion.version, SkillVersion.created_at)
        .filter_by(skill_id=skill.id)
        .order_by(SkillVersion.version.desc())
        .all()
    )
    current = next((v for v in versions if v.id == skill.current_version_id), None)
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "enabled_in_chat": bool(skill.enabled_in_chat),
        "source": skill.source,
        "version": current.version if current else None,
        "versions": [
            {"id": v.id, "version": v.version, "created_at": v.created_at} for v in versions
        ],
        "created_at": skill.created_at,
        "updated_at": skill.updated_at,
    }


def _get_skill(s, skill_id: int) -> Skill:
    skill = s.query(Skill).filter_by(id=skill_id).filter(Skill.deleted_at.is_(None)).first()
    if skill is None:
        raise HTTPException(404, "Skill no encontrada")
    return skill


@router.get("/skills")
def list_skills() -> dict:
    with _session() as s:
        rows = s.query(Skill).filter(Skill.deleted_at.is_(None)).order_by(Skill.name).all()
        return {"items": [_skill_payload(s, skill) for skill in rows]}


@router.get("/skills/{skill_id}")
def get_skill(skill_id: int) -> dict:
    with _session() as s:
        skill = _get_skill(s, skill_id)
        payload = _skill_payload(s, skill)
        version_id = skill.current_version_id
    package = skill_ops.version_package(version_id)
    files = {path: package.read(path) for path in package.files}
    return {**payload, "files": skill_ops.text_files(files)}


class SkillUpdate(BaseModel):
    enabled_in_chat: bool | None = None


@router.patch("/skills/{skill_id}")
def update_skill(skill_id: int, body: SkillUpdate) -> dict:
    with _session() as s:
        skill = _get_skill(s, skill_id)
        if body.enabled_in_chat is not None:
            skill.enabled_in_chat = body.enabled_in_chat
        skill.updated_at = datetime.utcnow()
        s.flush()
        return _skill_payload(s, skill)


@router.delete("/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(skill_id: int) -> None:
    with _session() as s:
        skill = _get_skill(s, skill_id)
        skill.deleted_at = datetime.utcnow()
        for bot in s.query(Bot).filter(Bot.skill_ids_json.isnot(None)):
            ids = [i for i in json.loads(bot.skill_ids_json) if i != skill_id]
            bot.skill_ids_json = json.dumps(ids) if ids else None


@router.get("/skills/{skill_id}/export")
def export_skill(skill_id: int) -> Response:
    with _session() as s:
        skill = _get_skill(s, skill_id)
        name, version_id = skill.name, skill.current_version_id
    data = export_zip(skill_ops.version_package(version_id))
    return Response(
        data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@router.post("/skills/import", status_code=201)
async def import_skills(file: UploadFile = File(...)) -> dict:
    """Importa un ZIP: cada skill encontrada abre un borrador para revisarla y publicarla."""
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        packages = await asyncio.to_thread(import_zip, data)
    except Exception as exc:
        raise HTTPException(422, f"No se pudo importar: {exc}") from exc
    drafts = []
    for package in packages:
        files = {path: package.read(path) for path in package.files}
        draft_id = await asyncio.to_thread(skill_ops.create_draft, None, files)
        drafts.append({"draft_id": draft_id, "name": package.manifest.name})
    return {"items": drafts}


# ── Borradores ───────────────────────────────────────────────────────────────


class DraftCreate(BaseModel):
    skill_id: int | None = None


class DraftPatch(BaseModel):
    revision: int = Field(ge=0)
    # ruta → contenido de texto; ``null`` borra el archivo.
    files: dict[str, str | None] = Field(min_length=1, max_length=256)


def _get_draft(s, draft_id: int) -> SkillDraft:
    draft = s.query(SkillDraft).filter_by(id=draft_id).first()
    if draft is None:
        raise HTTPException(404, "Borrador no encontrado")
    return draft


def _draft_summary(s, draft: SkillDraft) -> dict[str, Any]:
    files = skill_ops.decode_files(draft.files_json)
    check = skill_ops.validate_files(files) if files else {"ok": False, "error": "Vacío"}
    thread = s.query(ChatThread).filter_by(id=draft.thread_id).first()
    return {
        "id": draft.id,
        "skill_id": draft.skill_id,
        "thread_id": draft.thread_id,
        "base_version_id": draft.base_version_id,
        "revision": draft.revision,
        "name": check.get("name") or (thread.title if thread else None),
        "valid": check["ok"],
        "status": thread.status if thread else "idle",
        "created_at": draft.created_at,
        "updated_at": draft.updated_at,
    }


@router.get("/skill-drafts")
def list_drafts() -> dict:
    with _session() as s:
        rows = s.query(SkillDraft).order_by(SkillDraft.updated_at.desc()).limit(100).all()
        return {"items": [_draft_summary(s, d) for d in rows]}


@router.post("/skill-drafts", status_code=201)
def create_draft(body: DraftCreate) -> dict:
    try:
        draft_id = skill_ops.create_draft(body.skill_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": draft_id}


@router.get("/skill-drafts/{draft_id}")
def get_draft(draft_id: int) -> dict:
    with _session() as s:
        draft = _get_draft(s, draft_id)
        thread = s.query(ChatThread).filter_by(id=draft.thread_id).one()
        _heal_thread(s, thread)
        files = skill_ops.decode_files(draft.files_json)
        messages = (
            s.query(ChatMessage).filter_by(thread_id=thread.id).order_by(ChatMessage.id).all()
        )
        active = (
            s.query(AgentRun)
            .filter_by(thread_id=thread.id, status="running")
            .order_by(AgentRun.id.desc())
            .first()
        )
        base_files: dict[str, str | None] | None = None
        if draft.base_version_id is not None:
            version = s.query(SkillVersion).filter_by(id=draft.base_version_id).first()
            if version is not None:
                package = SkillPackage.model_validate_json(version.package_json)
                base_files = skill_ops.text_files({p: package.read(p) for p in package.files})
        return {
            **_draft_summary(s, draft),
            "files": skill_ops.text_files(files),
            "base_files": base_files,
            "validation": skill_ops.validate_files(files) if files else None,
            "messages": [_message_payload(m) for m in messages],
            "active_run_id": active.id if active else None,
        }


@router.patch("/skill-drafts/{draft_id}")
def patch_draft(draft_id: int, body: DraftPatch) -> dict:
    with _session() as s:
        draft = _get_draft(s, draft_id)
        if hub.thread_is_live(draft.thread_id):
            raise HTTPException(409, "El creador está editando el borrador; espera a que termine")
    try:
        revision = skill_ops.update_draft_files(draft_id, body.revision, body.files)
    except skill_ops.SkillConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"revision": revision}


@router.delete("/skill-drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_draft(draft_id: int) -> None:
    with _session() as s:
        draft = _get_draft(s, draft_id)
        if hub.thread_is_live(draft.thread_id):
            raise HTTPException(409, "El creador tiene un turno en curso")
        thread = s.query(ChatThread).filter_by(id=draft.thread_id).first()
        s.delete(draft)
        if thread is not None:
            s.delete(thread)


def _draft_thread(draft_id: int) -> int:
    with _session() as s:
        return _get_draft(s, draft_id).thread_id


@router.post("/skill-drafts/{draft_id}/messages")
async def draft_message(draft_id: int, body: MessageCreate):
    thread_id = await asyncio.to_thread(_draft_thread, draft_id)
    await asyncio.to_thread(_prepare_turn, thread_id)
    return await _stream(
        run_turn(thread_id, message=body.message, provider=body.provider, model_name=body.model)
    )


@router.post("/skill-drafts/{draft_id}/publish")
def publish(draft_id: int) -> dict:
    with _session() as s:
        draft = _get_draft(s, draft_id)
        if hub.thread_is_live(draft.thread_id):
            raise HTTPException(409, "Espera a que el creador termine antes de publicar")
    try:
        return skill_ops.publish_draft(draft_id)
    except skill_ops.SkillConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

