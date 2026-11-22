"""Skills del asistente (patrón de nexus ``lib/skills``, sin BFF).

- ``DbSkillStore``: catálogo autorizado para un turno (skills activas en el chat
  o las asignadas a un bot) leído de la BD del tenant.
- ``DbSkillDraftBackend``: las 5 herramientas que usa el creador de skills de
  nas-adk para editar **solo** su borrador.
- ``publish_draft``: valida el borrador y crea una versión inmutable.

FinanceAI no ejecuta scripts de skills: no hay ejecutor aislado, así que
``run_skill_script`` nunca se ofrece al modelo.
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import datetime
from typing import Any

from nas.adk import Agent
from nas.adk.skills import SkillPackage, SkillRef, package_from_files, safe_skill_path
from nas.adk.skills.creator import CREATOR_INSTRUCTION
from nas.adk.skills.models import MAX_FILES, MAX_PACKAGE_BYTES
from nas.adk.tools.function_tool import FunctionTool

from ..db.session import _session
from ..models import Bot, ChatThread, Skill, SkillDraft, SkillVersion

SKILL_RUNTIME_TOOLS = frozenset({"activate_skill", "read_skill_file"})
DRAFT_TOOLS = frozenset(
    {"read_draft", "read_draft_file", "write_draft_file", "delete_draft_file", "validate_draft"}
)
MAX_READ = 12000


class SkillConflict(Exception):
    """Nombre duplicado o revisión desactualizada."""


# ── Utilidades de paquetes ───────────────────────────────────────────────────


def ref_id(skill_id: int) -> str:
    return f"s{skill_id}"


def decode_files(files_json: str | None) -> dict[str, bytes]:
    raw = json.loads(files_json or "{}")
    return {path: base64.b64decode(data) for path, data in raw.items()}


def encode_files(files: dict[str, bytes]) -> str:
    return json.dumps(
        {path: base64.b64encode(data).decode() for path, data in sorted(files.items())}
    )


def text_files(files: dict[str, bytes]) -> dict[str, str | None]:
    """Contenido de texto por ruta (``None`` si es binario)."""
    out: dict[str, str | None] = {}
    for path, data in sorted(files.items()):
        try:
            out[path] = data.decode("utf-8")
        except UnicodeDecodeError:
            out[path] = None
    return out


def validate_files(files: dict[str, bytes]) -> dict[str, Any]:
    try:
        package = package_from_files(files)
    except Exception as exc:  # pydantic/yaml/ValueError: siempre un mensaje legible
        return {"ok": False, "error": str(exc)}
    return {
        "ok": True,
        "name": package.manifest.name,
        "description": package.manifest.description,
        "files": sorted(package.files),
        "digest": package.digest,
    }


def _package(version: SkillVersion) -> SkillPackage:
    return SkillPackage.model_validate_json(version.package_json)


# ── Catálogo para un turno ───────────────────────────────────────────────────


def _catalog_rows(bot_id: int | None) -> list[tuple[Skill, SkillVersion]]:
    with _session() as s:
        query = (
            s.query(Skill, SkillVersion)
            .join(SkillVersion, SkillVersion.id == Skill.current_version_id)
            .filter(Skill.deleted_at.is_(None))
        )
        if bot_id is not None:
            bot = s.query(Bot).filter_by(id=bot_id).first()
            ids = json.loads(bot.skill_ids_json) if bot and bot.skill_ids_json else []
            if not ids:
                return []
            query = query.filter(Skill.id.in_(ids))
        else:
            query = query.filter(Skill.enabled_in_chat.is_(True))
        rows = query.order_by(Skill.name).all()
        for skill, version in rows:
            s.expunge(skill)
            s.expunge(version)
        return rows


class DbSkillStore:
    """``SkillStore`` de nas-adk con la foto del catálogo tomada al crear el turno."""

    def __init__(self, rows: list[tuple[Skill, SkillVersion]]) -> None:
        self._packages: dict[str, SkillPackage] = {}
        self._refs: list[SkillRef] = []
        for skill, version in rows:
            package = _package(version)
            ref = package.reference(ref_id(skill.id))
            self._packages[ref.id] = package
            self._refs.append(ref)

    @classmethod
    def for_thread(cls, bot_id: int | None) -> DbSkillStore:
        return cls(_catalog_rows(bot_id))

    @property
    def names(self) -> set[str]:
        return {ref.name for ref in self._refs}

    async def list(self) -> list[SkillRef]:
        return list(self._refs)

    async def load(self, id: str) -> SkillPackage:
        return self._packages[id]


def split_explicit(message: str, names: set[str]) -> list[str]:
    """Skills forzadas con el prefijo ``/nombre`` al inicio del mensaje."""
    explicit: list[str] = []
    for token in message.strip().split():
        if not token.startswith("/"):
            break
        name = token[1:]
        if name in names and name not in explicit:
            explicit.append(name)
    return explicit


# ── Backend del borrador (herramientas del creador) ──────────────────────────


def _load_draft(s, draft_id: int) -> SkillDraft:
    draft = s.query(SkillDraft).filter_by(id=draft_id).first()
    if draft is None:
        raise LookupError("Borrador no encontrado")
    return draft


class DbSkillDraftBackend:
    """Implementa ``nas.adk.skills.creator.SkillDraftBackend`` sobre ``skill_drafts``."""

    def __init__(self, draft_id: int) -> None:
        self.draft_id = draft_id

    def _files(self) -> dict[str, bytes]:
        with _session() as s:
            return decode_files(_load_draft(s, self.draft_id).files_json)

    def _mutate(self, change) -> dict[str, bytes]:
        with _session() as s:
            draft = _load_draft(s, self.draft_id)
            files = decode_files(draft.files_json)
            change(files)
            if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
                raise ValueError("El borrador supera el límite de archivos o tamaño")
            draft.files_json = encode_files(files)
            draft.revision += 1
            draft.updated_at = datetime.utcnow()
            return files

    async def read_draft(self) -> str:
        """Read the current skill draft: SKILL.md contents and the list of supporting files."""
        files = await asyncio.to_thread(self._files)
        skill_md = files.get("SKILL.md", b"").decode("utf-8", errors="replace")
        return json.dumps(
            {
                "SKILL.md": skill_md[:MAX_READ] or None,
                "files": {path: len(data) for path, data in sorted(files.items())},
            },
            ensure_ascii=False,
        )

    async def read_draft_file(self, path: str, offset: int = 0, limit: int = MAX_READ) -> str:
        """Read a draft file (package-relative path) with optional character pagination."""
        path = safe_skill_path(path)
        files = await asyncio.to_thread(self._files)
        if path not in files:
            return json.dumps({"error": f"{path} no existe en el borrador"})
        if offset < 0 or not 1 <= limit <= MAX_READ:
            return json.dumps({"error": "Paginación inválida"})
        try:
            text = files[path].decode("utf-8")
        except UnicodeDecodeError:
            return json.dumps({"path": path, "binary": True, "bytes": len(files[path])})
        end = offset + limit
        return json.dumps(
            {"path": path, "text": text[offset:end], "nextOffset": end if end < len(text) else None},
            ensure_ascii=False,
        )

    async def write_draft_file(self, path: str, content: str) -> str:
        """Create or replace a UTF-8 text file in the draft (e.g. SKILL.md, references/x.md)."""
        path = safe_skill_path(path)

        def change(files: dict[str, bytes]) -> None:
            files[path] = content.encode("utf-8")

        files = await asyncio.to_thread(self._mutate, change)
        return json.dumps({"written": path, "bytes": len(files[path])})

    async def delete_draft_file(self, path: str) -> str:
        """Delete a file from the draft."""
        path = safe_skill_path(path)

        def change(files: dict[str, bytes]) -> None:
            if path not in files:
                raise ValueError(f"{path} no existe en el borrador")
            del files[path]

        await asyncio.to_thread(self._mutate, change)
        return json.dumps({"deleted": path})

    async def validate_draft(self) -> str:
        """Validate the draft as a portable Agent Skill package and report any problem."""
        files = await asyncio.to_thread(self._files)
        return json.dumps(validate_files(files), ensure_ascii=False)

    def tools(self) -> list[FunctionTool]:
        return [
            FunctionTool(fn)
            for fn in (
                self.read_draft,
                self.read_draft_file,
                self.write_draft_file,
                self.delete_draft_file,
                self.validate_draft,
            )
        ]


def finance_context() -> str:
    """Contexto de FinanceAI para que las skills usen herramientas reales."""
    from . import tools as finance_tools

    lines = []
    for fn in finance_tools.ALL_TOOLS:
        doc = (fn.__doc__ or "").strip().splitlines()
        kind = "escritura (requiere aprobación)" if fn.__name__ in finance_tools.WRITE_NAMES else "lectura"
        lines.append(f"- {fn.__name__} [{kind}]: {doc[0] if doc else ''}")
    return (
        "\n\nHost application: FinanceAI, the user's personal finance manager. Skills you write "
        "are procedures for its finance assistant, which can call ONLY these tools:\n"
        + "\n".join(lines)
        + "\nReference these tools by name in the procedure when relevant; never invent other "
        "tools, APIs or scripts (scripts cannot run in FinanceAI). Conventions: answers in Spanish, "
        "amounts as 1.234,56 €, categories have two levels «Raíz › Subcategoría», KPIs already "
        "exclude internal transfers and investment buys/sells, and every write tool stops for the "
        "user's approval. Skills may also be used by scheduled automations running without the "
        "user present: make the procedure end with a clear summary."
    )


def build_creator(model: Any, draft_id: int) -> Agent:
    """Agente creador de skills (equivale a ``create_skill_creator`` + contexto del host)."""
    return Agent(
        name="skill_creator",
        model=model,
        instruction=CREATOR_INSTRUCTION + finance_context(),
        tools=DbSkillDraftBackend(draft_id).tools(),
    )


def draft_for_thread(thread_id: int) -> int | None:
    with _session() as s:
        draft = s.query(SkillDraft).filter_by(thread_id=thread_id).first()
        return draft.id if draft else None


# ── Biblioteca: borradores y publicación ─────────────────────────────────────


def create_draft(skill_id: int | None = None, files: dict[str, bytes] | None = None) -> int:
    """Crea la conversación del creador y su borrador (opcionalmente desde una skill)."""
    with _session() as s:
        base_version_id = None
        title = "Nueva skill"
        if skill_id is not None:
            skill = s.query(Skill).filter_by(id=skill_id).filter(Skill.deleted_at.is_(None)).first()
            if skill is None or skill.current_version_id is None:
                raise LookupError("Skill no encontrada")
            version = s.query(SkillVersion).filter_by(id=skill.current_version_id).one()
            package = _package(version)
            files = {path: package.read(path) for path in package.files}
            base_version_id = version.id
            title = f"Editar {skill.name}"
        elif files and "SKILL.md" in files:
            check = validate_files(files)
            if check["ok"]:
                title = f"Importar {check['name']}"
        now = datetime.utcnow()
        thread = ChatThread(
            title=title, origin="skill_creator", status="idle", created_at=now, updated_at=now
        )
        s.add(thread)
        s.flush()
        draft = SkillDraft(
            skill_id=skill_id,
            thread_id=thread.id,
            base_version_id=base_version_id,
            files_json=encode_files(files or {}),
            revision=0,
            created_at=now,
            updated_at=now,
        )
        s.add(draft)
        s.flush()
        return draft.id


def update_draft_files(draft_id: int, revision: int, changes: dict[str, str | None]) -> int:
    """Edición manual del usuario con bloqueo optimista por ``revision``."""
    with _session() as s:
        draft = _load_draft(s, draft_id)
        if draft.revision != revision:
            raise SkillConflict("El borrador ha cambiado; recarga antes de guardar")
        files = decode_files(draft.files_json)
        for path, content in changes.items():
            path = safe_skill_path(path)
            if content is None:
                files.pop(path, None)
            else:
                files[path] = content.encode("utf-8")
        if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_PACKAGE_BYTES:
            raise ValueError("El borrador supera el límite de archivos o tamaño")
        draft.files_json = encode_files(files)
        draft.revision += 1
        draft.updated_at = datetime.utcnow()
        return draft.revision


def publish_draft(draft_id: int) -> dict[str, Any]:
    """Valida el borrador y crea una versión inmutable (nueva skill o versión siguiente)."""
    with _session() as s:
        draft = _load_draft(s, draft_id)
        files = decode_files(draft.files_json)
        try:
            package = package_from_files(files)
        except Exception as exc:
            raise ValueError(f"El borrador no es una skill válida: {exc}") from exc
        name = package.manifest.name
        clash = (
            s.query(Skill)
            .filter(Skill.name == name, Skill.deleted_at.is_(None))
            .filter(Skill.id != (draft.skill_id or 0))
            .first()
        )
        if clash is not None:
            raise SkillConflict(f"Ya tienes otra skill llamada «{name}»")
        now = datetime.utcnow()
        skill = None
        if draft.skill_id is not None:
            skill = s.query(Skill).filter_by(id=draft.skill_id).first()
            if skill is not None and skill.deleted_at is not None:
                skill = None
        if skill is None:
            skill = Skill(
                name=name,
                description=package.manifest.description,
                enabled_in_chat=True,
                source="creator",
                created_at=now,
            )
            s.add(skill)
            s.flush()
        last = (
            s.query(SkillVersion.version)
            .filter_by(skill_id=skill.id)
            .order_by(SkillVersion.version.desc())
            .first()
        )
        current = s.query(SkillVersion).filter_by(id=skill.current_version_id).first()
        if current is not None and current.digest == package.digest:
            raise SkillConflict("No hay cambios respecto a la versión publicada")
        version = SkillVersion(
            skill_id=skill.id,
            version=(last[0] if last else 0) + 1,
            digest=package.digest,
            package_json=package.model_dump_json(),
            created_at=now,
        )
        s.add(version)
        s.flush()
        skill.name = name
        skill.description = package.manifest.description
        skill.current_version_id = version.id
        skill.updated_at = now
        draft.skill_id = skill.id
        draft.base_version_id = version.id
        draft.updated_at = now
        return {"skill_id": skill.id, "version": version.version, "name": name}


def version_package(version_id: int) -> SkillPackage:
    with _session() as s:
        version = s.query(SkillVersion).filter_by(id=version_id).first()
        if version is None:
            raise LookupError("Versión no encontrada")
        return _package(version)
