"""
Interfaz legacy de adaptadores de ingesta (solo fixture de tests).

El pipeline de producción ya no usa parsers por banco: ``process_import``
extrae con ``src/ingest/agentic.py``. Esta interfaz se conserva únicamente
para el parser TR de los tests.
"""

from abc import ABC, abstractmethod


class DetectResult:
    """Resultado de la detección de fuente."""

    def __init__(self, source: str, parser_version: str):
        self.source = source
        self.parser_version = parser_version


class BaseParser(ABC):
    """Adaptador de ingesta para una fuente concreta (TR CSV, BBVA CSV, …)."""

    @abstractmethod
    def detect(self, header_lines: list[str], filename: str) -> bool:
        """Determina si este adaptador puede procesar el fichero."""
        ...

    @abstractmethod
    def parse(self, filepath: str) -> list[dict]:
        """Parsea el fichero y devuelve lista de eventos normalizados.

        Cada evento es un dict con las claves de NormalizedEvent:
          source_txn_id, broker_type, kind, occurred_at, value_date,
          amount, currency, fee, tax, original_amount, original_currency,
          fx_rate, asset_symbol, asset_name, asset_class, shares, price,
          counterparty_name, counterparty_iban, mcc_code,
          description_raw, description_clean, fingerprint
        """
        ...
