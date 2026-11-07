"""Tests del puente Jev ↔ pipeline de clasificación (sin red)."""

from __future__ import annotations

import pytest

from src.classify.decider import (
    DeciderNotConfigured,
    build_questions,
    decide_movement,
)
from src.config import reset_settings


class FakeProvider:
    name = "fake-jev"
    model = "jev-test"

    def __init__(self, answers):
        self.answers = answers
        self.calls = []

    def ask(self, state, questions, *, timeout=5.0):
        self.calls.append({"state": state, "questions": questions})
        return self.answers


def _choice_answer(category: str, p: float = 0.93) -> dict:
    other = max(0.0, 1.0 - p - 0.02)
    return {
        "type": "choice",
        "choice": category,
        "confidence": p,
        "probabilities": {category: p, "Compras": other},
    }


def _no_answer(p: float = 0.05) -> dict:
    return {"type": "noul", "noul": p}


def _snapshot(**overrides) -> dict:
    base = {
        "id": 1,
        "merchant": "AHORRAMAS",
        "descripcion": "Compra tarjeta",
        "amount": "-38.06",
        "kind": "gasto",
        "mcc_code": "5411",
        "broker_type": "CASH_CARD_TRANSACTION",
        "counterparty_name": None,
    }
    base.update(overrides)
    return base


class TestBuildQuestions:
    def test_category_and_review_questions(self):
        questions = build_questions(["Alimentación", "Compras"])
        assert set(questions) == {"categoria", "requiere_revision"}
        assert questions["categoria"].type.value == "choice"

    def test_transfer_question_is_optional(self):
        questions = build_questions(["Transferencias"], include_transfer=True)
        assert "es_transferencia_interna" in questions

    def test_no_categories_raises(self):
        with pytest.raises(ValueError):
            build_questions([])


class TestDecideMovement:
    def test_high_confidence_category_is_accepted(self):
        provider = FakeProvider(
            {
                "categoria": _choice_answer("Alimentación"),
                "requiere_revision": _no_answer(),
            }
        )
        result = decide_movement(_snapshot(), ["Alimentación", "Compras"], provider=provider)
        assert result["categoria"] == "Alimentación"
        assert result["needs_review"] is False
        assert result["confianza"] >= 0.9
        assert len(provider.calls) == 1
        assert "es_transferencia_interna" not in provider.calls[0]["questions"]

    def test_low_margin_requires_review(self):
        provider = FakeProvider(
            {
                "categoria": {
                    "type": "choice",
                    "choice": "Alimentación",
                    "confidence": 0.55,
                    "probabilities": {"Alimentación": 0.55, "Compras": 0.45},
                },
                "requiere_revision": _no_answer(),
            }
        )
        result = decide_movement(_snapshot(), ["Alimentación", "Compras"], provider=provider)
        assert result["categoria"] == "Alimentación"
        assert result["needs_review"] is True

    def test_invalid_category_requires_review(self):
        provider = FakeProvider(
            {
                "categoria": _choice_answer("Inexistente"),
                "requiere_revision": _no_answer(),
            }
        )
        result = decide_movement(_snapshot(), ["Alimentación", "Compras"], provider=provider)
        assert result["categoria"] is None
        assert result["needs_review"] is True

    def test_transfer_question_marks_internal(self):
        provider = FakeProvider(
            {
                "categoria": _choice_answer("Transferencias"),
                "es_transferencia_interna": {"type": "noul", "noul": 0.97},
                "requiere_revision": _no_answer(),
            }
        )
        result = decide_movement(
            _snapshot(broker_type="CASH_TRANSFER_INSTANT_OUTBOUND"),
            ["Transferencias", "Compras"],
            provider=provider,
        )
        assert result["es_transferencia_interna"] is True
        assert "es_transferencia_interna" in provider.calls[0]["questions"]

    def test_not_configured_without_key(self, monkeypatch):
        monkeypatch.setenv("TYPESAFE_API_KEY", "")
        reset_settings()
        try:
            with pytest.raises(DeciderNotConfigured):
                decide_movement(_snapshot(), ["Alimentación"], provider=None)
        finally:
            monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
            reset_settings()
