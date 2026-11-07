"""Validación determinista de la cuenta de un extracto.

El extractor devuelve banco, titular, IBAN y producto. Antes de crear
movimientos comprobamos que esa identidad coincide con la cuenta seleccionada.
Nunca se importa un extracto de otra cuenta conocida en la cuenta equivocada.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .accounts import AccountIndex, normalize_iban

_PRODUCTOS_NO_CONTROLADOS = ("pocket", "pockets", "deposito", "deposit", "savings", "ahorro")


@dataclass(frozen=True)
class AccountMatch:
    status: str
    selected_account_id: int | None
    detected_account_id: int | None
    reason: str
    detected: dict[str, Any]
    resolution_source: str | None = None
    requires_confirmation: bool = False
    candidates: list[int] = field(default_factory=list)

    @property
    def blocks_import(self) -> bool:
        return self.requires_confirmation or self.status in {
            "mismatch", "new_account", "unsupported_product"
        }

    @property
    def needs_review(self) -> bool:
        return self.status in {"warning", "new_account", "unsupported_product"}

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "selected_account_id": self.selected_account_id,
            "detected_account_id": self.detected_account_id,
            "reason": self.reason,
            "detected": self.detected,
            "resolution_source": self.resolution_source,
            "requires_confirmation": self.requires_confirmation,
            "candidates": list(self.candidates),
        }


def _text(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).strip()


def _bank_matches(bank: str | None, account: object) -> bool:
    if not bank:
        return True
    needle = _text(bank)
    broker = _text(getattr(account, "broker", None))
    name = _text(getattr(account, "nombre", None))
    if not needle:
        return True
    if broker and (_contains_words(broker, needle) or _contains_words(needle, broker)):
        return True
    return _contains_words(name, needle)


def _contains_words(haystack: str, needle: str) -> bool:
    """``needle`` aparece en ``haystack`` como palabras completas."""
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def _product_unsupported(product: str | None) -> bool:
    normalized = _text(product)
    return bool(normalized) and any(token in normalized for token in _PRODUCTOS_NO_CONTROLADOS)


def product_is_unsupported(product: str | None) -> bool:
    """True para productos que no se controlan como cuentas."""
    return _product_unsupported(product)


def _masked_matches(masked: str | None, account: object) -> bool:
    if not masked:
        return False
    raw = normalize_iban(masked)
    if len(raw) < 8:
        return False
    account_iban = normalize_iban(getattr(account, "iban", None))
    if not account_iban:
        return False
    return raw[:4] == account_iban[:4] and raw[-4:] == account_iban[-4:]


def evaluate_account_match(
    *,
    selected_account: object,
    index: AccountIndex,
    detected_bank: str | None = None,
    detected_account_name: str | None = None,
    detected_iban: str | None = None,
    detected_product: str | None = None,
) -> AccountMatch:
    """Compara la identidad detectada con la cuenta seleccionada.

    Estados:
    - ``match``: IBAN/banco coherentes.
    - ``match_weak``: IBAN enmascarado o cuenta sin IBAN pero nombre/producto
      coherente; se importa con aviso.
    - ``unknown``: el extracto no identifica cuenta; se confía en la selección.
    - ``warning``: banco/nombre no coincide; se importa a revisión.
    - ``mismatch``: el IBAN pertenece a otra cuenta conocida; se bloquea.
    - ``new_account``: el IBAN no existe; se ofrece crear la cuenta.
    - ``unsupported_product``: Pockets/Depósito; no se crea cuenta.
    """

    selected_id = getattr(selected_account, "id", None)
    detected = {
        "bank": detected_bank,
        "account_name": detected_account_name,
        "account_iban": detected_iban,
        "product": detected_product,
    }

    if _product_unsupported(detected_product):
        return AccountMatch(
            status="unsupported_product",
            selected_account_id=selected_id,
            detected_account_id=None,
            reason=(
                f"El extracto es del producto {detected_product!r}. "
                "Pockets/Depósito no se controlan como cuentas; importa solo "
                "Cuenta Corriente o Cuenta Conjunta."
            ),
            detected=detected,
        )

    raw_iban = normalize_iban(detected_iban)
    if len(raw_iban) >= 15:
        found = index.find_iban(raw_iban)
        if found is not None:
            if getattr(found, "id", None) == selected_id:
                return AccountMatch(
                    status="match",
                    selected_account_id=selected_id,
                    detected_account_id=getattr(found, "id", None),
                    reason="El IBAN detectado coincide con la cuenta seleccionada.",
                    detected=detected,
                )
            return AccountMatch(
                status="mismatch",
                selected_account_id=selected_id,
                detected_account_id=getattr(found, "id", None),
                reason=(
                    "El IBAN detectado pertenece a otra cuenta "
                    f"({getattr(found, 'nombre', 'cuenta desconocida')}). "
                    "Selecciona esa cuenta o cambia el extracto."
                ),
                detected=detected,
            )

        # IBAN completo desconocido. Si la cuenta seleccionada no tiene IBAN
        # todavía, el banco/nombre/producto puede confirmarla (p. ej. la
        # conjunta antes de completar su IBAN). El usuario ya la eligió de
        # forma explícita; no la cambiamos por otra cuenta.
        selected_iban = normalize_iban(getattr(selected_account, "iban", None))
        if not selected_iban and _bank_matches(detected_bank, selected_account):
            return AccountMatch(
                status="match_weak",
                selected_account_id=selected_id,
                detected_account_id=None,
                reason=(
                    "IBAN nuevo, pero el banco coincide con la cuenta "
                    "seleccionada. Se importará y se completará su IBAN."
                ),
                detected=detected,
            )
        if not selected_iban and _name_or_product_matches(
            selected_account, detected_account_name, detected_product
        ):
            return AccountMatch(
                status="match_weak",
                selected_account_id=selected_id,
                detected_account_id=None,
                reason=(
                    "IBAN nuevo, pero la cuenta seleccionada coincide por "
                    "nombre/producto. Se importará y quedará el IBAN detectado "
                    "para completar la cuenta."
                ),
                detected=detected,
            )
        return AccountMatch(
            status="new_account",
            selected_account_id=selected_id,
            detected_account_id=None,
            reason=(
                "El IBAN detectado no existe en Cuentas. Créalo antes de "
                "importar o selecciona la cuenta correcta."
            ),
            detected=detected,
        )

    if raw_iban and _masked_matches(raw_iban, selected_account):
        return AccountMatch(
            status="match_weak",
            selected_account_id=selected_id,
            detected_account_id=selected_id,
            reason="IBAN enmascarado compatible con la cuenta seleccionada.",
            detected=detected,
        )

    if detected_bank and not _bank_matches(detected_bank, selected_account):
        normalized_bank = _text(detected_bank)
        if normalized_bank not in {
            "desconocido", "unknown", "no detectado", "sin detectar", "n a",
        }:
            return AccountMatch(
                status="mismatch",
                selected_account_id=selected_id,
                detected_account_id=None,
                reason=(
                    f"El banco detectado ({detected_bank}) no coincide con la "
                    f"cuenta seleccionada ({getattr(selected_account, 'nombre', '')}). "
                    "Selecciona la cuenta correcta antes de importar."
                ),
                detected=detected,
            )

    if not detected_bank and not raw_iban:
        return AccountMatch(
            status="unknown",
            selected_account_id=selected_id,
            detected_account_id=None,
            reason=(
                "El extracto no identifica banco/IBAN. Se usará la cuenta "
                "seleccionada; revisa el detalle si hay dudas."
            ),
            detected=detected,
        )

    return AccountMatch(
        status="match_weak",
        selected_account_id=selected_id,
        detected_account_id=getattr(selected_account, "id", None),
        reason=(
            "El banco/IBAN detectado es compatible con la cuenta seleccionada, "
            "pero no hay un IBAN completo que lo confirme."
        ),
        detected=detected,
    )


def _name_or_product_matches(
    account: object, detected_name: str | None, detected_product: str | None
) -> bool:
    name = _text(getattr(account, "nombre", None))
    detected = _text(detected_name)
    product = _text(detected_product)
    if product and product in name:
        return True
    if not detected:
        return False
    # El titular no identifica una cuenta; solo aceptamos coincidencia de
    # producto/nombre de cuenta, no el nombre de la persona.
    return detected in name or name in detected
