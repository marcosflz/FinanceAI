"""Tests de reglas, memoria, pipeline y job de clasificación."""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.classify import memory
from src.classify.llm_batch import (
    LLMConfigurationError,
    LLMResponseError,
    classify_batch,
)
from src.classify.pipeline import (
    classify_batch as classify_pending_batch,
)
from src.classify.pipeline import (
    classify_one,
    classify_pending,
)
from src.classify.rules import RuleEngine, run_rule_for_movement
from src.db.session import _session
from src.models import (
    Categoria,
    Classification,
    ClassificationJob,
    ClassificationRule,
    FinancialMovement,
)

from .helpers import make_movement


def _category(name: str = "Alimentación") -> int:
    with _session() as s:
        cat = s.query(Categoria).filter_by(nombre=name).first()
        return cat.id


def _add_rule(**kwargs):
    with _session() as s:
        rule = ClassificationRule(**kwargs)
        s.add(rule)
        s.flush()
        return rule.id


class TestJevIntegration:
    def test_classify_one_persists_decider_classification(self, db, monkeypatch):
        from src.classify import pipeline

        mov_id, _ = make_movement(merchant="MERCADONA", description="compra")
        monkeypatch.setattr(pipeline, "decider_is_configured", lambda: True)
        monkeypatch.setattr(
            pipeline,
            "decide_movement",
            lambda *args, **kwargs: {
                "categoria": "Alimentación",
                "confianza": 0.96,
                "needs_review": False,
                "explicacion": "Jev: supermercado",
                "model": "jev-test",
            },
        )
        result = classify_one(mov_id)
        assert result["method"] == "decider_auto"
        assert result["auto_approved"] is True
        with _session() as s:
            movement = s.query(FinancialMovement).filter_by(id=mov_id).one()
            assert movement.estado == "aprobado"
            cl = (
                s.query(Classification)
                .filter_by(movement_id=mov_id, vigente=True)
                .one()
            )
            assert cl.origen == "decider"
            assert cl.modelo == "jev-test"
            assert cl.categoria.nombre == "Alimentación"

    def test_classify_pending_autoapproves_above_threshold(self, db, monkeypatch):
        from src.classify import pipeline

        mov_id, _ = make_movement(merchant="MERCADONA", description="compra")
        monkeypatch.setattr(pipeline, "decider_is_configured", lambda: True)
        monkeypatch.setattr(
            pipeline,
            "decide_movement",
            lambda *args, **kwargs: {
                "categoria": "Alimentación",
                "confianza": 0.96,
                "needs_review": False,
                "explicacion": "Jev: supermercado",
                "model": "jev-test",
            },
        )
        stats = classify_pending()
        assert stats["auto_approved"] == 1
        with _session() as s:
            movement = s.query(FinancialMovement).filter_by(id=mov_id).one()
            assert movement.estado == "aprobado"


class TestRuleEngine:
    def test_compiles_and_evaluates_rule(self, db):
        cat_id = _category()
        _add_rule(
            prioridad=5, campo="mcc_code", operador="mcc_in", valor="5411,5422",
            set_categoria_id=cat_id, set_subtipo="variable", auto_aprobar=True,
        )
        with _session() as s:
            engine = RuleEngine.from_session(s)
            hit = engine.evaluate(
                merchant="AHORRAMAS", kind="gasto", description_clean="compra",
                mcc_code="5411", broker_type="CASH_CARD_TRANSACTION",
            )
            assert hit is not None
            assert hit.categoria_id == cat_id
            assert hit.auto_aprobar is True
            assert hit.actions["auto_aprobar"] is True

            miss = engine.evaluate(
                merchant="OTRO", kind="gasto", description_clean="compra",
                mcc_code="9999", broker_type="CASH_CARD_TRANSACTION",
            )
            assert miss is None

    def test_run_rule_for_movement_accepts_precompiled_engine(self, db):
        cat_id = _category()
        _add_rule(
            prioridad=5, campo="merchant", operador="contains", valor="AHORRAMAS",
            set_categoria_id=cat_id, set_merchant="AHORRAMAS", auto_aprobar=True,
        )
        with _session() as s:
            engine = RuleEngine.from_session(s)
        cl, actions = run_rule_for_movement(
            mov_id=1, merchant="COMPRA AHORRAMAS", kind="gasto",
            description_clean="", mcc_code=None,
            broker_type="CASH_CARD_TRANSACTION", engine=engine,
        )
        assert cl is not None
        assert cl.categoria_id == cat_id
        assert cl.origen == "rule"
        assert actions == {"set_merchant": "AHORRAMAS", "auto_aprobar": True}

    def test_regex_and_equals_operators(self, db):
        cat_id = _category()
        _add_rule(
            prioridad=1, campo="merchant", operador="regex", valor=r"^AMZN.*",
            set_categoria_id=cat_id,
        )
        _add_rule(
            prioridad=2, campo="kind", operador="equals", valor="ingreso",
            set_categoria_id=cat_id,
        )
        with _session() as s:
            engine = RuleEngine.from_session(s)
        hit = engine.evaluate(
            merchant="AMZN Mktp", kind="gasto", description_clean="",
            mcc_code=None, broker_type=None,
        )
        assert hit is not None and hit.categoria_id == cat_id
        hit2 = engine.evaluate(
            merchant="OTRO", kind="ingreso", description_clean="",
            mcc_code=None, broker_type=None,
        )
        assert hit2 is not None and hit2.categoria_id == cat_id


class TestMemory:
    def test_record_lookup_and_timestamp(self, db):
        cat_id = _category()
        memory.record(1, "AHORRAMAS", "5411", "CASH_CARD_TRANSACTION", cat_id)
        hit = memory.lookup(1, "AHORRAMAS", "5411", "CASH_CARD_TRANSACTION")
        assert hit is not None
        assert hit["categoria_id"] == cat_id
        assert hit["confianza"] >= Decimal("0.60")

        with _session() as s:
            entry = s.query(memory.ClassificationMemory).first()
            assert entry.ultimo_uso_en is not None
            assert entry.veces_confirmado == 1

    def test_confirmation_increases_confidence(self, db):
        cat_id = _category()
        memory.record(1, "AHORRAMAS", None, None, cat_id)
        memory.record(2, "AHORRAMAS", None, None, cat_id)
        hit = memory.lookup(2, "AHORRAMAS", None, None)
        assert hit["confianza"] == Decimal("0.82")

    def test_correction_degrades_and_deactivates(self, db):
        cat_id = _category()
        other_id = _category("Compras")
        memory.record(1, "AHORRAMAS", None, None, cat_id)

        memory.correct(1, "AHORRAMAS", None, None, other_id)
        with _session() as s:
            entry = s.query(memory.ClassificationMemory).first()
            assert entry.categoria_id == other_id
            assert entry.confianza == Decimal("0.56")
            assert entry.activo is True

        memory.correct(1, "AHORRAMAS", None, None, other_id)
        assert memory.lookup(1, "AHORRAMAS", None, None) is None
        with _session() as s:
            entry = s.query(memory.ClassificationMemory).first()
            assert entry.activo is False
            assert entry.veces_corregido == 2
            assert entry.ultimo_uso_en is not None

    def test_correction_without_precedent_creates_entry(self, db):
        cat_id = _category()
        memory.correct(1, "NUEVO", None, None, cat_id)
        hit = memory.lookup(1, "NUEVO", None, None)
        assert hit is not None
        assert hit["confianza"] == Decimal("0.80")


class TestPipeline:
    def test_classify_pending_applies_rules_in_batch(self, db):
        cat_id = _category()
        _add_rule(
            prioridad=5, campo="mcc_code", operador="mcc_in", valor="5411",
            set_categoria_id=cat_id, auto_aprobar=True,
        )
        mov_id, _ = make_movement(
            merchant="AHORRAMAS", mcc_code="5411", amount=Decimal("-12.00"),
        )
        stats = classify_pending()
        assert stats["total"] == 1
        assert stats["rule"] == 1
        assert stats["failed"] == 0
        with _session() as s:
            mov = s.query(FinancialMovement).filter_by(id=mov_id).first()
            cl = s.query(Classification).filter_by(movement_id=mov_id, vigente=True).first()
            assert mov.estado == "aprobado"
            assert cl is not None and cl.categoria_id == cat_id

    def test_classify_pending_marks_failures_when_llm_unavailable(
        self, db, monkeypatch,
    ):
        mov_id, _ = make_movement(merchant="DESCONOCIDO", mcc_code=None)

        def _boom(*args, **kwargs):
            raise LLMConfigurationError("sin API key")

        monkeypatch.setattr("src.classify.pipeline.llm_classify_batch", _boom)
        stats = classify_pending()
        assert stats["total"] == 1
        assert stats["failed"] == 1
        assert stats["failed_ids"] == [mov_id]
        assert "sin API key" in stats["error"]

    def test_classify_pending_marks_partial_llm_results_as_failed(
        self, db, monkeypatch,
    ):
        first_id, _ = make_movement(merchant="UNO", mcc_code=None)
        second_id, _ = make_movement(merchant="DOS", mcc_code=None)

        def _partial(movements, categorias, subtipos):
            return [{
                "id": first_id, "categoria": categorias[0],
                "subtipo": None, "confianza": 0.9, "explicacion": "ok",
            }]

        monkeypatch.setattr("src.classify.pipeline.llm_classify_batch", _partial)
        stats = classify_pending()
        assert stats["llm"] == 1
        assert stats["failed"] == 1
        assert stats["failed_ids"] == [second_id]

    def test_classify_pending_autoapproves_already_classified(self, db, monkeypatch):
        cat_id = _category("Transferencias")
        mov_id, _ = make_movement(merchant="TRANSFER", kind="inversion_compra",
                                  broker_type="CASH_BUY")
        with _session() as s:
            s.add(Classification(
                movement_id=mov_id, categoria_id=cat_id, origen="broker",
                confianza=Decimal("0.99"), vigente=True,
            ))

        def _must_not_call(*args, **kwargs):
            raise AssertionError("no debe llamarse al LLM")

        monkeypatch.setattr("src.classify.pipeline.llm_classify_batch", _must_not_call)
        stats = classify_pending()
        assert stats["total"] == 1
        assert stats["auto_approved"] == 1
        with _session() as s:
            assert s.query(FinancialMovement).filter_by(id=mov_id).one().estado == "aprobado"
        assert stats["failed"] == 0

    def test_classify_pending_keeps_transfers_in_review(self, db, monkeypatch):
        cat_id = _category("Transferencias")
        mov_id, _ = make_movement(
            merchant="TRANSFER", kind="transferencia_interna",
            broker_type="CASH_TRANSFER_INSTANT_OUTBOUND",
        )
        with _session() as s:
            s.add(Classification(
                movement_id=mov_id, categoria_id=cat_id, origen="broker",
                confianza=Decimal("0.99"), vigente=True,
            ))
        monkeypatch.setattr(
            "src.classify.pipeline.llm_classify_batch",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("sin LLM")),
        )
        classify_pending()
        with _session() as s:
            movement = s.query(FinancialMovement).filter_by(id=mov_id).one()
            assert movement.estado == "pendiente"
            cl = s.query(Classification).filter_by(movement_id=mov_id, vigente=True).one()
            assert cl.categoria_id == cat_id  # propuesta conservada

    def test_classify_one_reports_typed_llm_error(self, db, monkeypatch):
        mov_id, _ = make_movement(merchant="DESCONOCIDO", mcc_code=None)

        def _boom(*args, **kwargs):
            raise LLMConfigurationError("config rota")

        monkeypatch.setattr("src.classify.pipeline.llm_classify_one", _boom)
        result = classify_one(mov_id)
        assert result["method"] == "failed"
        assert "config rota" in result["error"]


class TestLLMErrors:
    def test_missing_api_key_is_typed(self, monkeypatch):
        monkeypatch.setattr(
            "src.classify.llm_batch.resolve_llm_settings",
            lambda: {"api_key": "", "base_url": "", "model": "m", "provider": ""},
        )
        with pytest.raises(LLMConfigurationError):
            classify_batch([{"id": 1, "merchant": "X"}], ["Alimentación"])

    def test_invalid_json_is_typed(self, monkeypatch):
        from types import SimpleNamespace

        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="no es json"))]
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=lambda **kwargs: response)
            )
        )

        monkeypatch.setattr(
            "src.classify.llm_batch.resolve_llm_settings",
            lambda: {"api_key": "k", "base_url": "", "model": "m", "provider": ""},
        )
        monkeypatch.setattr("src.classify.llm_batch.OpenAI", lambda **kw: client)
        with pytest.raises(LLMResponseError):
            classify_batch([{"id": 1, "merchant": "X"}], ["Alimentación"])


class TestClassifyJob:
    def test_job_is_failed_not_completed_when_llm_returns_nothing(
        self, db, monkeypatch,
    ):
        import src.v2_api as v2

        make_movement(merchant="UNO", mcc_code=None)
        make_movement(merchant="DOS", mcc_code=None)
        with _session() as s:
            job = ClassificationJob(status="pending")
            s.add(job)
            s.flush()
            job_id = job.id

        monkeypatch.setattr(v2, "classify_batch", lambda *a, **kw: [])
        v2._run_classify_job(job_id)

        with _session() as s:
            job = s.query(ClassificationJob).filter_by(id=job_id).first()
            assert job.status == "failed"
            assert job.failed_count == 2
            assert job.finished_at is not None
            assert s.query(Classification).count() == 0
        # El import roto del P0-12 queda cubierto: classify_one existe en v2.
        assert callable(v2.classify_one)

    def test_job_marks_ids_missing_from_partial_batch_as_failed(
        self, db, monkeypatch,
    ):
        import src.v2_api as v2

        first_id, _ = make_movement(merchant="UNO", mcc_code=None)
        make_movement(merchant="DOS", mcc_code=None)
        with _session() as s:
            job = ClassificationJob(status="pending")
            s.add(job)
            s.flush()
            job_id = job.id

        def _partial(chunk, categorias, subtipos):
            return [{
                "id": first_id, "categoria": categorias[0],
                "subtipo": None, "confianza": 0.9, "explicacion": "ok",
            }]

        monkeypatch.setattr(v2, "classify_batch", _partial)
        v2._run_classify_job(job_id)

        with _session() as s:
            job = s.query(ClassificationJob).filter_by(id=job_id).first()
            assert job.status == "failed"
            assert job.llm_count == 1
            assert job.failed_count == 1
            assert job.failed_count + job.llm_count == 2


class TestBatchClassification:
    def test_batch_persists_decider_suggestions_and_grows_references(
        self, db, monkeypatch,
    ):
        from src.classify import pipeline

        first_id, _ = make_movement(merchant="MERCADONA", description="compra")
        second_id, _ = make_movement(merchant="ENDESA", description="luz")
        monkeypatch.setattr(pipeline, "decider_is_configured", lambda: True)
        seen_precedents: list[int] = []

        def fake_decide(snapshot, categories, *, precedents=None, **kwargs):
            seen_precedents.append(len(precedents or []))
            return {
                "categoria": categories[0],
                "confianza": 0.94,
                "needs_review": False,
                "explicacion": "fake",
                "model": "fake-jev",
            }

        monkeypatch.setattr(pipeline, "decide_movement", fake_decide)
        result = classify_pending_batch(limit=10)
        assert result["processed"] == 2
        assert result["reference_count"] == 0
        assert all(item["method"].startswith("decider") for item in result["items"])
        assert seen_precedents == [0, 0]

        # El usuario acepta la primera; el siguiente lote debe enviar 1 ejemplo.
        with _session() as s:
            cl = s.query(Classification).filter_by(movement_id=first_id).first()
            cl.origen = "user"
            cl.confianza = Decimal("1.0")
            movement = s.query(FinancialMovement).filter_by(id=first_id).first()
            movement.estado = "aprobado"
            s.flush()
        third_id, _ = make_movement(merchant="IBERDROLA", description="luz")
        result = classify_pending_batch(limit=10)
        assert result["processed"] == 1
        assert result["reference_count"] == 1
        assert seen_precedents[-1] == 1
        assert result["items"][0]["movement_id"] == third_id
        assert second_id != third_id
