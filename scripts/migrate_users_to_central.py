"""Copia los usuarios de la BD única (``DATABASE_URL``) a la BD central.

Paso del corte a ``TENANT_MODE=per_user``. Solo copia la identidad y el hash
de login (email, nombre, hash Argon2id, rol, estado); no copia sesiones. Las
claves de cifrado se generan en el primer inicio de sesión de cada usuario,
que recibe entonces su clave de recuperación.

Los datos financieros **no** se copian: el SQLite de cada usuario nace vacío
(con la taxonomía por defecto de las migraciones) y la BD única queda intacta.

Uso (dentro del contenedor):

    python -m scripts.migrate_users_to_central [--dry-run]

Idempotente: un usuario que ya existe en la central (por email) se omite.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, text

from src.config import get_settings
from src.db.session import central_session
from src.models import User


def _source_url() -> str:
    url = get_settings().database_url
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def _dt(value):
    """PostgreSQL devuelve ``datetime``; SQLite, texto ISO."""
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def run(*, dry_run: bool = False) -> int:
    settings = get_settings()
    if not settings.per_user:
        raise SystemExit("Este script es para TENANT_MODE=per_user")
    if settings.central_url == settings.database_url:
        raise SystemExit("CENTRAL_DATABASE_URL debe ser distinta de DATABASE_URL")

    engine = create_engine(_source_url())
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT email, name, password_hash, role, disabled, created_at, last_login_at "
                "FROM users ORDER BY id"
            )
        ).mappings().all()
    engine.dispose()

    copied = skipped = 0
    with central_session() as db:
        for row in rows:
            email = (row["email"] or "").strip().lower()
            if db.query(User).filter(User.email == email).first() is not None:
                skipped += 1
                continue
            copied += 1
            if dry_run:
                continue
            db.add(
                User(
                    email=email,
                    name=row["name"],
                    password_hash=row["password_hash"],
                    role=row["role"] or "user",
                    disabled=bool(row["disabled"]),
                    created_at=_dt(row["created_at"]) or datetime.utcnow(),
                    last_login_at=_dt(row["last_login_at"]),
                )
            )
        if dry_run:
            db.rollback()
    verb = "se copiarían" if dry_run else "copiados"
    print(f"Usuarios {verb}: {copied}; ya existentes: {skipped}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return run(dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
