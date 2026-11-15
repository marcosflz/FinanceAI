"""API v3 — autenticación y healthcheck (F0).

Rutas públicas: ``/api/v3/health``, ``/healthz`` y ``/api/v3/auth/login``.
El resto del router protegido exige sesión; los métodos unsafe exigen
además CSRF (cookie ``ft_csrf`` + header ``X-CSRF-Token``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from .auth import tenancy
from .auth.cookies import clear_auth_cookies, set_auth_cookies, set_csrf_cookie
from .auth.dependencies import client_ip, require_csrf, require_user
from .auth.keys import KeyUnwrapError
from .auth.passwords import hash_password, validate_password_strength, verify_password
from .auth.service import (
    authenticate,
    create_session,
    login_retry_after,
    normalise_email,
    normalise_name,
    record_login_attempt,
    revoke_all_sessions,
    revoke_session,
    session_remaining_seconds,
)
from .auth.tokens import generate_csrf_token, hash_session_token
from .config import get_settings
from .db.session import get_db
from .models import Session as UserSession
from .models import User

public_router = APIRouter(prefix="/api/v3", tags=["v3-public"])
protected_router = APIRouter(
    prefix="/api/v3", tags=["v3"], dependencies=[Depends(require_user)]
)
health_router = APIRouter(tags=["health"])


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class RecoverRequest(BaseModel):
    email: str
    recovery_key: str
    new_password: str


class AcceptInviteRequest(BaseModel):
    token: str
    password: str
    name: str | None = None


class AutomationRequest(BaseModel):
    enabled: bool
    password: str
    days: int | None = None


class ProfileUpdateRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    # Solo es obligatoria cuando se cambia el email de acceso.
    current_password: str | None = None


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MAX_NAME_LENGTH = 120
_MAX_EMAIL_LENGTH = 255


def _user_payload(user: User) -> dict:
    email = user.email or ""
    return {
        "id": user.id,
        "email": user.email,
        # ``name`` es el nombre editable del perfil; si aún no se ha
        # configurado, mantenemos la compatibilidad con el local-part.
        "name": user.name or email.split("@", 1)[0],
        "role": user.role,
        "disabled": bool(user.disabled),
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "automation_until": user.automation_until,
    }


def _open_session(
    db: OrmSession,
    request: Request,
    response: Response,
    user: User,
    dek: bytes | None,
) -> tuple[UserSession, str]:
    """Crea la sesión, le liga la DEK y fija las cookies tras el commit."""
    settings = get_settings()
    token, row = create_session(
        db,
        user=user,
        ttl_days=settings.session_ttl_days,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    tenancy.bind_session_key(row, dek, token)
    if dek is not None:
        tenancy.refresh_leases(db, user, dek, force=True)
    csrf_token = generate_csrf_token(settings.session_secret_value)
    # La cookie se envía con la respuesta; si el commit se deja al teardown
    # del dependency, el navegador puede pedir /me antes de que la sesión
    # exista y recibir un 401 intermitente.
    db.commit()
    set_auth_cookies(response, session_token=token, csrf_token=csrf_token, settings=settings)
    return row, csrf_token


def _request_dek(request: Request) -> bytes | None:
    ctx = getattr(request.state, "tenant", None)
    return ctx.key if ctx is not None else None


def _health_payload(db: OrmSession) -> dict:
    settings = get_settings()
    db_ok = True
    revision = None
    try:
        db.execute(text("SELECT 1"))
        version_table = (
            "alembic_version_central" if settings.per_user else "alembic_version"
        )
        try:
            revision = db.execute(text(f"SELECT version_num FROM {version_table}")).scalar()
        except Exception:
            revision = None
    except Exception:
        db_ok = False

    storage_ok = True
    try:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        storage_ok = os.access(settings.data_dir, os.W_OK)
    except Exception:
        storage_ok = False

    healthy = db_ok and storage_ok and (revision is not None or not settings.is_production)
    return {
        "status": "ok" if healthy else "degraded",
        "env": settings.env,
        "database": {"ok": db_ok, "revision": revision},
        "tenancy": {
            "mode": settings.tenant_mode,
            "encryption": settings.per_user and settings.tenant_encryption,
        },
        "storage": {"ok": storage_ok, "path": str(settings.data_dir)},
        "opencode_model": settings.opencode_model,
        "typesafe_configured": settings.typesafe_api_key is not None,
        "opencode_configured": settings.opencode_api_key is not None,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@health_router.get("/healthz")
def healthz(db: OrmSession = Depends(get_db)) -> dict:
    return _health_payload(db)


@public_router.get("/health")
def health(db: OrmSession = Depends(get_db)) -> dict:
    return _health_payload(db)


@public_router.post("/auth/login")
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> dict:
    email = normalise_email(payload.email)
    ip = client_ip(request)

    retry_after = login_retry_after(db, email=email, ip=ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Prueba de nuevo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    user = authenticate(db, email, payload.password)
    if user is None:
        record_login_attempt(db, email=email, ip=ip, ok=False)
        # Persistir el intento antes de lanzar: el dependency haría rollback.
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    try:
        dek, recovery_key = tenancy.unlock_at_login(user, payload.password)
    except KeyUnwrapError as exc:
        # El hash de login es válido pero la DEK no se desenvuelve: material de
        # claves inconsistente. No se crea sesión para no operar sin datos.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se pudo desbloquear la base de datos del usuario",
        ) from exc

    record_login_attempt(db, email=email, ip=ip, ok=True)
    user.last_login_at = datetime.utcnow()
    row, csrf_token = _open_session(db, request, response, user, dek)
    body = {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
    }
    if recovery_key:
        # Única vez que existe en claro: el frontend la muestra y la olvida.
        body["recovery_key"] = recovery_key
    return body


@public_router.post("/auth/recover")
def recover_account(
    payload: RecoverRequest,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> dict:
    """Restablece la contraseña con la clave de recuperación sin perder datos.

    Emite una clave de recuperación nueva (la anterior deja de valer).
    """
    email = normalise_email(payload.email)
    ip = client_ip(request)
    retry_after = login_retry_after(db, email=email, ip=ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Prueba de nuevo más tarde.",
            headers={"Retry-After": str(retry_after)},
        )
    user = db.query(User).filter(User.email == email).first()
    dek = None
    if user is not None and not user.disabled and user.dek_wrapped_recovery:
        try:
            dek = tenancy.keys.unlock_with_recovery(
                user.id,
                payload.recovery_key,
                recovery_salt=user.recovery_salt,
                dek_wrapped_recovery=user.dek_wrapped_recovery,
            )
        except KeyUnwrapError:
            dek = None
    if dek is None:
        record_login_attempt(db, email=email, ip=ip, ok=False)
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o clave de recuperación incorrectos",
        )
    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    user.password_hash = hash_password(payload.new_password)
    tenancy.change_password_keys(user, dek, payload.new_password)
    new_recovery_key = tenancy.rotate_recovery_key(user, dek)
    revoke_all_sessions(db, user_id=user.id)
    tenancy.revoke_leases(db, user.id)
    record_login_attempt(db, email=email, ip=ip, ok=True)
    user.last_login_at = datetime.utcnow()
    row, csrf_token = _open_session(db, request, response, user, dek)
    return {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
        "recovery_key": new_recovery_key,
    }


@public_router.post("/auth/accept-invite")
def accept_invite(
    payload: AcceptInviteRequest,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> dict:
    """El invitado fija su propia contraseña; el admin nunca la conoce."""
    token_hash = hash_session_token(payload.token or "")
    user = db.query(User).filter(User.invite_token_hash == token_hash).first()
    now = datetime.utcnow()
    if (
        user is None
        or user.disabled
        or user.invite_expires_at is None
        or user.invite_expires_at <= now
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invitación inválida o caducada",
        )
    try:
        validate_password_strength(payload.password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    user.password_hash = hash_password(payload.password)
    if "name" in payload.model_fields_set:
        user.name = normalise_name(payload.name)
    user.invite_token_hash = None
    user.invite_expires_at = None
    dek, recovery_key = tenancy.unlock_at_login(user, payload.password)
    user.last_login_at = now
    row, csrf_token = _open_session(db, request, response, user, dek)
    body = {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
    }
    if recovery_key:
        body["recovery_key"] = recovery_key
    return body


@protected_router.get("/auth/me")
def me(
    request: Request,
    response: Response,
    user: User = Depends(require_user),
) -> dict:
    settings = get_settings()
    row: UserSession = request.state.session
    csrf_token = request.cookies.get(settings.csrf_cookie_name)
    if not csrf_token:
        csrf_token = generate_csrf_token(settings.session_secret_value)
        set_csrf_cookie(response, csrf_token, settings)
    # GET /me devuelve el usuario plano (contrato del frontend) + metadatos.
    payload = _user_payload(user)
    payload.update(
        {
            "expires_at": row.expires_at,
            "remaining_seconds": session_remaining_seconds(row),
            "csrf_token": csrf_token,
            "tenancy": {
                "mode": settings.tenant_mode,
                "encryption": settings.per_user and settings.tenant_encryption,
            },
        }
    )
    return payload


@protected_router.patch("/auth/profile", dependencies=[Depends(require_csrf)])
def update_profile(
    payload: ProfileUpdateRequest,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    """Actualiza nombre y/o email del usuario autenticado.

    El email es la identidad de acceso: si cambia, se exige la contraseña
    actual para evitar que una sesión robada pueda secuestrar la cuenta.
    """
    changed = False

    # ``name=null`` de forma explícita limpia el nombre; ausente no lo toca.
    if "name" in payload.model_fields_set:
        name = normalise_name(payload.name)
        if name is not None and len(name) > _MAX_NAME_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El nombre no puede superar {_MAX_NAME_LENGTH} caracteres",
            )
        if name != user.name:
            user.name = name
            changed = True

    if payload.email is not None:
        email = normalise_email(payload.email)
        if (
            not email
            or len(email) > _MAX_EMAIL_LENGTH
            or _EMAIL_RE.fullmatch(email) is None
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El email no es válido",
            )
        if email != user.email:
            if not payload.current_password:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Para cambiar el email debes introducir tu contraseña actual",
                )
            if not verify_password(user.password_hash, payload.current_password):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="La contraseña actual no es correcta",
                )
            existing = (
                db.query(User)
                .filter(User.email == email, User.id != user.id)
                .first()
            )
            if existing is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ese email ya está en uso",
                )
            user.email = email
            changed = True

    if changed:
        db.flush()
    return _user_payload(user)


@protected_router.post("/auth/logout", dependencies=[Depends(require_csrf)])
def logout(
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    row: UserSession = request.state.session
    revoke_session(db, row)
    clear_auth_cookies(response, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@protected_router.post(
    "/auth/change-password", dependencies=[Depends(require_csrf)]
)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no es correcta",
        )
    try:
        validate_password_strength(payload.new_password)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    user.password_hash = hash_password(payload.new_password)
    # La DEK no cambia: solo se re-envuelve con la KEK nueva.
    dek = _request_dek(request)
    tenancy.change_password_keys(user, dek, payload.new_password)
    # Invalida todas las sesiones (incluida la actual) y emite una nueva.
    revoke_all_sessions(db, user_id=user.id)
    row, csrf_token = _open_session(db, request, response, user, dek)
    return {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
    }


@protected_router.post("/auth/recovery-key", dependencies=[Depends(require_csrf)])
def regenerate_recovery_key(
    payload: LoginRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    """Genera una clave de recuperación nueva (invalida la anterior)."""
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no es correcta",
        )
    dek = _request_dek(request)
    if dek is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El cifrado por usuario no está activo",
        )
    recovery_key = tenancy.rotate_recovery_key(user, dek)
    db.flush()
    return {"recovery_key": recovery_key}


@protected_router.put("/auth/automation", dependencies=[Depends(require_csrf)])
def set_automation(
    payload: AutomationRequest,
    request: Request,
    db: OrmSession = Depends(get_db),
    user: User = Depends(require_user),
) -> dict:
    """Opt-in: permite que el worker descifre tus datos sin sesión abierta.

    La concesión solo vive en la RAM del worker: si se reinicia, las
    automatizaciones esperan a tu siguiente inicio de sesión.
    """
    settings = get_settings()
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual no es correcta",
        )
    if not payload.enabled:
        user.automation_until = None
        tenancy.revoke_leases(db, user.id, "automation")
        db.flush()
        return {"automation_until": None, "workers": 0}
    days = min(payload.days or settings.automation_lease_days, settings.automation_lease_days)
    user.automation_until = datetime.utcnow() + timedelta(days=max(1, days))
    dek = _request_dek(request)
    workers = 0
    if dek is not None:
        workers = tenancy.grant_lease(
            db, user, dek, purpose="automation", expires_at=user.automation_until
        )
    db.flush()
    return {"automation_until": user.automation_until, "workers": workers}


@protected_router.post("/auth/logout-all", dependencies=[Depends(require_csrf)])
def logout_all(
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> Response:
    settings = get_settings()
    row: UserSession = request.state.session
    revoke_all_sessions(db, user_id=row.user_id)
    clear_auth_cookies(response, settings)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
