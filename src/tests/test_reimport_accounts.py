"""Tests de atribución de cuenta, saldo inicial y enlaces internos."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.db.session import _session
from src.ingest.account_match import evaluate_account_match
from src.ingest.accounts import (
    REVOLUT_IBAN,
    load_account_index,
)
from src.ingest.agentic import ExtractedStatement
from src.ingest.internal_transfers import link_internal_transfers
from src.ingest_service import process_import
from src.models import (
    Account,
    Categoria,
    Classification,
    FinancialMovement,
    MovementLink,
    SourceFile,
)

from .helpers import make_movement, tr_row, write_tr_csv


def _account(name: str) -> Account:
    with _session() as s:
        return s.query(Account).filter_by(nombre=name).one()


def test_account_match_blocks_revolut_iban_in_trade_republic(db):
    tr = _account("Trade Republic Default")
    with _session() as s:
        index = load_account_index(s)
    match = evaluate_account_match(
        selected_account=tr,
        index=index,
        detected_bank="Revolut",
        detected_iban=REVOLUT_IBAN,
    )
    assert match.status == "mismatch"
    assert match.blocks_import


def test_account_match_accepts_selected_revolut(db):
    revolut = _account("Revolut")
    with _session() as s:
        index = load_account_index(s)
    match = evaluate_account_match(
        selected_account=revolut,
        index=index,
        detected_bank="Revolut",
        detected_iban=REVOLUT_IBAN,
    )
    assert match.status == "match"
    assert not match.blocks_import


def test_account_match_unknown_without_bank_or_iban(db):
    tr = _account("Trade Republic Default")
    with _session() as s:
        index = load_account_index(s)
    match = evaluate_account_match(
        selected_account=tr,
        index=index,
    )
    assert match.status == "unknown"
    assert not match.blocks_import


class _MismatchExtractor:
    source = "test"
    parser_version = "test-1"

    def extract(self, path):
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=[{"row_index": 0, "values": {}}],
            events=[{
                "source_txn_id": "mismatch-1",
                "broker_type": "CASH_CARD_TRANSACTION",
                "kind": "gasto",
                "value_date": date(2026, 1, 1),
                "amount": Decimal("-10.00"),
                "currency": "EUR",
                "description_raw": "COMPRA",
                "description_clean": "COMPRA",
                "fingerprint": "f" * 64,
            }],
            bank="Revolut",
            account_iban=REVOLUT_IBAN,
        )


def test_import_with_wrong_account_is_quarantined(db, tmp_path):
    tr = _account("Trade Republic Default")
    path = write_tr_csv(tmp_path / "wrong.csv", [tr_row()])
    result = process_import(
        str(path),
        account_id=tr.id,
        extractor=_MismatchExtractor(),
    )
    assert result.source_file_id is not None
    assert result.errors
    with _session() as s:
        assert s.query(FinancialMovement).count() == 0
        sf = s.query(SourceFile).filter_by(id=result.source_file_id).one()
        assert sf.status == "needs_review"
        assert sf.account_id == tr.id


def test_internal_transfer_matcher_links_both_legs_and_is_idempotent(db):
    tr = _account("Trade Republic Default")
    revolut = _account("Revolut")
    with _session() as s:
        root = s.query(Categoria).filter_by(nombre="Transferencias").first()
        if root is None:
            root = Categoria(
                nombre="Transferencias",
                aplica_a="ambos",
                tratamiento="transferencia",
                excluir_kpis=True,
            )
            s.add(root)
            s.flush()
        child = (
            s.query(Categoria)
            .filter_by(nombre="Revolut", parent_id=root.id)
            .first()
        )
        if child is None:
            child = Categoria(
                nombre="Revolut",
                parent_id=root.id,
                aplica_a="ambos",
                tratamiento="transferencia",
                excluir_kpis=True,
            )
            s.add(child)
            s.flush()

    out_id, _ = make_movement(
        account_id=tr.id,
        amount=Decimal("-100.00"),
        kind="gasto",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Outgoing transfer to Revolut (ES1815830001189076828491)",
        merchant="Revolut",
        source_txn_id="out-1",
    )
    in_id, _ = make_movement(
        account_id=revolut.id,
        amount=Decimal("100.00"),
        kind="ingreso",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Top-up from Trade Republic (ES6415860001480335421911)",
        merchant="Trade Republic",
        source_txn_id="in-1",
    )

    stats = link_internal_transfers()
    assert stats["linked"] == 1
    with _session() as s:
        assert s.query(MovementLink).count() == 1
        a = s.query(FinancialMovement).filter_by(id=out_id).one()
        b = s.query(FinancialMovement).filter_by(id=in_id).one()
        assert a.kind == b.kind == "transferencia_interna"
        assert a.account_destino_id == revolut.id
        assert b.account_destino_id == tr.id
        for movement in (a, b):
            cl = (
                s.query(Classification)
                .filter_by(movement_id=movement.id, vigente=True)
                .one()
            )
            assert cl.categoria_id == child.id

    again = link_internal_transfers()
    assert again["linked"] == 0
    assert again["already_linked"] == 1


def test_account_without_iban_accepts_matching_bank_and_completes_iban(db):
    with _session() as s:
        joint = Account(
            nombre="Revolut Cuenta Conjunta",
            iban=None,
            tipo="efectivo_externa",
            broker="revolut",
            es_propia=True,
            moneda="EUR",
        )
        s.add(joint)
        s.flush()
        joint_id = joint.id
        index = load_account_index(s)
    match = evaluate_account_match(
        selected_account=s.query(Account).filter_by(id=joint_id).one(),
        index=index,
        detected_bank="Revolut",
        detected_iban="ES9121000418450200051332",
    )
    assert match.status == "match_weak"
    assert not match.blocks_import


class _OpeningBalanceExtractor:
    source = "test"
    parser_version = "test-1"

    def extract(self, path):
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=[{"row_index": 0, "values": {}}],
            events=[{
                "source_txn_id": "opening-1",
                "broker_type": "CASH_CARD_TRANSACTION",
                "kind": "gasto",
                "value_date": date(2026, 1, 2),
                "amount": Decimal("-10.00"),
                "currency": "EUR",
                "description_raw": "COMPRA",
                "description_clean": "COMPRA",
                "fingerprint": "a" * 64,
            }],
            period_start=date(2026, 1, 1),
            opening_balance=Decimal("100.00"),
            opening_balance_date=date(2026, 1, 1),
            bank="Trade Republic",
            account_iban="ES6415860001480335421911",
        )


def test_opening_balance_is_applied_to_empty_account(db, tmp_path):
    tr = _account("Trade Republic Default")
    with _session() as s:
        row = s.query(Account).filter_by(id=tr.id).one()
        row.balance_inicial = None
        row.balance_inicial_fecha = None
    path = write_tr_csv(tmp_path / "opening.csv", [tr_row()])
    result = process_import(
        str(path),
        account_id=tr.id,
        extractor=_OpeningBalanceExtractor(),
    )
    assert result.account_match["status"] == "match"
    with _session() as s:
        row = s.query(Account).filter_by(id=tr.id).one()
        assert row.balance_inicial == Decimal("100.00")
        assert row.balance_inicial_fecha == date(2026, 1, 1)


class _JointExtractor:
    source = "test"
    parser_version = "test-1"

    def extract(self, path):
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=[{"row_index": 0, "values": {}}],
            events=[{
                "source_txn_id": "joint-1",
                "broker_type": "CASH_CARD_TRANSACTION",
                "kind": "gasto",
                "value_date": date(2026, 1, 2),
                "amount": Decimal("-10.00"),
                "currency": "EUR",
                "description_raw": "COMPRA",
                "description_clean": "COMPRA",
                "fingerprint": "b" * 64,
            }],
            bank="Revolut",
            account_iban="ES9121000418450200051332",
        )


def test_joint_import_completes_missing_iban(db, tmp_path):
    with _session() as s:
        joint = Account(
            nombre="Revolut Cuenta Conjunta",
            iban=None,
            tipo="efectivo_externa",
            broker="revolut",
            es_propia=True,
            moneda="EUR",
        )
        s.add(joint)
        s.flush()
        joint_id = joint.id
    path = write_tr_csv(tmp_path / "joint.csv", [tr_row()])
    result = process_import(
        str(path),
        account_id=joint_id,
        extractor=_JointExtractor(),
    )
    assert result.account_match["status"] == "match_weak"
    with _session() as s:
        assert s.query(Account).filter_by(id=joint_id).one().iban == "ES9121000418450200051332"


def test_account_match_blocks_bank_mismatch_without_iban(db):
    tr = _account("Trade Republic Default")
    with _session() as s:
        index = load_account_index(s)
    match = evaluate_account_match(
        selected_account=tr,
        index=index,
        detected_bank="Revolut",
    )
    assert match.status == "mismatch"
    assert match.blocks_import


class _StaticExtractor:
    source = "test"
    parser_version = "test-1"

    def __init__(self, *, txn, amount, description, bank, iban):
        self.txn = txn
        self.amount = Decimal(amount)
        self.description = description
        self.bank = bank
        self.iban = iban

    def extract(self, path):
        return ExtractedStatement(
            source=self.source,
            parser_version=self.parser_version,
            raw_rows=[{"row_index": 0, "values": {}}],
            events=[{
                "source_txn_id": self.txn,
                "broker_type": "CASH_TRANSFER_AGENTIC",
                "kind": "transferencia_interna",
                "value_date": date(2026, 1, 15),
                "amount": self.amount,
                "currency": "EUR",
                "description_raw": self.description,
                "description_clean": self.description,
                "counterparty_iban": "ES1815830001189076828491",
                "fingerprint": (self.txn * 64)[:64],
            }],
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            bank=self.bank,
            account_iban=self.iban,
        )


def test_cross_currency_transfer_links_with_original_amount(db):
    tr = _account("Trade Republic Default")
    revolut = _account("Revolut")
    out_id, _ = make_movement(
        account_id=tr.id,
        amount=Decimal("-101.43"),
        currency="EUR",
        original_amount=Decimal("177620"),
        original_currency="KRW",
        kind="transferencia_interna",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Transferencia a ANDREEA ALEXANDRA BIRCU MITRAN",
        source_txn_id="fx-out-1",
    )
    in_id, _ = make_movement(
        account_id=revolut.id,
        amount=Decimal("177620"),
        currency="KRW",
        kind="transferencia_interna",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Transferencia de MARCOS FLOREZ FERNANDEZ",
        source_txn_id="fx-in-1",
    )
    stats = link_internal_transfers()
    assert stats["linked"] == 1
    with _session() as s:
        link = s.query(MovementLink).one()
        assert link.link_type == "internal_transfer"
        assert link.movement_a == min(out_id, in_id)
        assert link.movement_b == max(out_id, in_id)


def test_same_account_currency_exchange_is_linked_and_excluded(db):
    revolut = _account("Revolut")
    eur_id, _ = make_movement(
        account_id=revolut.id,
        amount=Decimal("-16.81"),
        currency="EUR",
        original_amount=Decimal("20.00"),
        original_currency="USD",
        kind="cambio_divisa",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Conversión a USD",
        source_txn_id="conv-eur",
    )
    usd_id, _ = make_movement(
        account_id=revolut.id,
        amount=Decimal("20.00"),
        currency="USD",
        kind="cambio_divisa",
        broker_type="CASH_TRANSFER_AGENTIC",
        description="Conversión a EUR",
        source_txn_id="conv-usd",
    )
    stats = link_internal_transfers()
    assert stats["linked"] == 1
    with _session() as s:
        link = s.query(MovementLink).one()
        assert link.link_type == "currency_exchange"
        for movement_id in (eur_id, usd_id):
            movement = s.query(FinancialMovement).filter_by(id=movement_id).one()
            assert movement.kind == "cambio_divisa"
            assert movement.account_destino_id is None


def test_second_account_import_links_internal_transfer_automatically(db, tmp_path):
    tr = _account("Trade Republic Default")
    revolut = _account("Revolut")
    first = write_tr_csv(tmp_path / "tr.csv", [tr_row()])
    process_import(
        str(first),
        account_id=tr.id,
        extractor=_StaticExtractor(
            txn="tr-out-1",
            amount="-100.00",
            description="Outgoing transfer to Revolut (ES1815830001189076828491)",
            bank="Trade Republic",
            iban="ES6415860001480335421911",
        ),
    )
    second = write_tr_csv(tmp_path / "revolut.csv", [tr_row()], extra_newline=True)
    process_import(
        str(second),
        account_id=revolut.id,
        extractor=_StaticExtractor(
            txn="rev-in-1",
            amount="100.00",
            description="Top-up from Trade Republic (ES6415860001480335421911)",
            bank="Revolut",
            iban="ES1815830001189076828491",
        ),
    )
    with _session() as s:
        links = s.query(MovementLink).all()
        assert len(links) == 1
        movements = s.query(FinancialMovement).order_by(FinancialMovement.id).all()
        assert len(movements) == 2
        assert all(m.kind == "transferencia_interna" for m in movements)
        assert movements[0].account_destino_id == revolut.id
        assert movements[1].account_destino_id == tr.id


def test_exact_iban_assigns_automatically_without_account_id(db, tmp_path):
    revolut = _account("Revolut")
    path = write_tr_csv(tmp_path / "auto-revolut.csv", [tr_row()])
    result = process_import(
        str(path),
        extractor=_StaticExtractor(
            txn="auto-revolut-1",
            amount="25.00",
            description="Incoming transfer",
            bank="Revolut",
            iban=REVOLUT_IBAN,
        ),
    )
    assert result.account_id == revolut.id
    assert result.account_match["status"] == "match"
    assert result.account_match["resolution_source"] == "iban"


def test_unknown_identity_does_not_fall_back_to_first_account(db, tmp_path):
    path = write_tr_csv(tmp_path / "unknown-account.csv", [tr_row()])
    result = process_import(str(path), extractor=_JointExtractor())
    assert result.account_match["status"] == "new_account"
    assert result.account_id is None
    with _session() as s:
        assert s.query(FinancialMovement).count() == 0


def test_start_from_zero_proposes_account_and_imports_after_confirmation(db, tmp_path):
    with _session() as s:
        s.query(Account).delete()
    path = write_tr_csv(tmp_path / "from_zero.csv", [tr_row()])
    first = process_import(
        str(path),
        extractor=_MismatchExtractor(),
    )
    assert first.account_match["status"] == "new_account"
    assert first.account_id is None
    with _session() as s:
        assert s.query(Account).count() == 0
        sf = s.query(SourceFile).filter_by(id=first.source_file_id).one()
        assert sf.status == "needs_review"
        assert sf.account_id is None

    with _session() as s:
        account = Account(
            nombre="Revolut Cuenta Corriente",
            iban=REVOLUT_IBAN,
            tipo="efectivo_externa",
            broker="revolut",
            es_propia=True,
            moneda="EUR",
        )
        s.add(account)
        s.flush()
        account_id = account.id

    second = process_import(
        str(path),
        account_id=account_id,
        extractor=_MismatchExtractor(),
        source_file_id=first.source_file_id,
    )
    assert second.account_match["status"] == "match"
    with _session() as s:
        assert s.query(Account).count() == 1
        assert s.query(FinancialMovement).count() == 1
        sf = s.query(SourceFile).filter_by(id=first.source_file_id).one()
        assert sf.status == "parsed"
        assert sf.account_id == account_id


class _ExplodingExtractor:
    def extract(self, path):  # pragma: no cover - no debe llamarse
        raise AssertionError("la reanudación no debe volver a extraer")


def test_quarantined_extraction_is_reused_after_account_approval(db, tmp_path):
    from src import ingest_service

    tr = _account("Trade Republic Default")
    revolut = _account("Revolut")
    path = write_tr_csv(tmp_path / "wrong.csv", [tr_row()])
    first = process_import(
        str(path), account_id=tr.id, extractor=_MismatchExtractor()
    )
    with _session() as s:
        sf = s.query(SourceFile).filter_by(id=first.source_file_id).one()
        file_hash = sf.file_hash
        sf.account_id = revolut.id
        sf.status = "queued"
    cache = ingest_service._extraction_cache_path(file_hash)
    assert cache.exists()

    resumed = process_import(
        str(path),
        force=True,
        account_id=revolut.id,
        source_file_id=first.source_file_id,
        extractor=_ExplodingExtractor(),
        reuse_extraction=True,
    )
    assert resumed.new_count == 1
    assert not cache.exists()
    with _session() as s:
        movement = s.query(FinancialMovement).one()
        assert movement.account_id == revolut.id
