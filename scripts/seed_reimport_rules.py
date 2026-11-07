"""Reglas de clasificación para la reimportación limpia (2026-11).

Usa paths actuales y nunca crea categorías raíz antiguas. Es idempotente:
actualiza la regla existente si cambia la categoría/prioridad.

Uso:
    python -m scripts.seed_reimport_rules
    python -m scripts.seed_reimport_rules --revolut-joint-iban ES...
"""

from __future__ import annotations

import argparse

from src.db.session import _session
from src.ingest.accounts import REVOLUT_IBAN, normalize_iban
from src.models import ClassificationRule
from src.taxonomy import category_by_path, resolve_assignable_category

MCC_GROUPS: dict[str, tuple[str, ...]] = {
    "Compras › Alimentación": (
        "5411", "5422", "5441", "5451", "5462", "5499",
    ),
    "Ocio › Bares y Restaurantes": ("5812", "5813", "5814"),
    "Transporte › Gasolina": ("5541", "5542", "5983"),
    "Transporte › Otros": (
        "4111", "4112", "4121", "4131", "4784", "7512", "7523",
    ),
    "Vivienda › Facturas": ("4900",),
    "Vivienda › Otros": (
        "5211", "5231", "5251", "5712", "5713", "5714", "5718",
        "5719", "5722", "5732",
    ),
    "Servicios › Otros": (
        "4814", "4816", "4821", "4899", "5734", "5815", "5967",
        "7230", "7372", "9399",
    ),
    "Compras › Otros": (
        "5200", "5262", "5310", "5311", "5399", "5611", "5621",
        "5631", "5641", "5651", "5661", "5681", "5691", "5699",
        "5940", "5941", "5942", "5943", "5944", "5945", "5946",
        "5947", "5948", "5949", "5963", "5977", "5999",
    ),
    "Ocio › Otros": (
        "5816", "5818", "7832", "7841", "7911", "7922", "7932",
        "7933", "7941", "7991", "7992", "7993", "7994", "7995",
        "7996", "7997", "7998",
    ),
    "Salud › Otros": (
        "5912", "8011", "8021", "8031", "8041", "8042", "8043",
        "8049", "8050", "8062", "8071", "8099",
    ),
    "Inversiones › Otros": ("6211",),
}

# (campo, operador, valor, path, prioridad)
MERCHANT_RULES: tuple[tuple[str, str, str, str, int], ...] = (
    ("merchant", "contains", "BRISA", "Vivienda › Alquiler", 20),
    ("merchant", "contains", "SUNFLOWER", "Vivienda › Facturas", 21),
    ("merchant", "contains", "TOTALENERGIES", "Vivienda › Facturas", 22),
    ("merchant", "contains", "UTE AGUAS ALCALA", "Vivienda › Facturas", 23),
    ("merchant", "contains", "DIGI SPAIN", "Servicios › Otros", 24),
    ("merchant", "contains", "XTB", "Inversiones › Otros", 25),
    ("merchant", "contains", "AMAZON", "Compras › Otros", 30),
    ("merchant", "contains", "LIDL", "Compras › Alimentación", 31),
    ("merchant", "contains", "MERCADONA", "Compras › Alimentación", 32),
    ("merchant", "contains", "CARREFOUR", "Compras › Alimentación", 33),
    ("merchant", "contains", "ALCAMPO", "Compras › Alimentación", 34),
    ("merchant", "contains", "ALDI", "Compras › Alimentación", 35),
    ("merchant", "contains", "DIA ", "Compras › Alimentación", 36),
    ("merchant", "contains", "ENGLISH CONNECTION", "Servicios › Suscripciones", 37),
    ("merchant", "contains", "ADIDAS", "Compras › Otros", 38),
    ("merchant", "contains", "REVOLUT", "Transferencias › Revolut", 10),
    ("merchant", "contains", "BUNQ", "Transferencias › Otros", 60),
    ("merchant", "contains", "N26", "Transferencias › Otros", 61),
    ("description_clean", "contains", "BIZUM DEBIT TRANSFER TO AMAZON",
     "Compras › Otros", 40),
    ("description_clean", "contains", "BIZUM DEBIT TRANSFER TO LIDL",
     "Compras › Alimentación", 41),
    ("description_clean", "contains", "BIZUM", "Transferencias › Bizum", 50),
    ("description_clean", "contains", "BUNQ", "Transferencias › Otros", 62),
    ("description_clean", "contains", "N26", "Transferencias › Otros", 63),
)


def _category_id(session, path: str) -> int | None:
    category = category_by_path(session, path)
    if category is None:
        return None
    resolved = resolve_assignable_category(session, category)
    return resolved.id if resolved is not None else None


def _upsert_rule(
    session,
    *,
    campo: str,
    operador: str,
    valor: str,
    category_id: int,
    prioridad: int,
    auto_aprobar: bool,
    nombre: str,
) -> str:
    rule = (
        session.query(ClassificationRule)
        .filter(
            ClassificationRule.campo == campo,
            ClassificationRule.operador == operador,
            ClassificationRule.valor == valor,
        )
        .first()
    )
    if rule is None:
        rule = ClassificationRule(
            campo=campo,
            operador=operador,
            valor=valor,
        )
        session.add(rule)
        action = "created"
    else:
        action = "updated"
    rule.set_categoria_id = category_id
    rule.prioridad = prioridad
    rule.auto_aprobar = auto_aprobar
    rule.nombre = nombre
    rule.activa = True
    return action


def seed(*, revolut_joint_iban: str | None = None) -> dict:
    stats = {"created": 0, "updated": 0, "skipped": 0}
    with _session() as s:
        for path, mccs in MCC_GROUPS.items():
            category_id = _category_id(s, path)
            if category_id is None:
                stats["skipped"] += len(mccs)
                print(f"AVISO: no existe la categoría {path!r}; se omiten sus MCC")
                continue
            for mcc in mccs:
                action = _upsert_rule(
                    s,
                    campo="mcc_code",
                    operador="equals",
                    valor=mcc,
                    category_id=category_id,
                    prioridad=70,
                    auto_aprobar=False,
                    nombre=f"MCC {mcc} → {path}",
                )
                stats[action] += 1

        for campo, operador, valor, path, prioridad in MERCHANT_RULES:
            category_id = _category_id(s, path)
            if category_id is None:
                stats["skipped"] += 1
                print(f"AVISO: no existe la categoría {path!r}; se omite {valor!r}")
                continue
            action = _upsert_rule(
                s,
                campo=campo,
                operador=operador,
                valor=valor,
                category_id=category_id,
                prioridad=prioridad,
                auto_aprobar=prioridad < 35,
                nombre=f"{campo} {operador} {valor} → {path}",
            )
            stats[action] += 1

        revolut_ibans = [REVOLUT_IBAN]
        if revolut_joint_iban:
            revolut_ibans.append(normalize_iban(revolut_joint_iban))
        for iban in dict.fromkeys(filter(None, revolut_ibans)):
            category_id = _category_id(s, "Transferencias › Revolut")
            if category_id is None:
                stats["skipped"] += 1
                continue
            action = _upsert_rule(
                s,
                campo="counterparty_iban",
                operador="equals",
                valor=iban,
                category_id=category_id,
                prioridad=5,
                auto_aprobar=True,
                nombre=f"IBAN Revolut {iban} → Transferencias › Revolut",
            )
            stats[action] += 1

        s.flush()
        print(
            "Reglas: "
            f"{stats['created']} creadas, {stats['updated']} actualizadas, "
            f"{stats['skipped']} omitidas"
        )
    return stats


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--revolut-joint-iban",
        default=None,
        help="IBAN de la cuenta conjunta de Revolut para la regla de transferencia.",
    )
    args = parser.parse_args(argv)
    seed(revolut_joint_iban=args.revolut_joint_iban)


if __name__ == "__main__":
    main()
