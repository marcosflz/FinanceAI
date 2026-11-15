"""Jerarquía de claves zero-knowledge.

- **DEK** (32 bytes aleatorios): clave raw de SQLCipher del SQLite del usuario y
  raíz de las subclaves de ficheros. No cambia al cambiar la contraseña.
- **KEK** = Argon2id(contraseña, sal propia). Distinta del ``password_hash`` de
  login: verificar la contraseña no permite descifrar nada.
- La BD central solo guarda la DEK *envuelta* (AES-256-GCM) con:
  la KEK, la clave de recuperación, el token en claro de cada sesión (solo se
  persiste su hash) y la clave pública efímera de cada worker.

El AAD de cada envoltura incluye el id de usuario y el propósito, de modo que
un blob copiado de otro usuario o de otro uso no se puede desenvolver.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from dataclasses import dataclass

from argon2.low_level import Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

DEK_BYTES = 32
_WRAP_VERSION = "v1"

# Mismos parámetros que el hash de login (src/auth/passwords.py): ~64 MiB.
DEFAULT_KDF_PARAMS = {"alg": "argon2id", "t": 3, "m": 65536, "p": 4}


class KeyUnwrapError(Exception):
    """La clave no desenvuelve el blob (contraseña/token/clave incorrectos)."""


@dataclass(frozen=True)
class UserKeyMaterial:
    """Lo que se persiste en ``users`` al crear las claves de un usuario."""

    kdf_salt: str
    kdf_params: str
    dek_wrapped_pw: str
    recovery_salt: str
    dek_wrapped_recovery: str


def _b64e(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64d(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _hkdf(material: bytes, *, info: str, salt: bytes | None = None) -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=salt, info=info.encode()
    ).derive(material)


def wrap(key: bytes, plaintext: bytes, *, aad: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad.encode())
    return f"{_WRAP_VERSION}.{_b64e(nonce + ct)}"


def unwrap(key: bytes, blob: str, *, aad: str) -> bytes:
    try:
        version, payload = blob.split(".", 1)
    except (AttributeError, ValueError) as exc:
        raise KeyUnwrapError("Blob de clave mal formado") from exc
    if version != _WRAP_VERSION:
        raise KeyUnwrapError("Versión de blob de clave no soportada")
    raw = _b64d(payload)
    try:
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad.encode())
    except InvalidTag as exc:
        raise KeyUnwrapError("No se pudo desenvolver la clave") from exc


# ── KEK de contraseña ────────────────────────────────────────────────────────


def derive_kek(password: str, salt: bytes, params: dict | None = None) -> bytes:
    p = params or DEFAULT_KDF_PARAMS
    if p.get("alg") != "argon2id":
        raise KeyUnwrapError("KDF no soportado")
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=int(p["t"]),
        memory_cost=int(p["m"]),
        parallelism=int(p["p"]),
        hash_len=32,
        type=Type.ID,
    )


def _aad_pw(user_id: int) -> str:
    return f"ft:user:{user_id}:pw"


def _aad_recovery(user_id: int) -> str:
    return f"ft:user:{user_id}:recovery"


def _aad_session(user_id: int) -> str:
    return f"ft:user:{user_id}:session"


def _aad_lease(user_id: int, purpose: str) -> str:
    return f"ft:user:{user_id}:lease:{purpose}"


# ── Clave de recuperación ────────────────────────────────────────────────────

_RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O/1/I


def generate_recovery_key() -> str:
    """Clave legible de ~160 bits: 8 grupos de 4 caracteres."""
    chars = "".join(secrets.choice(_RECOVERY_ALPHABET) for _ in range(32))
    return "-".join(chars[i : i + 4] for i in range(0, 32, 4))


def normalise_recovery_key(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _recovery_kek(recovery_key: str, salt: bytes) -> bytes:
    normalised = normalise_recovery_key(recovery_key)
    if len(normalised) != 32:
        raise KeyUnwrapError("Clave de recuperación con formato incorrecto")
    # La clave tiene ~160 bits de entropía: HKDF basta, no hace falta Argon2.
    return _hkdf(normalised.encode(), info="ft-recovery-kek", salt=salt)


# ── Operaciones de usuario ───────────────────────────────────────────────────


def create_user_keys(user_id: int, password: str) -> tuple[bytes, str, UserKeyMaterial]:
    """Genera DEK + envolturas. Devuelve ``(dek, recovery_key, material)``.

    La clave de recuperación solo existe en claro en el valor devuelto: hay
    que mostrarla una vez al usuario y olvidarla.
    """
    dek = os.urandom(DEK_BYTES)
    salt = os.urandom(16)
    kek = derive_kek(password, salt)
    recovery_key = generate_recovery_key()
    recovery_salt = os.urandom(16)
    material = UserKeyMaterial(
        kdf_salt=_b64e(salt),
        kdf_params=json.dumps(DEFAULT_KDF_PARAMS, sort_keys=True),
        dek_wrapped_pw=wrap(kek, dek, aad=_aad_pw(user_id)),
        recovery_salt=_b64e(recovery_salt),
        dek_wrapped_recovery=wrap(
            _recovery_kek(recovery_key, recovery_salt), dek, aad=_aad_recovery(user_id)
        ),
    )
    return dek, recovery_key, material


def unlock_with_password(
    user_id: int, password: str, *, kdf_salt: str, kdf_params: str, dek_wrapped_pw: str
) -> bytes:
    kek = derive_kek(password, _b64d(kdf_salt), json.loads(kdf_params))
    return unwrap(kek, dek_wrapped_pw, aad=_aad_pw(user_id))


def wrap_for_password(user_id: int, dek: bytes, password: str) -> tuple[str, str, str]:
    """Re-envuelve la DEK con una contraseña nueva: ``(salt, params, blob)``."""
    salt = os.urandom(16)
    kek = derive_kek(password, salt)
    return (
        _b64e(salt),
        json.dumps(DEFAULT_KDF_PARAMS, sort_keys=True),
        wrap(kek, dek, aad=_aad_pw(user_id)),
    )


def unlock_with_recovery(
    user_id: int, recovery_key: str, *, recovery_salt: str, dek_wrapped_recovery: str
) -> bytes:
    kek = _recovery_kek(recovery_key, _b64d(recovery_salt))
    return unwrap(kek, dek_wrapped_recovery, aad=_aad_recovery(user_id))


def wrap_for_recovery(user_id: int, dek: bytes) -> tuple[str, str, str]:
    """Nueva clave de recuperación: ``(recovery_key, salt, blob)``."""
    recovery_key = generate_recovery_key()
    salt = os.urandom(16)
    blob = wrap(_recovery_kek(recovery_key, salt), dek, aad=_aad_recovery(user_id))
    return recovery_key, _b64e(salt), blob


# ── Sesión web ───────────────────────────────────────────────────────────────


def _session_key(session_token: str) -> bytes:
    return _hkdf(session_token.encode(), info="ft-session-dek")


def wrap_for_session(user_id: int, dek: bytes, session_token: str) -> str:
    return wrap(_session_key(session_token), dek, aad=_aad_session(user_id))


def unwrap_for_session(user_id: int, blob: str, session_token: str) -> bytes:
    return unwrap(_session_key(session_token), blob, aad=_aad_session(user_id))


# ── Concesiones al worker (ECIES X25519) ─────────────────────────────────────


def generate_worker_keypair() -> tuple[X25519PrivateKey, str]:
    private = X25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return private, _b64e(public)


def seal_for_worker(user_id: int, purpose: str, dek: bytes, worker_public_b64: str) -> str:
    recipient = X25519PublicKey.from_public_bytes(_b64d(worker_public_b64))
    ephemeral = X25519PrivateKey.generate()
    shared = ephemeral.exchange(recipient)
    eph_pub = ephemeral.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    key = _hkdf(shared, info="ft-worker-lease", salt=eph_pub)
    return f"{_b64e(eph_pub)}:{wrap(key, dek, aad=_aad_lease(user_id, purpose))}"


def open_sealed(
    user_id: int, purpose: str, sealed: str, worker_private: X25519PrivateKey
) -> bytes:
    try:
        eph_b64, blob = sealed.split(":", 1)
        eph_pub = _b64d(eph_b64)
        shared = worker_private.exchange(X25519PublicKey.from_public_bytes(eph_pub))
    except (ValueError, TypeError) as exc:
        raise KeyUnwrapError("Concesión mal formada") from exc
    key = _hkdf(shared, info="ft-worker-lease", salt=eph_pub)
    return unwrap(key, blob, aad=_aad_lease(user_id, purpose))


# ── Subclaves ────────────────────────────────────────────────────────────────


def file_key(dek: bytes) -> bytes:
    """Subclave para cifrar ficheros del usuario (extractos, cachés)."""
    return _hkdf(dek, info="ft-files")
