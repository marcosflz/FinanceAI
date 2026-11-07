"""Tests unitarios de parser TR, cuentas, seed y dedup de ingesta."""

from __future__ import annotations

import time
from decimal import Decimal

from src.db.session import _session
from src.ingest.accounts import (
    classify_transfer_kind,
    ensure_accounts,
    load_account_index,
    resolve_accounts,
)
from src.ingest.trade_republic import TradeRepublicCsvParser
from src.ingest_service import enqueue_import
from src.ingest_service import process_import as _process_import
from src.models import (
    Account,
    Categoria,
    Classification,
    DedupCandidate,
    FinancialMovement,
    NormalizedEvent,
    SourceFile,
)

from .helpers import TrParserExtractor, tr_row, write_tr_csv


def run_import(path, **kwargs):
    return _process_import(path, extractor=TrParserExtractor(), **kwargs)


class TestParserIban:
    def test_extracts_iban_from_description_before_redacting(self):
        description = (
            "Outgoing transfer for Marcos Florez Fernandez "
            "(ES18 1583 0001 1890 7682 8491)"
        )
        event = TradeRepublicCsvParser()._row_to_event(tr_row(
            category="CASH",
            type="TRANSFER_INSTANT_OUTBOUND",
            amount="-100.00",
            description=description,
            transaction_id="txn-iban",
        ))
        assert event["counterparty_iban"] == "ES1815830001189076828491"
        assert event["description_raw"] == description
        assert "[IBAN]" in event["description_clean"]
        assert "7682" not in event["description_clean"]

    def test_normalizes_declared_counterparty_iban(self):
        event = TradeRepublicCsvParser()._row_to_event(tr_row(
            type="TRANSFER_INSTANT_OUTBOUND",
            amount="-10.00",
            counterparty_iban="es29 1576 1212 1210 1071 3974",
            transaction_id="txn-normalize",
        ))
        assert event["counterparty_iban"] == "ES2915761212121010713974"

    def test_direct_debit_keeps_own_declared_iban(self):
        event = TradeRepublicCsvParser()._row_to_event(tr_row(
            type="TRANSFER_DIRECT_DEBIT_INBOUND",
            amount="-33.97",
            description="Sepa Direct Debit transfer to Sunflower (ES0801287681980100009632)",
            counterparty_iban="ES6415860001480335421911",
            transaction_id="txn-dd",
        ))
        # No debe sustituirse por el IBAN del comercio que aparece en description.
        assert event["counterparty_iban"] == "ES6415860001480335421911"

    def test_transfer_without_iban(self):
        event = TradeRepublicCsvParser()._row_to_event(tr_row(
            type="TRANSFER_INSTANT_INBOUND",
            amount="10.00",
            description="Incoming transfer from alguien",
            transaction_id="txn-no-iban",
        ))
        assert event["counterparty_iban"] is None


class TestAccountsSeed:
    def test_ensure_accounts_is_idempotent(self, db):
        with _session() as s:
            s.query(Account).delete()
        with _session() as s:
            first = ensure_accounts(s)
        with _session() as s:
            second = ensure_accounts(s)
            accounts = s.query(Account).all()

        assert first["created"] == 5
        assert second["created"] == 0
        assert second["updated"] == 0
        assert len([a for a in accounts if a.nombre == "Trade Republic Default"]) == 1
        tr = next(a for a in accounts if a.tipo == "broker_central")
        revolut = next(a for a in accounts if a.nombre == "Revolut")
        assert tr.iban == "ES6415860001480335421911"
        assert revolut.iban == "ES1815830001189076828491"
        assert "Revolut**5844*" in revolut.alias_patrones
        assert any("Bunq test*" in (a.alias_patrones or "") for a in accounts)
        assert any("N26*" in (a.alias_patrones or "") for a in accounts)
        assert any("MARCOS FLOREZ*" in (a.alias_patrones or "") for a in accounts)

    def test_seed_fixes_legacy_trade_republic_iban(self, db):
        with _session() as s:
            revolut = s.query(Account).filter_by(nombre="Revolut").first()
            revolut.iban = None
        with _session() as s:
            tr = s.query(Account).filter_by(tipo="broker_central").first()
            tr.iban = "ES1815830001189076828491"  # IBAN erróneo antiguo
        with _session() as s:
            ensure_accounts(s)
        with _session() as s:
            tr = s.query(Account).filter_by(tipo="broker_central").first()
            revolut = s.query(Account).filter_by(nombre="Revolut").first()
            assert tr.iban == "ES6415860001480335421911"
            assert revolut.iban == "ES1815830001189076828491"


class TestAccountResolution:
    def _index(self):
        with _session() as s:
            return load_account_index(s)

    def test_priority_iban_from_description(self, db):
        index = self._index()
        source, dest = resolve_accounts({
            "counterparty_iban": None,
            "counterparty_name": "Alguien",
            "description_raw": "Outgoing transfer for Marcos (ES1815830001189076828491)",
        }, index=index)
        assert source.nombre == "Trade Republic Default"
        assert dest.nombre == "Revolut"

    def test_bunq_by_iban_and_pattern(self, db):
        index = self._index()
        _, dest = resolve_accounts({
            "counterparty_iban": None,
            "counterparty_name": "Bunq test",
            "description_raw": "Outgoing transfer for Bunq test (ES2915761212121010713974)",
        }, index=index)
        assert dest.nombre == "Bunq (test)"

    def test_known_own_name_without_known_iban(self, db):
        index = self._index()
        _, dest = resolve_accounts({
            "counterparty_iban": None,
            "counterparty_name": "M. Florez Fernandez",
            "description_raw": "Outgoing transfer for M. Florez Fernandez",
        }, index=index)
        assert dest.nombre == "Cuenta propia (otras)"

    def test_external_family_member_is_not_own(self, db):
        index = self._index()
        _, dest = resolve_accounts({
            "counterparty_iban": "ES4530590077843294331412",
            "counterparty_name": "INDALECIO JAVIER FLOREZ OZORES",
            "description_raw": "Incoming transfer from INDALECIO JAVIER FLOREZ OZORES "
                               "(ES4530590077843294331412)",
        }, index=index)
        assert dest is None

    def test_own_source_iban_is_not_destination(self, db):
        index = self._index()
        _, dest = resolve_accounts({
            "broker_type": "CASH_TRANSFER_DIRECT_DEBIT_INBOUND",
            "counterparty_iban": "ES6415860001480335421911",
            "counterparty_name": "MARCOS FLOREZ FERNANDEZ",
            "description_raw": "Sepa Direct Debit transfer to DIGI "
                               "(ES9521008674140200010616)",
        }, index=index)
        assert dest is None

    def test_direct_debit_kind_is_not_internal(self):
        assert classify_transfer_kind(
            "CASH_TRANSFER_DIRECT_DEBIT_INBOUND", Decimal("-10"), object()
        ) is None
        assert classify_transfer_kind(
            "CASH_TRANSFER_INSTANT_OUTBOUND", Decimal("-10"), object()
        ) == "transferencia_interna"


class TestImportPipeline:
    def _rows(self):
        return [
            tr_row(
                type="CARD_TRANSACTION", amount="-10.00", mcc_code="5411",
                description="SUPERMERCADO", transaction_id="txn-card",
            ),
            tr_row(
                type="TRANSFER_INSTANT_OUTBOUND", amount="-100.00",
                description="Outgoing transfer for Marcos Florez Fernandez "
                            "(ES1815830001189076828491)",
                transaction_id="txn-revolut",
            ),
            tr_row(
                type="TRANSFER_INSTANT_INBOUND", amount="50.00",
                description="Incoming transfer from INDALECIO JAVIER FLOREZ OZORES "
                            "(ES4530590077843294331412)",
                transaction_id="txn-external",
            ),
            tr_row(
                type="TRANSFER_INSTANT_OUTBOUND", amount="-2.00",
                description="Outgoing transfer for Bunq test "
                            "(ES2915761212121010713974)",
                counterparty_name="Bunq test",
                counterparty_iban="ES2915761212121010713974",
                transaction_id="txn-bunq",
            ),
        ]

    def test_enqueue_then_process_reuses_source_file(self, db, tmp_path):
        csv_path = write_tr_csv(tmp_path / "queue.csv", [self._rows()[0]])
        source_id = enqueue_import(str(csv_path), original_filename="queue.csv")
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=source_id).first()
            assert sf is not None
            assert sf.status == "queued"
            assert sf.attempts == 0

        result = _process_import(
            str(csv_path),
            extractor=TrParserExtractor(),
            source_file_id=source_id,
        )
        assert result.source_file_id == source_id
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=source_id).first()
            assert sf.status == "parsed"
            assert sf.finished_at is not None
            assert sf.row_count == 1

    def test_same_file_same_day_same_amount_is_not_duplicate_candidate(
        self, db, tmp_path
    ):
        path = write_tr_csv(tmp_path / "legit.csv", [
            tr_row(type="CARD_TRANSACTION", amount="-2.00",
                   description="CAFE A", transaction_id="legit-a"),
            tr_row(type="CARD_TRANSACTION", amount="-2.00",
                   description="CAFE B", transaction_id="legit-b"),
        ])
        result = run_import(str(path))
        assert result.new_count == 2
        assert result.dup_candidates == 0
        with _session() as s:
            assert s.query(DedupCandidate).count() == 0

    def test_same_day_same_amount_across_files_is_duplicate_candidate(
        self, db, tmp_path
    ):
        first = write_tr_csv(tmp_path / "enero.csv", [
            tr_row(type="CARD_TRANSACTION", amount="-20.00",
                   description="CAFE A", transaction_id="cross-a"),
        ])
        second = write_tr_csv(tmp_path / "junio.csv", [
            tr_row(type="CARD_TRANSACTION", amount="-20.00",
                   description="CAFE B", transaction_id="cross-b"),
        ])
        first_result = run_import(str(first))
        second_result = run_import(str(second))
        assert first_result.dup_candidates == 0
        assert second_result.dup_candidates == 1
        with _session() as s:
            assert s.query(DedupCandidate).count() == 1

    def test_import_assigns_accounts_and_detects_internal(self, db, tmp_path):
        csv_path = write_tr_csv(tmp_path / "ene.csv", self._rows())
        started = time.perf_counter()
        result = run_import(str(csv_path))
        elapsed = time.perf_counter() - started

        assert result.new_count == 4
        assert result.accounts_assigned == 4
        assert result.internal_transfers == 2
        assert elapsed < 5

        with _session() as s:
            movements = s.query(FinancialMovement).order_by(FinancialMovement.id).all()
            events = {e.id: e for e in s.query(NormalizedEvent).all()}
            transfer_cat = s.query(Categoria).filter_by(nombre="Transferencias").first()

            assert len(movements) == 4
            assert all(m.account_id is not None for m in movements)

            internal = [m for m in movements if m.kind == "transferencia_interna"]
            assert len(internal) == 2
            assert all(m.account_destino_id is not None for m in internal)
            # Las transferencias nunca se autoaprueban (revisión manual).
            assert all(m.estado == "pendiente" for m in internal)

            external = next(m for m in movements if m.kind == "ingreso")
            assert external.account_destino_id is None
            assert external.estado == "pendiente"
            ext_events = [events[m.event_id] for m in movements]
            assert any(e.counterparty_iban == "ES4530590077843294331412" for e in ext_events)

            # Los traspasos propios llevan Transferencias propuesta; las
            # transferencias a terceros quedan sin categoría para revisarlas.
            for movement in movements:
                cl = (
                    s.query(Classification)
                    .filter_by(movement_id=movement.id, vigente=True)
                    .first()
                )
                if movement.kind == "transferencia_interna":
                    assert cl is not None
                    assert cl.categoria_id == transfer_cat.id
                    assert cl.origen == "broker"
                else:
                    assert cl is None

    def test_reimport_links_seen_and_creates_only_new(self, db, tmp_path):
        rows = self._rows()
        run_import(str(write_tr_csv(tmp_path / "ene.csv", rows)))
        rows2 = rows + [tr_row(
            type="CARD_TRANSACTION", amount="-5.00", mcc_code="5411",
            description="OTRA COMPRA", transaction_id="txn-card-2",
        )]
        result = run_import(str(write_tr_csv(tmp_path / "ene2.csv", rows2)))
        assert result.new_count == 1
        assert result.seen_count == 4
        with _session() as s:
            assert s.query(FinancialMovement).count() == 5

    def test_intra_file_same_transaction_id_is_deduplicated(self, db, tmp_path):
        rows = [
            tr_row(amount="-2.00", description="compra", transaction_id="dup-1"),
            tr_row(amount="-2.00", description="compra", transaction_id="dup-1"),
        ]
        result = run_import(str(write_tr_csv(tmp_path / "dup.csv", rows)))
        assert result.new_count == 1
        assert result.seen_count == 1
        assert result.intra_file_duplicates == 1
        with _session() as s:
            assert s.query(FinancialMovement).count() == 1

    def test_legit_repeats_without_id_survive_and_reimport_links_both(self, db, tmp_path):
        rows = [
            tr_row(amount="-2.00", description="Bunq test -2", transaction_id=""),
            tr_row(amount="-2.00", description="Bunq test -2", transaction_id=""),
        ]
        first = run_import(str(write_tr_csv(tmp_path / "repeats.csv", rows)))
        assert first.new_count == 2
        with _session() as s:
            assert s.query(FinancialMovement).count() == 2

        # Fichero distinto (hash distinto) con las mismas dos filas.
        second = run_import(str(write_tr_csv(
            tmp_path / "repeats2.csv", rows, extra_newline=True,
        )))
        assert second.new_count == 0
        assert second.seen_count == 2
        with _session() as s:
            assert s.query(FinancialMovement).count() == 2

    def test_card_topup_to_revolut_is_internal(self, db, tmp_path):
        result = run_import(str(write_tr_csv(tmp_path / "topup.csv", [
            tr_row(
                type="CARD_TRANSACTION", amount="-20.00", mcc_code="6012",
                name="Revolut**5844*", description="Revolut**5844*",
                transaction_id="txn-topup",
            ),
        ])))
        assert result.new_count == 1
        assert result.internal_transfers == 1
        with _session() as s:
            movement = s.query(FinancialMovement).first()
            assert movement.kind == "transferencia_interna"
            assert movement.estado == "pendiente"
            assert movement.account_destino_id is not None
            dest = s.query(Account).filter_by(id=movement.account_destino_id).first()
            assert dest.nombre == "Revolut"

    def test_explicit_account_owns_the_import(self, db, tmp_path):
        with _session() as s:
            bank = Account(
                nombre="Banco principal",
                tipo="efectivo_externa",
                es_propia=True,
                moneda="EUR",
            )
            s.add(bank)
            s.flush()
            bank_id = bank.id

        result = run_import(
            str(write_tr_csv(tmp_path / "banco.csv", [
                tr_row(
                    type="CARD_TRANSACTION", amount="-12.00", mcc_code="5411",
                    description="SUPERMERCADO", transaction_id="txn-bank",
                ),
            ])),
            account_id=bank_id,
        )

        assert result.account_id == bank_id
        with _session() as s:
            source_file = s.query(SourceFile).order_by(SourceFile.id.desc()).first()
            movement = s.query(FinancialMovement).filter_by(merchant="SUPERMERCADO").first()
            assert source_file.account_id == bank_id
            assert movement.account_id == bank_id
            assert movement.event.source_account_id == bank_id

    def test_import_without_accounts_proposes_new_account(self, db, tmp_path):
        with _session() as s:
            s.query(Account).delete()

        result = run_import(str(write_tr_csv(tmp_path / "solo.csv", [
            tr_row(
                type="CARD_TRANSACTION", amount="-5.00", mcc_code="5411",
                description="PANADERIA", transaction_id="txn-solo",
            ),
        ])))

        assert result.account_match["status"] == "new_account"
        assert result.account_id is None
        with _session() as s:
            assert s.query(Account).count() == 0
            assert s.query(FinancialMovement).count() == 0
            sf = s.query(SourceFile).filter_by(id=result.source_file_id).one()
            assert sf.status == "needs_review"
            assert sf.account_id is None

    def test_import_uses_rule_engine_without_per_row_session(self, db, tmp_path):
        from src.models import ClassificationRule

        with _session() as s:
            cat = s.query(Categoria).filter_by(nombre="Alimentación").first()
            s.add(ClassificationRule(
                prioridad=10, campo="mcc_code", operador="mcc_in",
                valor="5411", set_categoria_id=cat.id, auto_aprobar=True,
            ))
        result = run_import(str(write_tr_csv(tmp_path / "rule.csv", [
            tr_row(amount="-12.34", mcc_code="5411", transaction_id="txn-rule"),
        ])))
        assert result.new_count == 1
        with _session() as s:
            movement = s.query(FinancialMovement).first()
            cl = s.query(Classification).filter_by(movement_id=movement.id).first()
            assert movement.estado == "aprobado"
            assert cl.origen == "rule"
            assert cl.categoria.nombre == "Alimentación"


def test_broker_category_mapping_inversions_and_saveback():
    from src.ingest_service import _broker_category_id

    category_ids = {
        "Inversiones": 1,
        "Inversiones › Compras": 2,
        "Inversiones › Ventas": 3,
        "Inversiones › Cashback": 4,
        "Inversiones › Aportaciones": 5,
        "Transferencias": 6,
        "Transferencias › Otros": 7,
        "Ingresos › Cashback": 8,
    }
    assert _broker_category_id("inversion_compra", "BUY", category_ids) == 2
    assert _broker_category_id("inversion_venta", "SELL", category_ids) == 3
    assert _broker_category_id("aporte_activo", "FREE_RECEIPT", category_ids) == 5
    assert (
        _broker_category_id("cashback", "BENEFITS_SAVEBACK", category_ids) == 4
    )
    assert _broker_category_id("cashback", "CASHBACK", category_ids) == 4
    assert _broker_category_id("transferencia_interna", "TRANSFER", category_ids) == 7
