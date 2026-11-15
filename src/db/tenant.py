"""Contexto de tenant y registro de BD por usuario (``TENANT_MODE=per_user``).

El contexto (``ContextVar``) lo fija :func:`src.auth.dependencies.require_user`
en cada petición, el worker al reclamar un trabajo y el planificador al lanzar
una automatización. :func:`src.db.session._session` lo lee, así que los ~125
puntos que abren sesión no necesitan saber de tenants.

Cada BD de usuario se migra a ``head`` la primera vez que se abre en el
proceso. Los motores se cierran por LRU o inactividad: al cerrarlos la DEK deja
de estar referenciada por el pool.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..config import get_settings

logger = logging.getLogger("financial.tenant")

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class TenantContext:
    user_id: int
    tenant_id: str
    key: bytes | None = field(default=None, repr=False)

    @property
    def key_fingerprint(self) -> str | None:
        if self.key is None:
            return None
        return hashlib.sha256(b"ft-fp" + self.key).hexdigest()[:16]


_current: ContextVar[TenantContext | None] = ContextVar("ft_tenant", default=None)


def current_tenant() -> TenantContext | None:
    return _current.get()


def set_current_tenant(ctx: TenantContext | None):
    return _current.set(ctx)


@contextmanager
def use_tenant(ctx: TenantContext) -> Iterator[TenantContext]:
    """Fija el tenant para un bloque (worker, planificador, tests)."""
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


class TenantUnavailable(RuntimeError):
    """La BD del tenant no se pudo abrir (clave incorrecta o fichero dañado)."""


def tenant_root(tenant_id: str) -> Path:
    if not tenant_id or not tenant_id.isalnum():
        raise ValueError("tenant_id inválido")
    return get_settings().tenant_dir / tenant_id


def tenant_db_path(tenant_id: str) -> Path:
    return tenant_root(tenant_id) / "finance.db"


def tenant_files_dir(tenant_id: str) -> Path:
    return tenant_root(tenant_id) / "files"


# ── Migraciones ──────────────────────────────────────────────────────────────


def _alembic_config():
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    return cfg


_head_cache: str | None = None


def tenant_head_revision() -> str:
    global _head_cache
    if _head_cache is None:
        from alembic.script import ScriptDirectory

        _head_cache = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    return _head_cache


def migrate_tenant_engine(engine: Engine) -> None:
    """Lleva la BD del tenant a ``head`` (crea el esquema si está vacía)."""
    from alembic.runtime.migration import MigrationContext

    from alembic import command

    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    if current == tenant_head_revision():
        return
    cfg = _alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
    logger.info("Tenant migrado de %s a %s", current, tenant_head_revision())


# ── Registro de motores ──────────────────────────────────────────────────────


@dataclass
class _Entry:
    engine: Engine
    factory: sessionmaker
    fingerprint: str | None
    last_used: float


class TenantRegistry:
    def __init__(self) -> None:
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._lock = threading.RLock()
        self._open_locks: dict[str, threading.Lock] = {}

    def factory_for(self, ctx: TenantContext) -> sessionmaker:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(ctx.tenant_id)
            if entry is not None and entry.fingerprint == ctx.key_fingerprint:
                entry.last_used = now
                self._entries.move_to_end(ctx.tenant_id)
                return entry.factory
            open_lock = self._open_locks.setdefault(ctx.tenant_id, threading.Lock())

        with open_lock:
            with self._lock:
                entry = self._entries.get(ctx.tenant_id)
                if entry is not None and entry.fingerprint == ctx.key_fingerprint:
                    entry.last_used = now
                    return entry.factory
                if entry is not None:
                    # Otra clave (p. ej. tras recuperar la cuenta): reabrir.
                    self._dispose(ctx.tenant_id)
            entry = self._open(ctx)
            with self._lock:
                self._entries[ctx.tenant_id] = entry
                self._evict(now)
            return entry.factory

    def _open(self, ctx: TenantContext) -> _Entry:
        from .session import _create_engine

        settings = get_settings()
        if settings.tenant_encryption and ctx.key is None:
            raise TenantUnavailable("Falta la clave de la BD del usuario")
        path = tenant_db_path(ctx.tenant_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tenant_files_dir(ctx.tenant_id).mkdir(parents=True, exist_ok=True)
        key = ctx.key if settings.tenant_encryption else None
        engine = _create_engine(f"sqlite:///{path}", key=key)
        try:
            migrate_tenant_engine(engine)
        except Exception as exc:
            engine.dispose()
            raise TenantUnavailable(
                f"No se pudo abrir la BD del usuario: {type(exc).__name__}"
            ) from exc
        factory = sessionmaker(
            bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
        )
        return _Entry(engine, factory, ctx.key_fingerprint, time.monotonic())

    def _evict(self, now: float) -> None:
        settings = get_settings()
        idle = settings.tenant_idle_seconds
        for tenant_id, entry in list(self._entries.items()):
            if now - entry.last_used > idle:
                self._dispose(tenant_id)
        while len(self._entries) > settings.tenant_cache_size:
            oldest = next(iter(self._entries))
            self._dispose(oldest)

    def _dispose(self, tenant_id: str) -> None:
        entry = self._entries.pop(tenant_id, None)
        if entry is not None:
            entry.engine.dispose()

    def close(self, tenant_id: str) -> None:
        with self._lock:
            self._dispose(tenant_id)

    def close_idle(self) -> None:
        with self._lock:
            self._evict(time.monotonic())

    def close_all(self) -> None:
        with self._lock:
            for tenant_id in list(self._entries):
                self._dispose(tenant_id)

    def open_count(self) -> int:
        with self._lock:
            return len(self._entries)


registry = TenantRegistry()


def engine_for(ctx: TenantContext) -> Engine:
    return registry.factory_for(ctx).kw["bind"]
