"""Motor y sesiones de base de datos.

Dos modos (``TENANT_MODE``):

- ``single`` (histórico): una sola BD (``DATABASE_URL``) con datos y auth.
- ``per_user``: BD central (``CENTRAL_DATABASE_URL``: users, sessions, cola,
  concesiones) + un SQLite (SQLCipher) por usuario. ``_session()`` resuelve el
  tenant del :mod:`contexto actual <src.db.tenant>`; sin contexto falla en vez
  de caer en una BD por defecto.

SQLite usa WAL y ``busy_timeout``. No se usa ``StaticPool``: una única
conexión compartida entre hilos era la causa de bloqueos con los jobs en
background.

``init_db()`` solo crea tablas y siembra datos en desarrollo/test. En
producción el esquema debe venir de Alembic (central en el entrypoint, tenant
al abrir cada BD de usuario).
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from ..config import get_settings
from ..models import AppConfig, Base, Categoria, CentralBase, Subtipo

_session_factory: sessionmaker | None = None
_engine: Engine | None = None
_engine_url: str | None = None
_central_engine: Engine | None = None
_central_url: str | None = None
_central_factory: sessionmaker | None = None
_lock = threading.RLock()


class NoTenantContext(RuntimeError):
    """Acceso a datos sin usuario/tenant en modo ``per_user``."""

_DEFAULT_CATEGORIAS = [
    "Vivienda",
    "Alimentación",
    "Transporte",
    "Servicios",
    "Telecomunicaciones",
    "Salud",
    "Ocio",
    "Compras",
    "Salario",
    "Inversiones",
    "Transferencias",
    "Otros",
]

_DEFAULT_APP_CONFIG = {
    "subtipo_gasto_fijo": "Alquiler, hipoteca, suscripciones periódicas, seguros, cuotas fijas",
    "subtipo_gasto_variable": "Supermercado, restaurantes, ocio, transporte puntual, compras espoádicas",
    "subtipo_gasto_inversion": "Aportación a fondos, ETFs, acciones, planes de pensión, criptoactivos",
    "subtipo_ingreso_nomina": "Sueldo, salario, remuneración laboral, paga extra",
    "subtipo_ingreso_variable": "Honorarios, bonificaciones, devoluciones, cashback, premios",
    "subtipo_ingreso_inversion": "Dividendos, intereses, rendimientos de activos financieros",
}

_DEFAULT_SUBTIPOS = [
    {
        "nombre": "fijo",
        "tipo": "gasto",
        "descripcion": "Alquiler, hipoteca, suscripciones periódicas, seguros, cuotas fijas",
    },
    {
        "nombre": "variable",
        "tipo": "gasto",
        "descripcion": "Supermercado, restaurantes, ocio, transporte puntual, compras esporádicas",
    },
    {
        "nombre": "inversion",
        "tipo": "gasto",
        "descripcion": "Aportación a fondos, ETFs, acciones, planes de pensión, criptoactivos",
    },
    {
        "nombre": "nomina",
        "tipo": "ingreso",
        "descripcion": "Sueldo, salario, remuneración laboral, paga extra",
    },
    {
        "nombre": "variable",
        "tipo": "ingreso",
        "descripcion": "Honorarios, bonificaciones, devoluciones, cashback, premios",
    },
    {
        "nombre": "inversion",
        "tipo": "ingreso",
        "descripcion": "Dividendos, intereses, rendimientos de activos financieros",
    },
]


def _resolve_database_url(db_url: str | None = None) -> str:
    """Prioriza la URL explícita, luego el entorno y por último la config."""
    if db_url:
        return str(db_url)
    env_url = os.getenv("DATABASE_URL")
    if env_url:
        return env_url
    return get_settings().database_url


def _normalise_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def _sqlcipher_creator(path: str, key: bytes):
    """Conexiones SQLCipher con la clave aplicada antes que cualquier otra cosa."""
    import sqlcipher3

    hex_key = key.hex()

    def connect():
        conn = sqlcipher3.dbapi2.connect(path, check_same_thread=False, timeout=30)
        conn.execute("PRAGMA cipher_log_level = NONE")
        conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
        return conn

    return connect


def _create_engine(url: str, *, key: bytes | None = None) -> Engine:
    url = _normalise_url(url)
    if url.startswith("sqlite"):
        if key is not None:
            import sqlcipher3

            path = url.split(":///", 1)[1]
            # La URL con ruta hace que SQLAlchemy elija el pool de fichero
            # (``sqlite://`` sería memoria → SingletonThreadPool).
            engine = create_engine(
                url,
                creator=_sqlcipher_creator(path, key),
                module=sqlcipher3.dbapi2,
                pool_pre_ping=True,
            )
        else:
            engine = create_engine(
                url,
                connect_args={"check_same_thread": False, "timeout": 30},
                pool_pre_ping=True,
            )

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            try:
                # WAL no aplica a bases en memoria; el PRAGMA es inofensivo.
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

        return engine

    kwargs: dict = {"pool_pre_ping": True, "pool_recycle": 1800}
    if url.startswith("postgresql+psycopg"):
        kwargs.update({"pool_size": 10, "max_overflow": 20})
    return create_engine(url, **kwargs)


def get_engine(db_url: str | None = None) -> Engine:
    """Devuelve (y cachea) el engine para la URL configurada."""
    global _engine, _engine_url
    url = _normalise_url(_resolve_database_url(db_url))
    with _lock:
        if _engine is not None and _engine_url == url:
            return _engine
        if _engine is not None:
            _engine.dispose()
        _engine = _create_engine(url)
        _engine_url = url
        return _engine


def get_sessionmaker(db_url: str | None = None) -> sessionmaker:
    """Devuelve el session factory ligado al engine actual."""
    global _session_factory
    engine = get_engine(db_url)
    with _lock:
        if _session_factory is None or _session_factory.kw.get("bind") is not engine:
            _session_factory = sessionmaker(
                bind=engine,
                autoflush=False,
                autocommit=False,
                expire_on_commit=False,
            )
        return _session_factory


def reset_engine() -> None:
    """Libera los engines cacheados. Útil en tests y cambios de DATABASE_URL."""
    global _engine, _engine_url, _session_factory
    global _central_engine, _central_url, _central_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        if _central_engine is not None and _central_engine is not _engine:
            _central_engine.dispose()
        _engine = None
        _engine_url = None
        _session_factory = None
        _central_engine = None
        _central_url = None
        _central_factory = None
    from .tenant import registry

    registry.close_all()


def get_central_engine() -> Engine:
    """Engine de la BD central.

    En modo ``single`` sin ``CENTRAL_DATABASE_URL`` es el mismo engine de
    datos (la BD que haya activado ``init_db``/``get_engine``).
    """
    global _central_engine, _central_url
    settings = get_settings()
    if not settings.per_user and not settings.central_database_url:
        with _lock:
            if _engine is not None:
                return _engine
        return get_engine()
    url = _normalise_url(settings.central_url)
    with _lock:
        if _central_engine is not None and _central_url == url:
            return _central_engine
        if _central_engine is not None and _central_engine is not _engine:
            _central_engine.dispose()
        _central_engine = _create_engine(url)
        _central_url = url
        return _central_engine


def get_central_sessionmaker() -> sessionmaker:
    global _central_factory
    engine = get_central_engine()
    with _lock:
        if _central_factory is None or _central_factory.kw.get("bind") is not engine:
            _central_factory = sessionmaker(
                bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
            )
        return _central_factory


# Alias usado por algunos tests/scripts.
dispose_engine = reset_engine


@contextmanager
def session_scope(db_url: str | None = None):
    """Context manager transaccional: commit al salir, rollback si hay error.

    Sin ``db_url`` reutiliza el factory ya inicializado (compatibilidad con
    ``init_db("sqlite:///...")``); si no existe, lo crea desde la config.
    """
    session = _resolve_factory(db_url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def _resolve_factory(db_url: str | None) -> sessionmaker:
    """URL explícita > tenant del contexto > BD única (modo ``single``)."""
    if db_url is not None:
        return get_sessionmaker(db_url)
    settings = get_settings()
    if settings.per_user:
        from .tenant import current_tenant, registry

        ctx = current_tenant()
        if ctx is None:
            raise NoTenantContext(
                "Acceso a datos sin tenant en TENANT_MODE=per_user"
            )
        return registry.factory_for(ctx)
    with _lock:
        existing_factory = _session_factory
    return existing_factory if existing_factory is not None else get_sessionmaker()


# Compatibilidad con el resto del repo (CRUDs y jobs).
@contextmanager
def _session():
    with session_scope() as session:
        yield session


@contextmanager
def central_session():
    """Sesión transaccional sobre la BD central (auth, cola, concesiones)."""
    session = get_central_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_central_db():
    """Dependencia FastAPI: sesión central con commit/rollback automático."""
    with central_session() as session:
        yield session


# Las rutas de auth/health usan la BD central.
get_db = get_central_db


def _run_legacy_compat_migrations(engine: Engine) -> None:
    """Ajustes ad-hoc heredados, solo en desarrollo y con guards."""
    inspector = sa_inspect(engine)
    tables = set(inspector.get_table_names())

    if "movimientos" in tables:
        cols = {c["name"] for c in inspector.get_columns("movimientos")}
        if "subtipo" not in cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE movimientos ADD COLUMN subtipo VARCHAR(50)"))
                if "tipo_gasto" in cols:
                    conn.execute(text("UPDATE movimientos SET subtipo = tipo_gasto"))
                conn.commit()
        if "descripcion_llm" not in cols:
            with engine.connect() as conn:
                conn.execute(
                    text("ALTER TABLE movimientos ADD COLUMN descripcion_llm VARCHAR(1000)")
                )
                conn.commit()

    if "operaciones" in tables:
        op_cols = {c["name"] for c in inspector.get_columns("operaciones")}
        if "moneda" not in op_cols:
            with engine.connect() as conn:
                conn.execute(text("ALTER TABLE operaciones ADD COLUMN moneda VARCHAR(10)"))
                conn.commit()
        if "movimiento_id" not in op_cols:
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE operaciones ADD COLUMN movimiento_id INTEGER "
                        "REFERENCES movimientos(id) ON DELETE SET NULL"
                    )
                )
                conn.commit()


def _seed_defaults() -> None:
    """Siembra categorías, subtipos y app_config de forma idempotente."""
    with _session() as session:
        if session.query(Categoria).count() == 0:
            for nombre in _DEFAULT_CATEGORIAS:
                session.add(Categoria(nombre=nombre))

    with _session() as session:
        for key, value in _DEFAULT_APP_CONFIG.items():
            if not session.query(AppConfig).filter_by(key=key).first():
                session.add(AppConfig(key=key, value=value))

    with _session() as session:
        if session.query(Subtipo).count() == 0:
            for subtipo in _DEFAULT_SUBTIPOS:
                session.add(Subtipo(**subtipo))


def init_db(
    db_url: str | None = None,
    *,
    create_all: bool | None = None,
    seed: bool | None = None,
) -> None:
    """Inicializa la base de datos.

    En producción no ejecuta ``create_all`` ni seeds por defecto: el
    entrypoint aplica las migraciones de Alembic. En desarrollo/test se
    mantiene el comportamiento histórico para no romper scripts locales.
    """
    settings = get_settings()
    if create_all is None:
        create_all = not settings.is_production
    if seed is None:
        seed = not settings.is_production

    if settings.per_user and db_url is None:
        # Los tenants se crean/migran al abrirse; aquí solo la BD central.
        if create_all:
            CentralBase.metadata.create_all(get_central_engine())
        return

    engine = get_engine(db_url)
    if create_all:
        Base.metadata.create_all(engine)
        central = get_central_engine()
        CentralBase.metadata.create_all(central)
    if not settings.is_production:
        _run_legacy_compat_migrations(engine)

    # Fuerza la creación del factory con el engine actual.
    get_sessionmaker(db_url)

    if seed:
        inspector = sa_inspect(engine)
        tables = set(inspector.get_table_names())
        if {"categorias", "subtipos", "app_config"} <= tables:
            _seed_defaults()
