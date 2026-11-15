import os
import importlib.util
import sys
from logging.config import fileConfig
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

# Permite que `alembic upgrade head` use el mismo .env que la app en local.
load_dotenv()

config = context.config

# La app migra cada BD de usuario al abrirla pasando su conexión (ya con la
# clave SQLCipher aplicada) en ``config.attributes["connection"]``. En ese caso
# no se toca el logging de la app ni ``DATABASE_URL``.
_external_connection = config.attributes.get("connection")

if config.config_file_name is not None and _external_connection is None:
    fileConfig(config.config_file_name)

url = os.getenv("DATABASE_URL")
if url and _external_connection is None:
    config.set_main_option("sqlalchemy.url", url)

_MODELS = Path(__file__).resolve().parents[1] / "src" / "models.py"
spec = importlib.util.spec_from_file_location("models", _MODELS)
mod = importlib.util.module_from_spec(spec)
sys.modules["models"] = mod
spec.loader.exec_module(mod)
target_metadata = mod.Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if _external_connection is not None:
        context.configure(
            connection=_external_connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
