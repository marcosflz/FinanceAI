"""Tokens opacos de sesión y tokens CSRF firmados."""

from __future__ import annotations

import hashlib
import hmac
import secrets

SESSION_TOKEN_BYTES = 32


def generate_session_token() -> str:
    """Token opaco con 32 bytes de entropía (codificado en URL-safe)."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_session_token(token: str) -> str:
    """SHA-256 hexadecimal; es lo único que se persiste en ``sessions``."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_csrf_token(secret: str) -> str:
    """Token CSRF firmado con ``SESSION_SECRET`` (cookie legible + header)."""
    raw = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    signature = hmac.new(
        secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"{raw}.{signature}"


def verify_csrf_token(secret: str, value: str | None) -> bool:
    """Comprueba la firma del token CSRF con comparación timing-safe."""
    if not value or "." not in value:
        return False
    raw, signature = value.rsplit(".", 1)
    expected = hmac.new(
        secret.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(signature, expected)
