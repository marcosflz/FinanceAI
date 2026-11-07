"""API v3 — autenticación y healthcheck (F0).

Rutas públicas: ``/api/v3/health``, ``/healthz`` y ``/api/v3/auth/login``.
El resto del router protegido exige sesión; los métodos unsafe exigen
además CSRF (cookie ``ft_csrf`` + header ``X-CSRF-Token``).
"""

from __future__ import annotations

import os
import re
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session as OrmSession

from .auth.cookies import clear_auth_cookies, set_auth_cookies, set_csrf_cookie
from .auth.dependencies import client_ip, require_csrf, require_user
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
from .auth.tokens import generate_csrf_token
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
    }


def _health_payload(db: OrmSession) -> dict:
    settings = get_settings()
    db_ok = True
    revision = None
    try:
        db.execute(text("SELECT 1"))
        try:
            revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
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
    settings = get_settings()
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

    record_login_attempt(db, email=email, ip=ip, ok=True)
    user.last_login_at = datetime.utcnow()
    token, row = create_session(
        db,
        user=user,
        ttl_days=settings.session_ttl_days,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
    )
    csrf_token = generate_csrf_token(settings.session_secret_value)
    # La cookie se envía con la respuesta; si el commit se deja al teardown
    # del dependency, el navegador puede pedir /me antes de que la sesión
    # exista y recibir un 401 intermitente.
    db.commit()
    set_auth_cookies(
        response, session_token=token, csrf_token=csrf_token, settings=settings
    )
    return {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
    }


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
    settings = get_settings()
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
    # Invalida todas las sesiones (incluida la actual) y emite una nueva.
    revoke_all_sessions(db, user_id=user.id)
    token, row = create_session(
        db,
        user=user,
        ttl_days=settings.session_ttl_days,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    csrf_token = generate_csrf_token(settings.session_secret_value)
    # La cookie se envía con la respuesta; si el commit se deja al teardown
    # del dependency, el navegador puede pedir /me antes de que la sesión
    # exista y recibir un 401 intermitente.
    db.commit()
    set_auth_cookies(
        response, session_token=token, csrf_token=csrf_token, settings=settings
    )
    return {
        "user": _user_payload(user),
        "expires_at": row.expires_at,
        "csrf_token": csrf_token,
    }


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
