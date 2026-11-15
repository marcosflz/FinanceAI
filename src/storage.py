"""Almacenamiento de ficheros del usuario (extractos y cachés de extracción).

En ``TENANT_MODE=per_user`` los ficheros viven en
``TENANT_DIR/<tenant>/files`` y, con cifrado activo, se guardan con AES-256-GCM
usando una subclave de la DEK (:func:`src.auth.keys.file_key`). Para procesarlos
se descifran a un temporal (montar ``/tmp`` como tmpfs en producción) que se
borra al terminar.

En modo ``single`` es un ``shutil.copy2`` de toda la vida.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .auth.keys import file_key
from .config import get_settings
from .db.tenant import current_tenant, tenant_files_dir

MAGIC = b"FTENC1\n"


def files_dir(default: Path) -> Path:
    """Directorio de ficheros del tenant actual (o ``default`` en modo single)."""
    settings = get_settings()
    if not settings.per_user:
        return default
    ctx = current_tenant()
    if ctx is None:
        raise RuntimeError("Acceso a ficheros sin tenant en TENANT_MODE=per_user")
    path = tenant_files_dir(ctx.tenant_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _key() -> bytes | None:
    settings = get_settings()
    if not (settings.per_user and settings.tenant_encryption):
        return None
    ctx = current_tenant()
    if ctx is None or ctx.key is None:
        raise RuntimeError("Falta la clave del usuario para cifrar ficheros")
    return file_key(ctx.key)


def _aad(path: Path) -> bytes:
    # Ligado al nombre: un fichero renombrado/intercambiado no se descifra.
    return path.name.encode()


def is_encrypted(path: Path) -> bool:
    try:
        with open(path, "rb") as fh:
            return fh.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def write_bytes(dest: Path, data: bytes) -> None:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    key = _key()
    if key is not None:
        nonce = os.urandom(12)
        data = MAGIC + nonce + AESGCM(key).encrypt(nonce, data, _aad(dest))
    tmp = dest.with_name(dest.name + ".tmp")
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dest)


def read_bytes(path: Path) -> bytes:
    path = Path(path)
    raw = path.read_bytes()
    if not raw.startswith(MAGIC):
        return raw
    key = _key()
    if key is None:
        raise RuntimeError("Fichero cifrado sin clave disponible")
    body = raw[len(MAGIC) :]
    return AESGCM(key).decrypt(body[:12], body[12:], _aad(path))


def store_copy(src: str | Path, dest: Path) -> None:
    """Copia ``src`` (en claro) a ``dest`` cifrando si procede."""
    if _key() is None:
        shutil.copy2(src, dest)
        return
    write_bytes(dest, Path(src).read_bytes())


@contextmanager
def plaintext_path(path: str | Path) -> Iterator[str]:
    """Ruta legible por parsers (pdfplumber, openpyxl…) para un fichero guardado."""
    path = Path(path)
    if not is_encrypted(path):
        yield str(path)
        return
    data = read_bytes(path)
    fd, tmp = tempfile.mkstemp(prefix="ft-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        yield tmp
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
