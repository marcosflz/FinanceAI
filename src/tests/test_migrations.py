"""Tests de migraciones Alembic sobre SQLite temporal (nunca financial.db)."""

from __future__ import annotations

import os
import re
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HEAD = "v3_013_import_portfolio"


def _run_alembic(db_path: Path, *args: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    command = [sys.executable, "-m", "alembic", *(args or ("upgrade", "head"))]
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _tables(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }


def _columns(db_path: Path, table: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _column_length(db_path: Path, table: str, column: str) -> int | None:
    with sqlite3.connect(db_path) as conn:
        for row in conn.execute(f"PRAGMA table_info({table})"):
            if row[1] == column:
                match = re.search(r"\((\d+)\)", row[2] or "")
                return int(match.group(1)) if match else None
    return None


def _revision(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _assert_foundation_schema(db_path: Path) -> None:
    assert _revision(db_path) == HEAD
    tables = _tables(db_path)
    assert {
        "users",
        "sessions",
        "login_attempts",
        "account_balance_snapshots",
        "financial_movements",
        "normalized_events",
        "source_files",
        "account_currency_balances",
        "portfolio_snapshots",
        "portfolio_snapshot_positions",
        "asset_opening_positions",
    } <= tables
    assert {
        "mime_type",
        "page_count",
        "account_id",
        "balance_start",
        "balance_end",
        "balance_start_date",
        "extraction_meta",
        "queued_at",
        "started_at",
        "finished_at",
        "attempts",
    } <= _columns(db_path, "source_files")
    assert {
        "source_account_id",
        "dedup_key",
        "occurrence_index",
        "extraction_confidence",
        "raw_text",
    } <= _columns(db_path, "normalized_events")
    assert {"nombre", "descripcion", "hit_count", "last_hit_at"} <= _columns(
        db_path, "classification_rules"
    )
    assert {
        "lote_id", "tax", "fx_rate", "account_id", "source_file_id"
    } <= _columns(db_path, "asset_transactions")
    assert {
        "amount_eur", "fx_rate_to_eur", "fx_source", "fx_date"
    } <= _columns(db_path, "financial_movements")
    assert {"currency", "source_file_id"} <= _columns(
        db_path, "account_balance_snapshots"
    )
    assert (_column_length(db_path, "asset_transactions", "tipo") or 0) >= 16
    assert {"balance_inicial", "balance_inicial_fecha"} <= _columns(db_path, "accounts")
    assert "name" in _columns(db_path, "users")
    assert {
        "parent_id",
        "aplica_a",
        "tratamiento",
        "color",
        "excluir_kpis",
        "orden",
        "system_key",
        "es_default",
    } <= _columns(db_path, "categorias")
    assert {"group_id", "orden", "activa"} <= _columns(db_path, "etiquetas")
    assert {"tag_groups", "movement_tags", "classification_rule_tags"} <= tables
    with sqlite3.connect(db_path) as conn:
        ingresos = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Ingresos' AND parent_id IS NULL"
        ).fetchone()
        inversiones = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Inversiones' AND parent_id IS NULL"
        ).fetchone()
        assert ingresos is not None
        assert inversiones is not None

        for nombre in ("Cashback", "Intereses", "Dividendos", "Nómina"):
            child = conn.execute(
                "SELECT id FROM categorias WHERE nombre=? AND parent_id=?",
                (nombre, ingresos[0]),
            ).fetchone()
            assert child is not None

        benefit = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Beneficios' AND parent_id=?",
            (ingresos[0],),
        ).fetchone()
        assert benefit is None
        nomina = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Nómina' AND parent_id=?",
            (ingresos[0],),
        ).fetchone()
        assert nomina is not None
        nomina_children = conn.execute(
            "SELECT COUNT(*) FROM categorias WHERE parent_id=?", (nomina[0],)
        ).fetchone()[0]
        assert nomina_children == 0

        ventas = conn.execute(
            "SELECT id, tratamiento, excluir_kpis FROM categorias "
            "WHERE nombre='Ventas' AND parent_id=?",
            (inversiones[0],),
        ).fetchone()
        assert ventas is not None
        assert ventas[1] == "inversion"
        assert ventas[2] == 1
        for nombre in ("Compras", "Aportaciones", "Cashback", "Otros"):
            child = conn.execute(
                "SELECT id FROM categorias WHERE nombre=? AND parent_id=?",
                (nombre, inversiones[0]),
            ).fetchone()
            assert child is not None

        inv_cashback = conn.execute(
            "SELECT tratamiento, excluir_kpis FROM categorias "
            "WHERE nombre='Cashback' AND parent_id=?",
            (inversiones[0],),
        ).fetchone()
        assert inv_cashback is not None
        assert inv_cashback[0] == "inversion"
        assert inv_cashback[1] == 1

        nested = conn.execute(
            "SELECT child.id, child.nombre FROM categorias child "
            "JOIN categorias parent ON parent.id=child.parent_id "
            "WHERE parent.parent_id IS NOT NULL"
        ).fetchall()
        assert nested == []

        duplicate_other = conn.execute(
            "SELECT COUNT(*) FROM categorias WHERE nombre='Otros' AND es_default=1"
        ).fetchone()[0]
        assert duplicate_other >= 2

        transfer = conn.execute(
            "SELECT id FROM categorias WHERE nombre='Transferencias' AND parent_id IS NULL"
        ).fetchone()
        assert transfer is not None
        for nombre in ("Revolut", "Bizum"):
            row = conn.execute(
                "SELECT tratamiento, excluir_kpis, activa FROM categorias "
                "WHERE nombre=? AND parent_id=?",
                (nombre, transfer[0]),
            ).fetchone()
            assert row is not None
            assert row[0] == "transferencia"
            assert row[1] == 1
            assert row[2] == 1
        historical = conn.execute(
            "SELECT activa FROM categorias WHERE nombre='Revolut' AND parent_id IS NULL"
        ).fetchone()
        if historical is not None:
            assert historical[0] == 0


def test_upgrade_head_from_empty_database(tmp_path):
    db_path = tmp_path / "empty.db"
    result = _run_alembic(db_path)
    assert result.returncode == 0, result.stderr
    _assert_foundation_schema(db_path)

    # Idempotente: una segunda ejecución no debe fallar ni cambiar la revisión.
    again = _run_alembic(db_path)
    assert again.returncode == 0, again.stderr
    assert _revision(db_path) == HEAD


def test_upgrade_head_on_copy_of_local_database(tmp_path):
    source = ROOT / "financial.db"
    if not source.exists():
        pytest.skip("financial.db no existe en este checkout")
    db_path = tmp_path / "financial_copy.db"
    shutil.copy2(source, db_path)

    with sqlite3.connect(db_path) as conn:
        before = conn.execute("SELECT COUNT(*) FROM financial_movements").fetchone()[0]

    result = _run_alembic(db_path)
    assert result.returncode == 0, result.stderr
    _assert_foundation_schema(db_path)

    with sqlite3.connect(db_path) as conn:
        after = conn.execute("SELECT COUNT(*) FROM financial_movements").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert after == before
    assert users == 0


def test_downgrade_one_and_reupgrade(tmp_path):
    db_path = tmp_path / "downgrade.db"
    assert _run_alembic(db_path).returncode == 0
    down = _run_alembic(db_path, "downgrade", "v3_008_income_group")
    assert down.returncode == 0, down.stderr
    assert _revision(db_path) == "v3_008_income_group"
    up = _run_alembic(db_path)
    assert up.returncode == 0, up.stderr
    _assert_foundation_schema(db_path)


def test_upgrade_head_is_idempotent_on_already_migrated_copy(tmp_path):
    source = ROOT / "financial.db"
    if not source.exists():
        pytest.skip("financial.db no existe en este checkout")
    db_path = tmp_path / "financial_copy_twice.db"
    shutil.copy2(source, db_path)

    assert _run_alembic(db_path).returncode == 0
    assert _run_alembic(db_path).returncode == 0
    _assert_foundation_schema(db_path)


def test_revision_ids_fit_alembic_version_column():
    """``alembic_version.version_num`` es VARCHAR(32) en PostgreSQL."""
    import re
    from pathlib import Path

    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for path in versions.glob("*.py"):
        match = re.search(r'^revision: str = "([^"]+)"', path.read_text(), re.M)
        if match:
            assert len(match.group(1)) <= 32, (path.name, match.group(1))
