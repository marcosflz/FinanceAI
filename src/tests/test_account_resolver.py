from types import SimpleNamespace

from src.ingest.account_resolver import resolve_account


def account(
    account_id: int,
    name: str,
    iban: str | None,
    *,
    broker: str = "revolut",
    active: bool = True,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=account_id,
        nombre=name,
        iban=iban,
        broker=broker,
        activo=active,
        es_propia=True,
    )


def test_exact_iban_assigns_without_selection():
    accounts = [
        account(1, "Trade Republic", "ES6415860001480335421911", broker="trade_republic"),
        account(2, "Revolut personal", "ES1815830001189076828491"),
    ]
    match = resolve_account(
        accounts=accounts,
        detected_bank="Revolut",
        detected_iban="ES18 1583 0001 1890 7682 8491",
    )
    assert match.status == "match"
    assert match.selected_account_id == 2
    assert match.resolution_source == "iban"
    assert not match.blocks_import
    assert not match.requires_confirmation


def test_new_iban_requires_confirmation_instead_of_using_first_account():
    match = resolve_account(
        accounts=[account(1, "Trade Republic", "ES6415860001480335421911", broker="trade_republic")],
        detected_bank="Revolut",
        detected_iban="ES0815830001139109642173",
        detected_product="Cuenta conjunta",
    )
    assert match.status == "new_account"
    assert match.selected_account_id is None
    assert match.blocks_import
    assert match.requires_confirmation


def test_masked_iban_requires_confirmation():
    match = resolve_account(
        accounts=[account(1, "Revolut personal", "ES1815830001189076828491")],
        detected_bank="Revolut",
        detected_iban="ES18************8491",
    )
    assert match.status == "match_weak"
    assert match.selected_account_id == 1
    assert match.blocks_import


def test_same_bank_different_products_can_match_strong_candidate():
    accounts = [
        account(1, "Revolut Cuenta Corriente", None),
        account(2, "Revolut Cuenta Conjunta", None),
    ]
    match = resolve_account(
        accounts=accounts,
        detected_bank="Revolut",
        detected_product="Cuenta Conjunta",
    )
    assert match.selected_account_id == 2
    assert match.resolution_source == "bank_product"
    assert not match.requires_confirmation


def test_same_bank_without_product_is_not_auto_assigned():
    accounts = [
        account(1, "Revolut personal", None),
        account(2, "Revolut conjunta", None),
    ]
    match = resolve_account(
        accounts=accounts,
        detected_bank="Revolut",
        detected_account_name="Revolut",
    )
    assert match.status == "warning"
    assert match.selected_account_id is None
    assert match.blocks_import
    assert match.candidates == [1, 2]


def test_approved_profile_assigns_repeated_document():
    accounts = [
        account(1, "Trade Republic", None, broker="trade_republic"),
        account(2, "Revolut personal", None),
    ]
    match = resolve_account(
        accounts=accounts,
        detected_bank="Trade Republic",
        detected_product="DEFAULT",
        approved_profiles=[{
            "account_id": 1,
            "bank": "Trade Republic",
            "product": "DEFAULT",
        }],
    )
    assert match.status == "match"
    assert match.selected_account_id == 1
    assert match.resolution_source == "approved_profile"
    assert not match.blocks_import


def test_no_accounts_proposes_new_account():
    match = resolve_account(
        accounts=[],
        detected_bank="Revolut",
        detected_product="Cuenta Corriente",
    )
    assert match.status == "new_account"
    assert match.resolution_source == "no_accounts"
    assert match.blocks_import


def test_inactive_and_external_accounts_are_ignored():
    active = account(2, "Revolut personal", "ES1815830001189076828491")
    inactive = account(1, "Revolut antigua", "ES1815830001189076828491", active=False)
    match = resolve_account(
        accounts=[inactive, active],
        detected_iban="ES1815830001189076828491",
    )
    assert match.selected_account_id == 2
