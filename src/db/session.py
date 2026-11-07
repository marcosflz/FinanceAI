"""Motor y sesiones de base de datos.

PostgreSQL es el camino de producción (``postgresql+psycopg://`` con pool
dimensionado). SQLite queda para desarrollo y tests, con WAL y
``busy_timeout``. No se usa ``StaticPool``: una única conexión compartida
entre hilos era la causa de bloqueos con los jobs en background.

``init_db()`` solo crea tablas y siembra datos en desarrollo/test. En
producción el esquema debe venir de ``alembic upgrade head``.
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
from ..models import AppConfig, Base, Categoria, Subtipo

_session_factory: sessionmaker | None = None
_engine: Engine | None = None
_engine_url: str | None = None
_lock = threading.RLock()

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


def _create_engine(url: str) -> Engine:
    url = _normalise_url(url)
    if url.startswith("sqlite"):
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
    """Libera el engine cacheado. Útil en tests y cambios de DATABASE_URL."""
    global _engine, _engine_url, _session_factory
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _engine_url = None
        _session_factory = None


# Alias usado por algunos tests/scripts.
dispose_engine = reset_engine


@contextmanager
def session_scope(db_url: str | None = None):
    """Context manager transaccional: commit al salir, rollback si hay error.

    Sin ``db_url`` reutiliza el factory ya inicializado (compatibilidad con
    ``init_db("sqlite:///...")``); si no existe, lo crea desde la config.
    """
    with _lock:
        existing_factory = _session_factory
    factory = (
        existing_factory
        if db_url is None and existing_factory is not None
        else get_sessionmaker(db_url)
    )
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Compatibilidad con el resto del repo (CRUDs y jobs).
@contextmanager
def _session():
    with session_scope() as session:
        yield session


def get_db():
    """Dependencia FastAPI: sesión con commit/rollback automático."""
    with session_scope() as session:
        yield session


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

    engine = get_engine(db_url)
    if create_all:
        Base.metadata.create_all(engine)
    if not settings.is_production:
        _run_legacy_compat_migrations(engine)

    # Fuerza la creación del factory con el engine actual.
    get_sessionmaker(db_url)

    if seed:
        inspector = sa_inspect(engine)
        tables = set(inspector.get_table_names())
        if {"categorias", "subtipos", "app_config"} <= tables:
            _seed_defaults()
