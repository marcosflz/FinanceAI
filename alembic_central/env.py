"""Entorno Alembic de la BD central."""

import importlib.util
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

from alembic import context

load_dotenv()

config = context.config
_external_connection = config.attributes.get("connection")

if config.config_file_name is not None and _external_connection is None:
    fileConfig(config.config_file_name)

url = os.getenv("CENTRAL_DATABASE_URL") or os.getenv("DATABASE_URL")
if url and _external_connection is None:
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    config.set_main_option("sqlalchemy.url", url)

_MODELS = Path(__file__).resolve().parents[1] / "src" / "models.py"
spec = importlib.util.spec_from_file_location("central_models_env", _MODELS)
mod = importlib.util.module_from_spec(spec)
sys.modules["central_models_env"] = mod
spec.loader.exec_module(mod)
target_metadata = mod.CentralBase.metadata

VERSION_TABLE = config.get_main_option("version_table") or "alembic_version_central"


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if _external_connection is not None:
        _run(_external_connection)
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        _run(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
