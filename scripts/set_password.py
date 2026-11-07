"""Cambia la contraseña del admin de forma no interactiva o interactiva.

Uso:
    python -m scripts.set_password --email admin@example.com
    python -m scripts.set_password --password '...'   # solo local

Es idempotente: crea el usuario si no existe o actualiza su contraseña.
Nunca imprime el hash ni la contraseña.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.create_admin import run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cambia la contraseña del admin")
    parser.add_argument("--email", help="Email del admin (por defecto ADMIN_EMAIL)")
    parser.add_argument("--password", help="Contraseña (preferible el prompt interactivo)")
    args = parser.parse_args(argv)
    return run(
        email=args.email,
        password=args.password,
        require_password=True,
        use_env_credentials=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
