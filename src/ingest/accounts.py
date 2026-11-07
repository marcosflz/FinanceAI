"""Resolución de cuentas propias a partir de eventos normalizados.

Prioridad (documentada y testeada):
1. IBAN exacto de ``counterparty_iban``.
2. IBAN exacto extraído de ``description_raw`` (nunca del texto redactado).
3. Patrones de ``accounts.alias_patrones`` (glob por defecto, ``re:`` para regex)
   contra ``counterparty_name``, nombre/merchant y ``description_raw``.
4. Heurísticas de nombre propio conocidas (Marcos Florez / M. Florez / Revolut /
   Bunq / N26), solo como red de seguridad si el seed no está aplicado.

La cuenta origen es siempre la cuenta del fichero importado (Trade Republic,
``tipo='broker_central'``). El destino solo se devuelve para cuentas propias
distintas de la origen. Los cargos por domiciliación (``TRANSFER_DIRECT_DEBIT``)
nunca se consideran transferencias internas aunque el nombre de la contraparte
sea el titular: el ``counterparty_iban`` del CSV es el de la propia TR y el
comercio aparece en ``description``.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text

# IBANs reales observados en los extractos (2026-01..06).
TRADE_REPUBLIC_IBAN = "ES6415860001480335421911"
REVOLUT_IBAN = "ES1815830001189076828491"
BUNQ_IBAN = "ES2915761212121010713974"
OTHER_OWN_IBANS = (
    "ES4615761212101010714154",
    "ES8015632626393267482833",
)

# Alias por defecto. Los patrones son glob (case-insensitive) salvo prefijo ``re:``.
DEFAULT_ACCOUNTS: tuple[dict, ...] = (
    {
        "nombre": "Trade Republic Default",
        "iban": TRADE_REPUBLIC_IBAN,
        "tipo": "broker_central",
        "broker": "trade_republic",
        "es_propia": True,
        "moneda": "EUR",
        "color": "#6366f1",
        "alias": ["Trade Republic*"],
    },
    {
        "nombre": "Revolut",
        "iban": REVOLUT_IBAN,
        "tipo": "efectivo_externa",
        "broker": "revolut",
        "es_propia": True,
        "moneda": "EUR",
        "color": "#00B4D8",
        "alias": ["Revolut**5844*", "Revolut**", "Marcos - Revolut*"],
    },
    {
        "nombre": "Bunq (test)",
        "iban": BUNQ_IBAN,
        "tipo": "efectivo_externa",
        "broker": "bunq",
        "es_propia": True,
        "moneda": "EUR",
        "color": "#E76F51",
        "alias": ["Bunq test*", "Bunq*"],
    },
    {
        "nombre": "N26",
        "iban": None,
        "tipo": "efectivo_externa",
        "broker": "n26",
        "es_propia": True,
        "moneda": "EUR",
        "color": "#48CAE4",
        "alias": ["N26*", "N26 TOP-UP*"],
    },
    {
        "nombre": "Cuenta propia (otras)",
        "iban": OTHER_OWN_IBANS[0],
        "tipo": "efectivo_externa",
        "broker": None,
        "es_propia": True,
        "moneda": "EUR",
        "color": "#8D99AE",
        "alias": [
            "MARCOS FLOREZ*",
            "M. FLOREZ*",
            "MARCOS*FLOREZ*",
            "FLOREZ FERNANDEZ MARCOS*",
            "MARCOS F.F.*",
        ],
        "extra_ibans": list(OTHER_OWN_IBANS[1:]),
    },
)

_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?: ?\d{4}){3,7}(?: ?\d{1,4})?\b")

# Heurísticas de último recurso (si no hay seed o el alias se perdió).
_NAME_HEURISTICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Revolut", ("REVOLUT",)),
    ("Bunq (test)", ("BUNQ",)),
    ("N26", ("N26",)),
    ("Cuenta propia (otras)", ("MARCOS FLOREZ", "M. FLOREZ", "MARCOS F.F.")),
)


def normalize_iban(value: str | None) -> str:
    """Normaliza un IBAN: mayúsculas, sin espacios ni guiones."""
    if not value:
        return ""
    return re.sub(r"[\s-]+", "", value).upper()


def extract_ibans(text: str | None) -> list[str]:
    """Extrae IBANs normalizados de un texto, sin duplicados y en orden."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _IBAN_RE.finditer(text.upper()):
        iban = normalize_iban(match.group())
        if len(iban) < 15 or len(iban) > 34:
            continue
        if iban not in seen:
            seen.add(iban)
            result.append(iban)
    return result


_BROKER_TYPE_PREFIXES = ("CASH_", "TRADING_", "DELIVERY_")


def base_broker_type(broker_type: str | None) -> str:
    """Tipo sin prefijo de categoría: ``CASH_BUY``/``TRADING_BUY`` → ``BUY``."""
    bt = (broker_type or "").upper()
    for prefix in _BROKER_TYPE_PREFIXES:
        if bt.startswith(prefix):
            return bt[len(prefix):]
    return bt


def is_transfer_type(broker_type: str | None) -> bool:
    """True para transferencias SEPA/instantáneas; excluye domiciliaciones."""
    bt = (broker_type or "").upper()
    if not bt or "DIRECT_DEBIT" in bt:
        return False
    base = base_broker_type(bt)
    return base in {"TRANSFER", "TOPUP", "TOP_UP"} or base.startswith(
        ("TRANSFER_", "TOPUP_", "TOP_UP_")
    )


def is_card_transaction(broker_type: str | None) -> bool:
    """True para cargos de tarjeta (incluye recargas tipo Revolut/N26)."""
    return base_broker_type(broker_type).startswith(("CARD_TRANSACTION", "CARD_PAYMENT"))


@dataclass
class AccountRef:
    """Vista ligera de una cuenta, tolerante a esquemas antiguos.

    No es una entidad ORM: permite que seed/backfill e ingesta funcionen
    aunque la BD todavía no tenga columnas nuevas del modelo (drift Alembic).
    """

    id: int
    nombre: str
    iban: str | None = None
    alias_patrones: str | None = None
    tipo: str = "efectivo_externa"
    broker: str | None = None
    es_propia: bool = True
    moneda: str = "EUR"
    color: str = "#6366f1"
    activo: bool = True


@dataclass
class _CompiledAlias:
    account: AccountRef
    globs: list[str] = field(default_factory=list)
    regexes: list[re.Pattern] = field(default_factory=list)


class AccountIndex:
    """Índice en memoria de cuentas, IBANs y alias."""

    def __init__(self, accounts: Iterable[object], source: object | None = None):
        self.accounts: list[object] = list(accounts)
        self.by_iban: dict[str, object] = {}
        self.aliases: list[_CompiledAlias] = []
        self.source = source

        for account in self.accounts:
            if account.iban:
                self.by_iban[normalize_iban(account.iban)] = account

        for account in self.accounts:
            compiled = _CompiledAlias(account=account)
            for raw in _load_aliases(account.alias_patrones):
                if raw.lower().startswith("re:"):
                    try:
                        compiled.regexes.append(re.compile(raw[3:], re.IGNORECASE))
                    except re.error:
                        continue
                    continue
                # Un alias que es un IBAN completo sin comodines se registra
                # también como IBAN exacto de la cuenta.
                if "*" not in raw and "?" not in raw:
                    candidate = normalize_iban(raw)
                    if _IBAN_RE.fullmatch(candidate):
                        self.by_iban.setdefault(candidate, account)
                compiled.globs.append(raw.upper())
            if compiled.globs or compiled.regexes:
                self.aliases.append(compiled)

        if source is None:
            self.source = next(
                (a for a in self.accounts if (a.tipo or "") == "broker_central"),
                None,
            )

    def find_iban(self, iban: str | None) -> object | None:
        normalized = normalize_iban(iban)
        if not normalized:
            return None
        return self.by_iban.get(normalized)

    def match_alias(self, values: Iterable[str | None]) -> object | None:
        haystack = [v for v in values if v]
        if not haystack:
            return None
        for alias in self.aliases:
            for value in haystack:
                upper = value.upper()
                for pattern in alias.globs:
                    if fnmatch.fnmatchcase(upper, pattern):
                        return alias.account
                for regex in alias.regexes:
                    if regex.search(value):
                        return alias.account
        return None


def _load_aliases(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [str(item).strip() for item in data if str(item).strip()]


def _merge_aliases(existing: str | None, defaults: list[str]) -> str:
    merged: list[str] = []
    for item in _load_aliases(existing) + defaults:
        if item not in merged:
            merged.append(item)
    return json.dumps(merged, ensure_ascii=False)


def _table_columns(session, table: str) -> set[str]:
    try:
        inspector = sa_inspect(session.get_bind())
        if table not in inspector.get_table_names():
            return set()
        return {c["name"] for c in inspector.get_columns(table)}
    except Exception:
        return set()


def _row_to_account(row, columns: set[str]) -> AccountRef:
    data = dict(row)
    es_propia = data.get("es_propia")
    activo = data.get("activo")
    return AccountRef(
        id=data["id"],
        nombre=data.get("nombre") or "",
        iban=data.get("iban"),
        alias_patrones=data.get("alias_patrones"),
        tipo=data.get("tipo") or "efectivo_externa",
        broker=data.get("broker"),
        es_propia=True if es_propia is None else bool(es_propia),
        moneda=data.get("moneda") or "EUR",
        color=data.get("color") or "#6366f1",
        activo=True if activo is None else bool(activo),
    )


def _select_accounts_sql(columns: set[str], where: str = "", params: dict | None = None,
                         limit: int | None = None):
    selectable = [
        c for c in (
            "id", "nombre", "iban", "alias_patrones", "tipo", "broker",
            "es_propia", "moneda", "color", "activo",
        ) if c in columns
    ]
    sql = f"SELECT {', '.join(selectable)} FROM accounts"
    if where:
        sql += f" WHERE {where}"
    sql += " ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    return text(sql), (params or {})


def _find_account_sql(session, spec: dict, columns: set[str]) -> AccountRef | None:
    iban = normalize_iban(spec.get("iban"))
    # Orden deliberado: las cuentas externas se localizan por nombre antes que
    # por IBAN para no confundirlas con una TR antigua que aún tenga ese IBAN.
    searches: list[tuple[str, dict]] = []
    if spec.get("tipo") == "broker_central" and "tipo" in columns:
        searches.append(("tipo = :tipo", {"tipo": "broker_central"}))
    if "nombre" in columns:
        searches.append(("nombre = :nombre", {"nombre": spec["nombre"]}))
    if iban and "iban" in columns:
        searches.append(("iban = :iban", {"iban": iban}))

    for where, params in searches:
        sql, bound = _select_accounts_sql(columns, where, params, 1)
        row = session.execute(sql, bound).mappings().first()
        if row:
            return _row_to_account(row, columns)
    return None


def ensure_accounts(session) -> dict:
    """Seed idempotente de TR/Revolut/Bunq/N26/cuentas propias.

    Si las cuentas ya existen, actualiza IBAN, tipo y alias en vez de omitir.
    Usa SQL dinámico sobre las columnas realmente presentes: así funciona
    también con el esquema antiguo (sin ``balance_inicial`` ni otras columnas
    nuevas del modelo) y no requiere migración para el seed.
    Devuelve contadores ``created``/``updated``.
    """
    created = 0
    updated = 0
    columns = _table_columns(session, "accounts")
    if not columns:
        return {"created": 0, "updated": 0}

    for spec in DEFAULT_ACCOUNTS:
        account = _find_account_sql(session, spec, columns)
        extra_ibans = spec.get("extra_ibans") or []
        aliases = list(spec.get("alias") or [])
        if extra_ibans:
            # Se conservan como alias de IBAN exacto en alias_patrones para
            # que la resolución por patrón también los reconozca.
            aliases.extend(extra_ibans)

        if account is None:
            data: dict = {}
            if "nombre" in columns:
                data["nombre"] = spec["nombre"]
            if "iban" in columns:
                data["iban"] = spec.get("iban")
            if "alias_patrones" in columns:
                data["alias_patrones"] = _merge_aliases(None, aliases)
            if "tipo" in columns:
                data["tipo"] = spec["tipo"]
            if "broker" in columns:
                data["broker"] = spec.get("broker")
            if "es_propia" in columns:
                data["es_propia"] = spec.get("es_propia", True)
            if "moneda" in columns:
                data["moneda"] = spec.get("moneda", "EUR")
            if "color" in columns:
                data["color"] = spec.get("color", "#6366f1")
            if "activo" in columns:
                data["activo"] = True
            placeholders = ", ".join(f":{key}" for key in data)
            sql = f"INSERT INTO accounts ({', '.join(data)}) VALUES ({placeholders})"
            if session.get_bind().dialect.name != "sqlite":
                sql += " RETURNING id"
            result = session.execute(text(sql), data)
            if session.get_bind().dialect.name == "sqlite":
                new_id = result.lastrowid
            else:
                new_id = result.scalar_one()
            account = AccountRef(
                id=new_id, nombre=spec["nombre"], iban=spec.get("iban"),
                alias_patrones=data.get("alias_patrones"), tipo=spec["tipo"],
                broker=spec.get("broker"), es_propia=spec.get("es_propia", True),
                moneda=spec.get("moneda", "EUR"),
                color=spec.get("color", "#6366f1"), activo=True,
            )
            created += 1
            continue

        updates: dict = {}
        if spec.get("iban") and normalize_iban(account.iban) != normalize_iban(spec["iban"]):
            updates["iban"] = spec["iban"]
        if account.tipo != spec["tipo"]:
            updates["tipo"] = spec["tipo"]
        if spec.get("broker") and account.broker != spec["broker"]:
            updates["broker"] = spec["broker"]
        if account.es_propia is not True:
            updates["es_propia"] = True
        if "alias_patrones" in columns:
            merged = _merge_aliases(account.alias_patrones, aliases)
            if merged != (account.alias_patrones or "[]"):
                updates["alias_patrones"] = merged
        if updates:
            assignments = ", ".join(f"{key} = :{key}" for key in updates)
            session.execute(
                text(f"UPDATE accounts SET {assignments} WHERE id = :_id"),
                {**updates, "_id": account.id},
            )
            updated += 1

    return {"created": created, "updated": updated}


def load_account_index(session, source_account: object | None = None) -> AccountIndex:
    """Carga todas las cuentas activas y construye el índice de resolución."""
    columns = _table_columns(session, "accounts")
    if not columns:
        return AccountIndex([], source=source_account)
    where = "activo IS NULL OR activo = true" if "activo" in columns else ""
    sql, params = _select_accounts_sql(columns, where, {})
    rows = session.execute(sql, params).mappings().all()
    accounts = [_row_to_account(row, columns) for row in rows]
    if source_account is None:
        source_account = next(
            (a for a in accounts if (a.tipo or "") == "broker_central"),
            None,
        )
    return AccountIndex(accounts, source=source_account)


def resolve_accounts(
    event: dict,
    source_account: object | None = None,
    index: AccountIndex | None = None,
) -> tuple[object | None, object | None]:
    """Resuelve ``(cuenta_origen, cuenta_destino_propia)`` para un evento.

    ``event`` admite las claves del parser (``counterparty_iban``,
    ``counterparty_name``, ``description_raw``, ``asset_name``, ``name``).
    El destino nunca es la cuenta origen.
    """
    if index is None:
        if source_account is None:
            raise ValueError("resolve_accounts requiere index o source_account")
        index = AccountIndex([source_account], source=source_account)

    source = source_account or index.source
    source_id = source.id if source is not None else None

    # Solo las transferencias y las recargas de tarjeta a una cuenta propia
    # pueden tener cuenta de destino. Una domiciliación nunca se reinterpreta
    # como traspaso (su counterparty_iban del CSV es el de la propia TR).
    broker_type = event.get("broker_type")
    if broker_type and not is_transfer_type(broker_type) and not is_card_transaction(broker_type):
        return source, None

    # 1) IBAN exacto declarado por el broker.
    declared = index.find_iban(event.get("counterparty_iban"))
    if declared is not None and declared.id != source_id:
        return source, declared

    # 2) IBAN exacto extraído de la descripción original (nunca de la redactada).
    desc_raw = event.get("description_raw") or ""
    for iban in extract_ibans(desc_raw):
        account = index.find_iban(iban)
        if account is not None and account.id != source_id:
            return source, account

    # 3) Alias configurados sobre contraparte / merchant / descripción.
    values = [
        event.get("counterparty_name"),
        event.get("name"),
        event.get("asset_name"),
        desc_raw,
    ]
    aliased = index.match_alias(values)
    if aliased is not None and aliased.id != source_id:
        return source, aliased

    # 4) Heurísticas de nombre propio (red de seguridad).
    upper_values = [v.upper() for v in values if v]
    for account_name, needles in _NAME_HEURISTICS:
        if not any(any(needle in value for needle in needles) for value in upper_values):
            continue
        account = next(
            (a for a in index.accounts if a.nombre == account_name),
            None,
        )
        if account is not None and account.id != source_id:
            return source, account

    return source, None


def classify_transfer_kind(
    broker_type: str | None,
    amount,
    destination: object | None,
) -> str | None:
    """Devuelve el kind final de una transferencia, o None si no aplica.

    - Destino propio distinto de la origen → ``transferencia_interna``.
    - Resto de transferencias (no domiciliaciones) → ingreso/gasto por signo.
    """
    if not is_transfer_type(broker_type):
        return None
    if destination is not None:
        return "transferencia_interna"
    try:
        return "ingreso" if amount is not None and amount > 0 else "gasto"
    except TypeError:
        return "gasto"
