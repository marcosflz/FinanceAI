"""Dependencias FastAPI de autenticación y CSRF."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.session import get_db
from ..db.tenant import TenantContext, set_current_tenant
from ..models import User
from . import tenancy
from .cookies import set_session_cookie
from .keys import KeyUnwrapError
from .service import get_valid_session, touch_session
from .tokens import verify_csrf_token

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def client_ip(request: Request) -> str | None:
    """IP del cliente. No confiamos en X-Forwarded-For sin proxy explícito."""
    return request.client.host if request.client else None


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No autenticado",
        headers={"WWW-Authenticate": "Session"},
    )


def _authenticate(
    request: Request, response: Response, db: OrmSession
) -> tuple[User, TenantContext | None]:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    row = get_valid_session(db, token)
    if row is None:
        raise _unauthorized()

    try:
        dek = tenancy.session_dek(row, token)
        ctx = tenancy.context_for(row.user, dek)
    except KeyUnwrapError as exc:
        # Sesión anterior al cifrado o blob inválido: hay que volver a entrar.
        raise _unauthorized() from exc

    new_token = touch_session(db, row, ttl_days=settings.session_ttl_days)
    if new_token:
        tenancy.bind_session_key(row, dek, new_token)
        set_session_cookie(response, new_token, settings)

    tenancy.refresh_leases(db, row.user, dek)

    request.state.user = row.user
    request.state.session = row
    request.state.tenant = ctx
    return row.user, ctx


async def require_user(
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> User:
    """Valida la cookie de sesión, rota el token si toca y devuelve el usuario.

    Es ``async`` a propósito: el ``ContextVar`` del tenant solo se propaga al
    handler si se fija en la tarea de la petición (una dependencia síncrona
    corre en un hilo con una copia del contexto). El trabajo de BD/cripto se
    hace en el threadpool.
    """
    user, ctx = await run_in_threadpool(_authenticate, request, response, db)
    if ctx is not None:
        set_current_tenant(ctx)
    return user


def require_csrf(request: Request) -> None:
    """Exige cookie ``ft_csrf`` + header ``X-CSRF-Token`` en métodos unsafe."""
    if request.method.upper() not in _UNSAFE_METHODS:
        return

    settings = get_settings()
    cookie_token = request.cookies.get(settings.csrf_cookie_name)
    header_token = request.headers.get("X-CSRF-Token")
    if (
        not cookie_token
        or not header_token
        or not hmac.compare_digest(cookie_token, header_token)
        or not verify_csrf_token(settings.session_secret_value, cookie_token)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token inválido o ausente",
        )
