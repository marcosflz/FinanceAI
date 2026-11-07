"""Dependencias FastAPI de autenticación y CSRF."""

from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.session import get_db
from ..models import User
from .cookies import set_session_cookie
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


def require_user(
    request: Request,
    response: Response,
    db: OrmSession = Depends(get_db),
) -> User:
    """Valida la cookie de sesión, rota el token si toca y devuelve el usuario."""
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    row = get_valid_session(db, token)
    if row is None:
        raise _unauthorized()

    new_token = touch_session(db, row, ttl_days=settings.session_ttl_days)
    if new_token:
        set_session_cookie(response, new_token, settings)

    request.state.user = row.user
    request.state.session = row
    return row.user


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
