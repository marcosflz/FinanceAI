"""Cuentas y etiquetas base para la reimportación.

- Trade Republic (se conserva si ya existe).
- Revolut Cuenta Corriente.
- Revolut Cuenta Conjunta (IBAN se completa al importar su extracto).
- Etiqueta Ahorro para traspasos a Pockets/Depósito.

Uso:
    python -m scripts.bootstrap_reimport_accounts
"""

from __future__ import annotations

import json

from src.db.session import _session
from src.ingest.accounts import REVOLUT_IBAN, TRADE_REPUBLIC_IBAN, normalize_iban
from src.models import Account, Etiqueta

ACCOUNTS = (
    {
        "nombre": "Trade Republic Default",
        "iban": TRADE_REPUBLIC_IBAN,
        "tipo": "broker_central",
        "broker": "trade_republic",
        "color": "#6366f1",
        "alias": ["Trade Republic*"],
    },
    {
        "nombre": "Revolut Cuenta Corriente",
        "iban": REVOLUT_IBAN,
        "tipo": "efectivo_externa",
        "broker": "revolut",
        "color": "#00B4D8",
        "alias": ["Revolut**5844*", "Revolut**", "Marcos - Revolut*"],
    },
    {
        "nombre": "Revolut Cuenta Conjunta",
        "iban": None,
        "tipo": "efectivo_externa",
        "broker": "revolut",
        "color": "#48CAE4",
        "alias": ["Revolut*Conjunta*", "Cuenta Conjunta*"],
    },
)


def _find_existing(session, spec: dict) -> Account | None:
    account = session.query(Account).filter_by(nombre=spec["nombre"]).first()
    if account is not None:
        return account
    iban = normalize_iban(spec.get("iban"))
    if iban:
        return session.query(Account).filter(Account.iban == iban).first()
    return None


def bootstrap() -> dict:
    stats = {"created": 0, "updated": 0}
    with _session() as session:
        for spec in ACCOUNTS:
            account = _find_existing(session, spec)
            if account is None:
                account = Account(
                    nombre=spec["nombre"],
                    iban=normalize_iban(spec.get("iban")) or None,
                    alias_patrones=json.dumps(spec["alias"], ensure_ascii=False),
                    tipo=spec["tipo"],
                    broker=spec["broker"],
                    es_propia=True,
                    moneda="EUR",
                    color=spec["color"],
                    activo=True,
                )
                session.add(account)
                stats["created"] += 1
                continue
            account.nombre = spec["nombre"]
            account.tipo = spec["tipo"]
            account.broker = spec["broker"]
            account.es_propia = True
            account.moneda = "EUR"
            account.color = spec["color"]
            if spec.get("iban"):
                account.iban = normalize_iban(spec["iban"])
            aliases = []
            try:
                aliases = json.loads(account.alias_patrones or "[]")
            except (TypeError, ValueError):
                aliases = []
            for alias in spec["alias"]:
                if alias not in aliases:
                    aliases.append(alias)
            account.alias_patrones = json.dumps(aliases, ensure_ascii=False)
            stats["updated"] += 1

        tag = session.query(Etiqueta).filter(Etiqueta.nombre == "Ahorro").first()
        if tag is None:
            session.add(Etiqueta(
                nombre="Ahorro",
                color="#10B981",
                descripcion="Traspasos a Pockets/Depósito o cuentas de ahorro.",
            ))
            stats["tag_created"] = 1
        else:
            stats["tag_created"] = 0
        session.flush()
    return stats


def main() -> None:
    print(bootstrap())


if __name__ == "__main__":
    main()
