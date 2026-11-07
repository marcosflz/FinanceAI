"""Resolución automática de la cuenta propietaria de un extracto.

A diferencia de ``evaluate_account_match``, aquí no hay una cuenta elegida por
el usuario. Solo se asigna automáticamente una cuenta cuando la evidencia es
única y ya es conocida; cualquier novedad o ambigüedad queda en revisión.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from .account_match import AccountMatch, _bank_matches, _name_or_product_matches
from .accounts import normalize_iban


def _text(value: object) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _detected(
    bank: str | None,
    account_name: str | None,
    iban: str | None,
    product: str | None,
) -> dict:
    return {
        "bank": bank,
        "account_name": account_name,
        "account_iban": iban,
        "product": product,
    }


def _masked_candidates(accounts: list[object], masked: str) -> list[object]:
    raw = normalize_iban(masked)
    if len(raw) < 8:
        return []
    return [
        account
        for account in accounts
        if normalize_iban(getattr(account, "iban", None))
        and raw[:4] == normalize_iban(getattr(account, "iban", None))[:4]
        and raw[-4:] == normalize_iban(getattr(account, "iban", None))[-4:]
    ]


def _profile_candidates(
    accounts: list[object],
    profiles: Iterable[Mapping],
    *,
    bank: str | None,
    product: str | None,
    iban: str | None,
) -> list[object]:
    by_id = {getattr(account, "id", None): account for account in accounts}
    normalized_iban = normalize_iban(iban)
    result: list[object] = []
    seen: set[int] = set()
    for profile in profiles:
        account_id = profile.get("account_id")
        account = by_id.get(account_id)
        if account is None or account_id in seen:
            continue
        profile_iban = normalize_iban(profile.get("account_iban"))
        if normalized_iban and profile_iban and normalized_iban != profile_iban:
            continue
        if _text(profile.get("bank")) != _text(bank):
            continue
        if _text(profile.get("product")) != _text(product):
            continue
        result.append(account)
        seen.add(account_id)
    return result


def resolve_account(
    *,
    accounts: Iterable[object],
    detected_bank: str | None = None,
    detected_account_name: str | None = None,
    detected_iban: str | None = None,
    detected_product: str | None = None,
    approved_profiles: Iterable[Mapping] = (),
) -> AccountMatch:
    """Resuelve una cuenta sin selección previa.

    ``approved_profiles`` contiene diccionarios con ``account_id``, ``bank``,
    ``product`` y opcionalmente ``account_iban`` de imports ya confirmados.
    """
    candidates = [
        account
        for account in accounts
        if getattr(account, "activo", True) and getattr(account, "es_propia", True)
    ]
    detected = _detected(
        detected_bank, detected_account_name, detected_iban, detected_product
    )
    raw_iban = normalize_iban(detected_iban)

    def result(
        status: str,
        *,
        account: object | None = None,
        source: str,
        reason: str,
        confirm: bool,
        options: Iterable[object] = (),
    ) -> AccountMatch:
        account_id = getattr(account, "id", None)
        option_ids = [getattr(item, "id") for item in options if getattr(item, "id", None) is not None]
        return AccountMatch(
            status=status,
            selected_account_id=account_id,
            detected_account_id=account_id if status in {"match", "match_weak"} else None,
            reason=reason,
            detected=detected,
            resolution_source=source,
            requires_confirmation=confirm,
            candidates=option_ids,
        )

    if len(raw_iban) >= 15 and raw_iban.isalnum():
        exact = [
            account
            for account in candidates
            if normalize_iban(getattr(account, "iban", None)) == raw_iban
        ]
        if len(exact) == 1:
            account = exact[0]
            return result(
                "match",
                account=account,
                source="iban",
                reason="El IBAN detectado coincide con una cuenta existente.",
                confirm=False,
                options=exact,
            )
        return result(
            "new_account",
            source="iban_new",
            reason="El IBAN detectado no pertenece a ninguna cuenta registrada. Confirma su alta o asigna otra cuenta.",
            confirm=True,
        )

    if raw_iban:
        masked = _masked_candidates(candidates, raw_iban)
        if len(masked) == 1:
            return result(
                "match_weak",
                account=masked[0],
                source="iban_masked",
                reason="El IBAN enmascarado es compatible con una cuenta. Confirma la asignación antes de importar.",
                confirm=True,
                options=masked,
            )
        if len(masked) > 1:
            return result(
                "warning",
                source="ambiguous_iban",
                reason="El IBAN enmascarado es compatible con varias cuentas. Selecciona la correcta.",
                confirm=True,
                options=masked,
            )

    profiled = _profile_candidates(
        candidates,
        approved_profiles,
        bank=detected_bank,
        product=detected_product,
        iban=raw_iban or None,
    )
    if len(profiled) == 1:
        return result(
            "match",
            account=profiled[0],
            source="approved_profile",
            reason="El documento coincide con un perfil de importación ya confirmado.",
            confirm=False,
            options=profiled,
        )

    strong = [
        account
        for account in candidates
        if detected_bank
        and _bank_matches(detected_bank, account)
        and (
            _name_or_product_matches(
                account, detected_account_name, detected_product
            )
            or (not detected_account_name and not detected_product)
        )
    ]
    if len(strong) == 1:
        return result(
            "match",
            account=strong[0],
            source="bank_product",
            reason=(
                "Banco y producto identifican una única cuenta compatible."
            ),
            confirm=False,
            options=strong,
        )
    if len(strong) > 1:
        return result(
            "warning",
            source="ambiguous_bank_product",
            reason="Hay varias cuentas compatibles con el banco y producto detectados.",
            confirm=True,
            options=strong,
        )

    if not candidates:
        return result(
            "new_account",
            source="no_accounts",
            reason="No hay cuentas activas. Confirma la cuenta detectada para importar el extracto.",
            confirm=True,
        )

    if detected_bank or detected_product or detected_account_name:
        return result(
            "new_account",
            source="unmatched_identity",
            reason="No hay una cuenta existente que coincida con la identidad detectada. Confirma el alta o asigna una cuenta.",
            confirm=True,
        )

    return result(
        "warning",
        source="unknown_identity",
        reason="El extracto no aporta suficiente identidad para asignarlo automáticamente.",
        confirm=True,
        options=candidates,
    )
