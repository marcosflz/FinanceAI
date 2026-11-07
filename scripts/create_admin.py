"""Crea o actualiza el usuario administrador.

Uso recomendado (no deja la contraseña en el historial):

    python -m scripts.create_admin

También acepta variables de entorno ``ADMIN_EMAIL`` y
``ADMIN_PASSWORD_HASH`` (o ``ADMIN_PASSWORD`` solo para entornos locales).
Nunca imprime el hash ni la contraseña.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

# Permite ejecutar tanto `python -m scripts.create_admin` como
# `python scripts/create_admin.py` desde la raíz del repo.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.auth.passwords import hash_password, validate_password_strength
from src.auth.service import upsert_admin
from src.config import get_settings
from src.db.session import _session, init_db


def _resolve_password(
    *,
    password: str | None,
    password_hash: str | None,
    require_password: bool,
    allow_env_password: bool = True,
) -> str | None:
    if password_hash:
        if not password_hash.startswith("$argon2"):
            raise SystemExit("ADMIN_PASSWORD_HASH no parece un hash Argon2 válido")
        return password_hash
    if password:
        validate_password_strength(password)
        return hash_password(password)

    env_password = os.getenv("ADMIN_PASSWORD") if allow_env_password else None
    if env_password:
        validate_password_strength(env_password)
        return hash_password(env_password)

    if require_password:
        first = getpass.getpass("Nueva contraseña: ")
        second = getpass.getpass("Repite la contraseña: ")
        if first != second:
            raise SystemExit("Las contraseñas no coinciden")
        validate_password_strength(first)
        return hash_password(first)

    # Sin contraseña: si el usuario ya existe, se deja intacta.
    return None


def run(
    *,
    email: str | None = None,
    password: str | None = None,
    password_hash: str | None = None,
    require_password: bool = False,
    use_env_credentials: bool = True,
) -> int:
    settings = get_settings()
    resolved_email = (email or settings.admin_email or "").strip().lower()
    if not resolved_email:
        raise SystemExit(
            "Falta el email: usa --email o configura ADMIN_EMAIL en el entorno/.env"
        )
    env_hash = settings.admin_password_hash_value if use_env_credentials else None
    resolved_hash = _resolve_password(
        password=password or None,
        password_hash=password_hash or env_hash,
        require_password=require_password,
        allow_env_password=use_env_credentials,
    )

    init_db()
    with _session() as session:
        user, created = upsert_admin(
            session, email=resolved_email, password_hash=resolved_hash
        )
        user_id = user.id

    action = "creado" if created else "actualizado"
    print(f"Admin {action}: {resolved_email} (id={user_id})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crea o actualiza el admin")
    parser.add_argument("--email", help="Email del admin (por defecto ADMIN_EMAIL)")
    parser.add_argument(
        "--password",
        help="Contraseña en línea de comandos (menos seguro; preferible el prompt)",
    )
    parser.add_argument(
        "--password-hash",
        help="Hash Argon2id ya calculado (por defecto ADMIN_PASSWORD_HASH)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return run(email=args.email, password=args.password, password_hash=args.password_hash)


if __name__ == "__main__":
    raise SystemExit(main())
