"""Reset de la base de datos v2 (PostgreSQL o SQLite de desarrollo).

Borra los datos de negocio e ingesta, conserva el catálogo
(categorías/etiquetas/subtipos/app_config) y vuelve a sembrar cuentas,
reglas MCC/merchant y configuración de auto-aprobación.

Uso:
    DATABASE_URL=postgresql+psycopg://... python -m scripts.reset_v2
    DATABASE_URL=sqlite:///./financial.db python -m scripts.reset_v2

No usa ``SET session_replication_role`` ni SQL específico de SQLite en
PostgreSQL. En PostgreSQL usa ``TRUNCATE ... CASCADE``; en SQLite borra por
dependencias.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime

from sqlalchemy import inspect, text

from src.config import get_settings
from src.db.session import get_engine, get_sessionmaker
from src.ingest.accounts import ensure_accounts
from src.models import Account, AppConfig

_CORE_TABLES = [
    "movement_sources", "movement_links", "dedup_candidates",
    "classifications", "classification_memory", "classification_rule_tags",
    "classification_rules", "movement_tags",
    "account_balance_snapshots",
    "portfolio_snapshot_positions", "portfolio_snapshots",
    "asset_opening_positions", "account_currency_balances",
    "asset_transactions", "position_snapshots", "assets",
    "financial_movements", "normalized_events", "raw_rows",
    "source_files", "accounts", "classification_jobs",
    "pocket_transacciones", "pockets",
    "movimiento_etiquetas", "movimientos", "documentos",
    "activo_etiquetas", "operaciones", "activos",
]


def reset(
    db_url: str | None = None,
    *,
    seed_rules_flag: bool = False,
    keep_accounts: bool = False,
    keep_account_balances: bool = False,
) -> None:
    engine = get_engine(db_url)
    session_factory = get_sessionmaker(db_url)
    tables = set(inspect(engine).get_table_names())
    core = list(_CORE_TABLES)
    if keep_accounts:
        core.remove("accounts")
        if keep_account_balances:
            # Las anclas por divisa son el saldo inicial de cada cuenta.
            core.remove("account_currency_balances")
    existing = [table for table in core if table in tables]

    session = session_factory()
    try:
        if engine.dialect.name == "postgresql":
            if existing:
                session.execute(text(
                    "TRUNCATE TABLE " + ", ".join(existing) + " RESTART IDENTITY CASCADE"
                ))
        else:
            # SQLite: borrado por dependencias; no hay TRUNCATE CASCADE.
            for table in existing:
                session.execute(text(f"DELETE FROM {table}"))
        print(f"Datos truncados ({engine.dialect.name}): {len(existing)} tablas")
        # El inspector de ``ensure_accounts`` abre otra conexión; hay que
        # liberar los AccessExclusiveLock del TRUNCATE antes de inspeccionar.
        session.commit()

        if keep_accounts:
            for account in session.query(Account).all():
                if not keep_account_balances:
                    account.balance_inicial = 0
                    account.balance_inicial_fecha = None
                account.activo = True
        else:
            # Re-seed idempotente: cuentas, categorías y reglas.
            ensure_accounts(session)
        session.flush()

        if not session.query(AppConfig).filter_by(key="auto_approve_kinds").first():
            session.add(AppConfig(
                key="auto_approve_kinds",
                value=(
                    '["inversion_compra","inversion_venta","dividendo",'
                    '"interes","cashback","aporte_activo","transferencia_interna"]'
                ),
            ))
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if seed_rules_flag:
        # El seed histórico (scripts/seed_rules.py) se retiró en la limpieza
        # 2026-11-04. Las reglas vigentes se siembran aparte y de forma
        # explícita con ``python -m scripts.seed_reimport_rules``.
        from scripts.seed_reimport_rules import main as seed_reimport_rules

        seed_reimport_rules([])
    else:
        print(
            "Reglas de clasificación eliminadas. Siembra las vigentes con "
            "`python -m scripts.seed_reimport_rules`."
        )

    data_dir = get_settings().data_dir
    if data_dir.exists():
        shutil.rmtree(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"{data_dir} limpio")

    print("\nReset complete. Ready for fresh import.")


def _confirm() -> None:
    print("Esto vaciará TODOS los datos financieros (movimientos, imports, activos,")
    print("clasificaciones y reglas). Se conservan usuarios, sesiones y catálogo.")
    answer = input("Escribe 'BORRAR' para continuar: ").strip()
    if answer != "BORRAR":
        print("Cancelado.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="No pedir confirmación")
    parser.add_argument(
        "--no-rules",
        action="store_true",
        help="Compatibilidad: ya es el comportamiento por defecto",
    )
    parser.add_argument(
        "--seed-rules",
        action="store_true",
        help="Sembrar después las reglas de scripts.seed_reimport_rules",
    )
    parser.add_argument(
        "--keep-accounts",
        action="store_true",
        help="Conservar las cuentas existentes y poner su saldo inicial a 0",
    )
    parser.add_argument(
        "--keep-account-balances",
        action="store_true",
        help=(
            "Con --keep-accounts, conservar también balance_inicial y su fecha. "
            "Útil al reimportar el mismo histórico."
        ),
    )
    args = parser.parse_args()
    if not args.yes:
        _confirm()
    started = datetime.utcnow()
    reset(
        seed_rules_flag=args.seed_rules and not args.no_rules,
        keep_accounts=args.keep_accounts,
        keep_account_balances=args.keep_account_balances,
    )
    print(f"Reset terminado en {datetime.utcnow() - started}")


def _seed_config(engine) -> None:
    """Compatibilidad con llamadas antiguas."""
    Session = get_sessionmaker(engine.url)
    session = Session()
    try:
        if not session.query(AppConfig).filter_by(key="auto_approve_kinds").first():
            session.add(AppConfig(
                key="auto_approve_kinds",
                value=(
                    '["inversion_compra","inversion_venta","dividendo",'
                    '"interes","cashback","aporte_activo","transferencia_interna"]'
                ),
            ))
            session.commit()
    finally:
        session.close()


def _seed_accounts(engine) -> None:
    """Compatibilidad: siembra cuentas usando el motor indicado."""
    session = get_sessionmaker(engine.url)()
    try:
        ensure_accounts(session)
        session.commit()
    finally:
        session.close()


if __name__ == "__main__":
    main()
