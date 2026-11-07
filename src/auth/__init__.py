"""Autenticación single-user: Argon2id, sesiones opacas y CSRF.

El paquete no depende de FastAPI para poder reutilizarse desde scripts
(``create_admin.py``). Las dependencias HTTP viven en ``dependencies.py``.
"""

from .passwords import (
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from .tokens import (
    generate_csrf_token,
    generate_session_token,
    hash_session_token,
    verify_csrf_token,
)

__all__ = [
    "hash_password",
    "needs_rehash",
    "verify_password",
    "validate_password_strength",
    "generate_csrf_token",
    "generate_session_token",
    "hash_session_token",
    "verify_csrf_token",
]
