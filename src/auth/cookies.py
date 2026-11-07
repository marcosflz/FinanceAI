"""Cookies de sesión y CSRF con flags seguros."""

from __future__ import annotations

from fastapi import Response

from ..config import Settings


def set_session_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=settings.cookie_secure_effective,
        samesite="lax",
        path="/",
    )


def set_csrf_cookie(response: Response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=settings.cookie_secure_effective,
        samesite="lax",
        path="/",
    )


def set_auth_cookies(
    response: Response, *, session_token: str, csrf_token: str, settings: Settings
) -> None:
    set_session_cookie(response, session_token, settings)
    set_csrf_cookie(response, csrf_token, settings)


def clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        secure=settings.cookie_secure_effective,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        key=settings.csrf_cookie_name,
        path="/",
        secure=settings.cookie_secure_effective,
        httponly=False,
        samesite="lax",
    )
