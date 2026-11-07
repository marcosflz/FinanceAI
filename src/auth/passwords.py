"""Hash y verificación de contraseñas con Argon2id."""

from __future__ import annotations

import secrets

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024

_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)

_dummy_hash: str | None = None


def validate_password_strength(password: str) -> None:
    """Valida la política mínima. Lanza ``ValueError`` si no cumple."""
    if not isinstance(password, str):
        raise ValueError("La contraseña debe ser texto")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(
            f"La contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres"
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("La contraseña es demasiado larga")


def hash_password(password: str) -> str:
    """Devuelve un hash Argon2id. Nunca se debe loguear el resultado."""
    validate_password_strength(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Verifica una contraseña sin filtrar el motivo del fallo."""
    if not password_hash or not isinstance(password, str):
        return False
    try:
        return bool(_hasher.verify(password_hash, password))
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return bool(_hasher.check_needs_rehash(password_hash))
    except (InvalidHashError, TypeError):
        return True


def dummy_verify(password: str) -> bool:
    """Verificación señuelo para usuarios inexistentes (timing uniforme).

    El coste es el mismo que una verificación real; el resultado siempre es
    ``False``. El hash señuelo se genera una sola vez por proceso.
    """
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = _hasher.hash(secrets.token_urlsafe(32))
    verify_password(_dummy_hash, password)
    return False
