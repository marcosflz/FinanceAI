"""Portabilidad de datos y administración de usuarios.

- ``POST /api/v3/export/database``: descarga tu SQLite completo, descifrado
  (``sqlite``) o cifrado con una passphrase que eliges (``sqlcipher``; se abre
  con DB Browser for SQLite/SQLCipher o ``sqlcipher``). Exige la contraseña.
- ``/api/v3/admin/users``: alta por invitación. El admin no elige ni ve la
  contraseña del invitado (si la conociera podría derivar su KEK).
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import tempfile
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as OrmSession

from .auth.dependencies import require_csrf, require_user
from .auth.passwords import verify_password
from .auth.service import normalise_email, normalise_name, revoke_all_sessions
from .auth.tokens import hash_session_token
from .config import get_settings
from .db.session import _session, get_db
from .db.tenant import current_tenant, tenant_db_path
from .models import User

router = APIRouter(
    prefix="/api/v3",
    tags=["v3-account"],
    dependencies=[Depends(require_user), Depends(require_csrf)],
)

INVITE_DAYS = 7


class ExportRequest(BaseModel):
    password: str
    format: Literal["sqlite", "sqlcipher"] = "sqlite"
    passphrase: str | None = Field(default=None, min_length=12)


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _export_per_user(dest: str, body: ExportRequest) -> None:
    ctx = current_tenant()
    if ctx is None:
        raise HTTPException(409, "Sin base de datos de usuario")
    settings = get_settings()
    source = tenant_db_path(ctx.tenant_id)
    # Asegura que el fichero existe y está migrado (abre el motor del tenant).
    with _session():
        pass
    if not settings.tenant_encryption:
        with sqlite3.connect(source) as src, sqlite3.connect(dest) as out:
            src.backup(out)
        return

    import sqlcipher3

    conn = sqlcipher3.dbapi2.connect(str(source))
    try:
        conn.execute("PRAGMA cipher_log_level = NONE")
        conn.execute(f"PRAGMA key = \"x'{ctx.key.hex()}'\"")
        key = body.passphrase if body.format == "sqlcipher" else ""
        conn.execute("ATTACH DATABASE ? AS export KEY ?", (dest, key))
        conn.execute("SELECT sqlcipher_export('export')")
        conn.execute("DETACH DATABASE export")
    finally:
        conn.close()


def _export_single(dest: str) -> None:
    from .db.session import get_engine

    engine = get_engine()
    if engine.dialect.name != "sqlite":
        raise HTTPException(
            400, "La exportación de base de datos solo está disponible con SQLite"
        )
    raw = engine.raw_connection()
    try:
        with sqlite3.connect(dest) as out:
            raw.driver_connection.backup(out)
    finally:
        raw.close()


@router.post("/export/database")
def export_database(
    body: ExportRequest,
    background: BackgroundTasks,
    user: User = Depends(require_user),
) -> FileResponse:
    if not verify_password(user.password_hash, body.password):
        raise HTTPException(400, "La contraseña actual no es correcta")
    settings = get_settings()
    if body.format == "sqlcipher":
        if not body.passphrase:
            raise HTTPException(422, "Indica una passphrase para la copia cifrada")
        if not (settings.per_user and settings.tenant_encryption):
            raise HTTPException(409, "El cifrado por usuario no está activo")

    fd, dest = tempfile.mkstemp(prefix="ft-export-", suffix=".db")
    os.close(fd)
    os.unlink(dest)  # sqlcipher_export/backup crean el fichero
    try:
        if settings.per_user:
            _export_per_user(dest, body)
        else:
            _export_single(dest)
    except Exception:
        _cleanup(dest)
        raise
    background.add_task(_cleanup, dest)
    stamp = datetime.utcnow().strftime("%Y%m%d")
    suffix = "sqlcipher.db" if body.format == "sqlcipher" else "db"
    return FileResponse(
        dest,
        media_type="application/vnd.sqlite3",
        filename=f"finanzas-{stamp}.{suffix}",
    )


# ── Administración de usuarios ───────────────────────────────────────────────


class InviteRequest(BaseModel):
    email: str
    name: str | None = None
    role: Literal["user", "admin"] = "user"


class UserStatusRequest(BaseModel):
    disabled: bool


def _require_admin(request: Request) -> User:
    user: User = request.state.user
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo para administradores")
    return user


def _admin_payload(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role,
        "disabled": bool(user.disabled),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "invite_pending": user.invite_token_hash is not None,
        "invite_expires_at": user.invite_expires_at,
        "encrypted": bool(user.dek_wrapped_pw),
    }


@router.get("/admin/users")
def list_users(request: Request, db: OrmSession = Depends(get_db)) -> dict:
    _require_admin(request)
    users = db.query(User).order_by(User.id).all()
    return {"items": [_admin_payload(u) for u in users]}


@router.post("/admin/users", status_code=201)
def invite_user(
    body: InviteRequest, request: Request, db: OrmSession = Depends(get_db)
) -> dict:
    """Crea (o renueva) una invitación. El token solo se devuelve aquí."""
    _require_admin(request)
    email = normalise_email(body.email)
    if "@" not in email:
        raise HTTPException(422, "El email no es válido")
    token = secrets.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(days=INVITE_DAYS)
    user = db.query(User).filter(User.email == email).first()
    if user is not None and user.dek_wrapped_pw:
        raise HTTPException(409, "Ese usuario ya tiene cuenta activa")
    if user is None:
        user = User(
            email=email,
            name=normalise_name(body.name),
            # Hash imposible: no se puede iniciar sesión hasta aceptar.
            password_hash="!invited",
            role=body.role,
            created_at=datetime.utcnow(),
        )
        db.add(user)
    user.invite_token_hash = hash_session_token(token)
    user.invite_expires_at = expires
    db.flush()
    return {
        "user": _admin_payload(user),
        "invite_token": token,
        "invite_path": f"/invite?token={token}",
    }


@router.patch("/admin/users/{user_id}")
def set_user_status(
    user_id: int,
    body: UserStatusRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
) -> dict:
    admin = _require_admin(request)
    if user_id == admin.id:
        raise HTTPException(400, "No puedes deshabilitar tu propia cuenta")
    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    user.disabled = body.disabled
    if body.disabled:
        revoke_all_sessions(db, user_id=user.id)
        from .auth.tenancy import revoke_leases

        revoke_leases(db, user.id)
    db.flush()
    return _admin_payload(user)
