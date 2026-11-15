"""Enlace entre autenticación y BD por usuario.

- Al iniciar sesión se desenvuelve (o se crea, la primera vez) la DEK con la
  contraseña y se guarda envuelta con el token de la sesión.
- En cada petición se desenvuelve con el token de la cookie y se fija el
  :class:`~src.db.tenant.TenantContext`.
- Si el usuario lo ha activado (o tiene trabajos en cola), se sella la DEK
  para las claves públicas efímeras de los workers vivos (``key_leases``).

En ``TENANT_MODE=single`` todo esto es un no-op.
"""

from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy.orm import Session as OrmSession

from ..config import get_settings
from ..db.tenant import TenantContext
from ..models import CentralJob, KeyLease, Session, User, WorkerKey
from . import keys

WORKER_ALIVE_SECONDS = 120
IMPORT_LEASE_HOURS = 6
_LEASE_REFRESH_SECONDS = 300
_refresh_lock = threading.Lock()
_last_refresh: dict[int, float] = {}


def encryption_enabled() -> bool:
    settings = get_settings()
    return settings.per_user and settings.tenant_encryption


def ensure_tenant_id(user: User) -> str:
    if not user.tenant_id:
        user.tenant_id = secrets.token_hex(16)
    return user.tenant_id


def unlock_at_login(user: User, password: str) -> tuple[bytes | None, str | None]:
    """Devuelve ``(dek, recovery_key)``; ``recovery_key`` solo si se acaba de crear.

    La primera vez (usuario existente sin claves, p. ej. el admin sembrado con
    ``ADMIN_PASSWORD_HASH``) se genera la DEK: es el único momento en que el
    servidor tiene la contraseña.
    """
    settings = get_settings()
    if not settings.per_user:
        return None, None
    ensure_tenant_id(user)
    if not settings.tenant_encryption:
        return None, None
    if not user.dek_wrapped_pw:
        dek, recovery_key, material = keys.create_user_keys(user.id, password)
        user.kdf_salt = material.kdf_salt
        user.kdf_params = material.kdf_params
        user.dek_wrapped_pw = material.dek_wrapped_pw
        user.recovery_salt = material.recovery_salt
        user.dek_wrapped_recovery = material.dek_wrapped_recovery
        user.keys_created_at = datetime.utcnow()
        return dek, recovery_key
    dek = keys.unlock_with_password(
        user.id,
        password,
        kdf_salt=user.kdf_salt,
        kdf_params=user.kdf_params,
        dek_wrapped_pw=user.dek_wrapped_pw,
    )
    return dek, None


def bind_session_key(row: Session, dek: bytes | None, token: str) -> None:
    row.dek_wrapped = (
        keys.wrap_for_session(row.user_id, dek, token) if dek is not None else None
    )


def session_dek(row: Session, token: str) -> bytes | None:
    """DEK de la sesión; ``None`` si no aplica. Lanza si la sesión no la tiene."""
    if not encryption_enabled():
        return None
    if not row.dek_wrapped:
        raise keys.KeyUnwrapError("La sesión no tiene clave de datos")
    return keys.unwrap_for_session(row.user_id, row.dek_wrapped, token)


SINGLE_TENANT_ID = "single"


def context_for(user: User, dek: bytes | None) -> TenantContext | None:
    if not get_settings().per_user:
        # Modo single: contexto sin clave para saber qué usuario actúa (bots,
        # cola central). La BD sigue siendo la única configurada.
        return TenantContext(user_id=user.id, tenant_id=SINGLE_TENANT_ID, key=None)
    if not user.tenant_id:
        raise keys.KeyUnwrapError("Usuario sin tenant asignado")
    return TenantContext(user_id=user.id, tenant_id=user.tenant_id, key=dek)


def change_password_keys(user: User, dek: bytes | None, new_password: str) -> None:
    if dek is None or not encryption_enabled():
        return
    salt, params, blob = keys.wrap_for_password(user.id, dek, new_password)
    user.kdf_salt, user.kdf_params, user.dek_wrapped_pw = salt, params, blob


def rotate_recovery_key(user: User, dek: bytes) -> str:
    recovery_key, salt, blob = keys.wrap_for_recovery(user.id, dek)
    user.recovery_salt, user.dek_wrapped_recovery = salt, blob
    return recovery_key


# ── Concesiones al worker ────────────────────────────────────────────────────


def active_worker_keys(db: OrmSession, *, now: datetime | None = None) -> list[WorkerKey]:
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=WORKER_ALIVE_SECONDS)
    return db.query(WorkerKey).filter(WorkerKey.last_seen_at >= cutoff).all()


def grant_lease(
    db: OrmSession,
    user: User,
    dek: bytes,
    *,
    purpose: str,
    expires_at: datetime,
    now: datetime | None = None,
) -> int:
    """Sella la DEK para cada worker vivo. Devuelve cuántas concesiones hay."""
    granted = 0
    for worker in active_worker_keys(db, now=now):
        sealed = keys.seal_for_worker(user.id, purpose, dek, worker.public_key)
        row = (
            db.query(KeyLease)
            .filter_by(user_id=user.id, worker_key_id=worker.id, purpose=purpose)
            .first()
        )
        if row is None:
            db.add(
                KeyLease(
                    user_id=user.id,
                    worker_key_id=worker.id,
                    purpose=purpose,
                    sealed_dek=sealed,
                    expires_at=expires_at,
                    created_at=now or datetime.utcnow(),
                )
            )
        else:
            row.sealed_dek = sealed
            row.expires_at = expires_at
        granted += 1
    return granted


def revoke_leases(db: OrmSession, user_id: int, purpose: str | None = None) -> None:
    query = db.query(KeyLease).filter(KeyLease.user_id == user_id)
    if purpose:
        query = query.filter(KeyLease.purpose == purpose)
    query.delete(synchronize_session=False)


def refresh_leases(
    db: OrmSession, user: User, dek: bytes | None, *, force: bool = False
) -> None:
    """Renueva concesiones si el usuario tiene automatizaciones o trabajos.

    Se llama en cada petición autenticada, limitado a una vez cada
    ``_LEASE_REFRESH_SECONDS`` por usuario y proceso. También reactiva los
    trabajos que esperaban la clave (``waiting_unlock``).
    """
    if dek is None or not encryption_enabled():
        return
    now_mono = time.monotonic()
    with _refresh_lock:
        last = _last_refresh.get(user.id)
        if not force and last is not None and now_mono - last < _LEASE_REFRESH_SECONDS:
            return
        _last_refresh[user.id] = now_mono

    now = datetime.utcnow()
    if user.automation_until and user.automation_until > now:
        grant_lease(db, user, dek, purpose="automation", expires_at=user.automation_until, now=now)

    pending = (
        db.query(CentralJob)
        .filter(
            CentralJob.user_id == user.id,
            CentralJob.status.in_(("queued", "processing", "waiting_unlock")),
        )
        .all()
    )
    if pending:
        grant_lease(
            db,
            user,
            dek,
            purpose="import",
            expires_at=now + timedelta(hours=IMPORT_LEASE_HOURS),
            now=now,
        )
        for job in pending:
            if job.status == "waiting_unlock":
                job.status = "queued"
                job.error = None


def reset_refresh_throttle() -> None:
    with _refresh_lock:
        _last_refresh.clear()
