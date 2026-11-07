"""Configuración de pytest: permite importar el paquete ``src`` desde la raíz."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """SQLite temporal aislada, con categorías y cuentas sembradas."""
    from src.db.session import init_db, _session
    from src.ingest.accounts import ensure_accounts
    from src import ingest_service

    files_dir = tmp_path / "files"
    files_dir.mkdir()
    monkeypatch.setattr(ingest_service, "DATA_DIR", files_dir)
    init_db(f"sqlite:///{tmp_path / 'financial_test.db'}")
    with _session() as s:
        ensure_accounts(s)
    return tmp_path
