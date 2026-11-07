"""Tests del orquestador de decisión: umbrales, cache y revisión."""

from __future__ import annotations

import pytest

from src.ai.decision import DecisionOrchestrator, DecisionProvider, Thresholds
from src.ai.jev import JevAnswer
from src.ai.schemas import DecisionQuestion


class FakeProvider:
    name = "fake"
    model = "fake-1"

    def __init__(self, answers):
        self.answers = answers
        self.calls: list[dict] = []

    def ask(self, state, questions, *, timeout: float = 5.0):
        self.calls.append(
            {"state": state, "questions": questions, "timeout": timeout}
        )
        return self.answers


def _orchestrator(answers):
    provider = FakeProvider(answers)
    return DecisionOrchestrator(provider), provider


def _choice(choice: str, confidence: float, probabilities=None) -> dict:
    return {
        "type": "choice",
        "choice": choice,
        "confidence": confidence,
        "probabilities": probabilities or {choice: confidence},
    }


def _category_question() -> DecisionQuestion:
    return DecisionQuestion.choice(
        "¿Qué categoría es?",
        {"Alimentación": "Supermercado", "Otros": "Ninguna de las anteriores"},
    )


def test_high_confidence_choice_auto_accepts() -> None:
    orchestrator, provider = _orchestrator(
        {
            "categoria": _choice(
                "Alimentación", 0.95, {"Alimentación": 0.95, "Otros": 0.05}
            )
        }
    )

    result = orchestrator.decide(
        {"merchant": "AHORRAMAS", "amount": "-38.06"},
        {"categoria": _category_question()},
    )

    assert result.needs_review is False
    assert result.confidence == pytest.approx(0.95)
    assert result.provider == "fake"
    assert result.model == "fake-1"
    assert result.cached is False
    assert result.state_hash
    assert result.answers["categoria"]["top2_margin"] == pytest.approx(0.90)
    assert result.answers["categoria"]["confidence_source"] == "provider"
    assert "Auto-aceptado" in result.explanation
    assert "categoria=Alimentación" in result.explanation
    assert len(provider.calls) == 1


def test_low_top2_margin_forces_review() -> None:
    orchestrator, _ = _orchestrator(
        {"categoria": _choice("A", 0.91, {"A": 0.91, "B": 0.80})}
    )

    result = orchestrator.decide(
        {"merchant": "X"}, {"categoria": _category_question()}
    )

    assert result.needs_review is True
    assert "margen top-2" in result.explanation


def test_margin_rule_only_applies_to_category_questions() -> None:
    orchestrator, _ = _orchestrator(
        {
            "kind": _choice(
                "gasto", 0.95, {"gasto": 0.95, "ingreso": 0.85}
            )
        }
    )

    result = orchestrator.decide(
        {"merchant": "X", "amount": "-10"},
        {
            "kind": DecisionQuestion.choice(
                "¿Qué tipo de movimiento es?",
                {"gasto": "Sale dinero", "ingreso": "Entra dinero"},
            )
        },
    )

    assert result.needs_review is False
    assert result.answers["kind"]["top2_margin"] == pytest.approx(0.10)


def test_exact_category_threshold_auto_accepts() -> None:
    orchestrator, _ = _orchestrator(
        {"categoria": _choice("A", 0.90, {"A": 0.90, "B": 0.74})}
    )

    result = orchestrator.decide(
        {"merchant": "X"}, {"categoria": _category_question()}
    )

    assert result.needs_review is False
    assert result.confidence == pytest.approx(0.90)


def test_just_below_category_threshold_needs_review() -> None:
    orchestrator, _ = _orchestrator(
        {"categoria": _choice("A", 0.89, {"A": 0.89, "B": 0.05})}
    )

    result = orchestrator.decide(
        {"merchant": "X"}, {"categoria": _category_question()}
    )

    assert result.needs_review is True
    assert "auto-aceptación" in result.explanation


def test_below_review_threshold_mentions_review() -> None:
    orchestrator, _ = _orchestrator(
        {"categoria": _choice("A", 0.72, {"A": 0.72, "B": 0.10})}
    )

    result = orchestrator.decide(
        {"merchant": "X"}, {"categoria": _category_question()}
    )

    assert result.needs_review is True
    assert "revisión" in result.explanation
    assert result.confidence == pytest.approx(0.72)


def test_transfer_threshold_uses_noul_probability() -> None:
    question = DecisionQuestion.noul("¿Es una transferencia interna?")

    high_orchestrator, _ = _orchestrator(
        {"es_transferencia_interna": {"type": "noul", "noul": 0.98}}
    )
    high = high_orchestrator.decide(
        {"counterparty": "Revolut"}, {"es_transferencia_interna": question}
    )
    assert high.needs_review is False
    assert high.confidence == pytest.approx(0.96)
    assert high.answers["es_transferencia_interna"]["decision_strength"] == (
        pytest.approx(0.98)
    )

    low_orchestrator, _ = _orchestrator(
        {"es_transferencia_interna": {"type": "noul", "noul": 0.93}}
    )
    low = low_orchestrator.decide(
        {"counterparty": "Revolut"}, {"es_transferencia_interna": question}
    )
    assert low.needs_review is True
    assert low.confidence == pytest.approx(0.86)
    assert "0.95" in low.explanation

    # Un "no" muy seguro también es auto-aceptable.
    no_orchestrator, _ = _orchestrator(
        {"es_transferencia_interna": {"type": "noul", "noul": 0.02}}
    )
    no = no_orchestrator.decide(
        {"counterparty": "Amazon"}, {"es_transferencia_interna": question}
    )
    assert no.needs_review is False
    assert no.answers["es_transferencia_interna"]["decision_strength"] == (
        pytest.approx(0.98)
    )

    # P = 0.95 es exactamente el umbral del plan: auto-aceptable.
    boundary_orchestrator, _ = _orchestrator(
        {"es_transferencia_interna": {"type": "noul", "noul": 0.95}}
    )
    boundary = boundary_orchestrator.decide(
        {"counterparty": "Revolut"}, {"es_transferencia_interna": question}
    )
    assert boundary.needs_review is False
    assert boundary.confidence == pytest.approx(0.90)


def test_duplicate_threshold() -> None:
    question = DecisionQuestion.noul("¿Es un duplicado probable?")

    high_orchestrator, _ = _orchestrator(
        {"es_duplicado_probable": {"type": "noul", "noul": 0.96}}
    )
    high = high_orchestrator.decide(
        {"movement_a": 1, "movement_b": 2},
        {"es_duplicado_probable": question},
    )
    assert high.needs_review is False

    # P = 0.90 es exactamente el umbral del plan: auto-aceptable.
    boundary_orchestrator, _ = _orchestrator(
        {"es_duplicado_probable": {"type": "noul", "noul": 0.90}}
    )
    boundary = boundary_orchestrator.decide(
        {"movement_a": 1, "movement_b": 2},
        {"es_duplicado_probable": question},
    )
    assert boundary.needs_review is False

    low_orchestrator, _ = _orchestrator(
        {"es_duplicado_probable": {"type": "noul", "noul": 0.89}}
    )
    low = low_orchestrator.decide(
        {"movement_a": 1, "movement_b": 2},
        {"es_duplicado_probable": question},
    )
    assert low.needs_review is True
    assert low.confidence == pytest.approx(0.78)


def test_review_flag_question_forces_review() -> None:
    question = DecisionQuestion.noul("¿Requiere revisión humana?")

    review_orchestrator, _ = _orchestrator(
        {"requiere_revision": {"type": "noul", "noul": 0.90}}
    )
    review = review_orchestrator.decide(
        {"merchant": "X"}, {"requiere_revision": question}
    )
    assert review.needs_review is True
    assert "recomienda revisión" in review.explanation

    ok_orchestrator, _ = _orchestrator(
        {"requiere_revision": {"type": "noul", "noul": 0.10}}
    )
    ok = ok_orchestrator.decide(
        {"merchant": "X"}, {"requiere_revision": question}
    )
    assert ok.needs_review is False


def test_risk_high_forces_human_review() -> None:
    answers = {
        "categoria": _choice(
            "Alimentación", 0.99, {"Alimentación": 0.99, "Otros": 0.01}
        )
    }
    orchestrator, _ = _orchestrator(answers)

    normal = orchestrator.decide(
        {"merchant": "AHORRAMAS"}, {"categoria": _category_question()}
    )
    assert normal.needs_review is False

    high = orchestrator.decide(
        {"merchant": "AHORRAMAS"},
        {"categoria": _category_question()},
        risk="high",
        use_cache=False,
    )
    assert high.needs_review is True
    assert "riesgo" in high.explanation


def test_cache_hits_by_state_and_questions() -> None:
    answers = {
        "categoria": _choice(
            "Alimentación", 0.95, {"Alimentación": 0.95, "Otros": 0.05}
        )
    }
    orchestrator, provider = _orchestrator(answers)
    state = {"merchant": "AHORRAMAS", "amount": "-38.06"}
    questions = {"categoria": _category_question()}

    first = orchestrator.decide(state, questions)
    second = orchestrator.decide(state, questions)
    assert len(provider.calls) == 1
    assert first.cached is False
    assert second.cached is True
    assert first.state_hash == second.state_hash

    # Cambiar el estado invalida la cache.
    orchestrator.decide({"merchant": "OTRO"}, questions)
    assert len(provider.calls) == 2

    # Cambiar las preguntas también invalida la cache.
    other_question = DecisionQuestion.choice(
        "¿Qué categoría es? (v2)",
        {"Alimentación": "Supermercado", "Otros": "Ninguna"},
    )
    orchestrator.decide(state, {"categoria": other_question})
    assert len(provider.calls) == 3


def test_risk_change_reuses_cached_answers_without_calling_provider() -> None:
    answers = {
        "categoria": _choice(
            "Alimentación", 0.95, {"Alimentación": 0.95, "Otros": 0.05}
        )
    }
    orchestrator, provider = _orchestrator(answers)
    state = {"merchant": "AHORRAMAS"}
    questions = {"categoria": _category_question()}

    assert orchestrator.decide(state, questions).needs_review is False
    risky = orchestrator.decide(state, questions, risk="high")
    assert len(provider.calls) == 1
    assert risky.cached is True
    assert risky.needs_review is True


def test_missing_answer_goes_to_review() -> None:
    orchestrator, _ = _orchestrator({})

    result = orchestrator.decide(
        {"merchant": "X"}, {"categoria": _category_question()}
    )

    assert result.needs_review is True
    assert "sin respuesta" in result.explanation
    assert result.answers["categoria"]["missing"] is True
    assert result.confidence == 0.0


def test_jev_answer_objects_are_accepted() -> None:
    answer = JevAnswer.from_payload(
        "categoria",
        {
            "type": "choice",
            "choice": "Alimentación",
            "confidence": 0.97,
            "probabilities": {"Alimentación": 0.97, "Otros": 0.03},
        },
    )
    orchestrator, _ = _orchestrator({"categoria": answer})

    result = orchestrator.decide(
        {"merchant": "AHORRAMAS"}, {"categoria": _category_question()}
    )

    assert result.needs_review is False
    assert result.answers["categoria"]["choice"] == "Alimentación"


def test_custom_thresholds_are_applied() -> None:
    answers = {
        "categoria": _choice(
            "Alimentación", 0.95, {"Alimentación": 0.95, "Otros": 0.05}
        )
    }
    provider = FakeProvider(answers)
    orchestrator = DecisionOrchestrator(
        provider,
        thresholds=Thresholds(category_auto=0.99, category_margin=0.05),
    )

    result = orchestrator.decide(
        {"merchant": "AHORRAMAS"}, {"categoria": _category_question()}
    )

    assert result.needs_review is True
    assert "0.99" in result.explanation


def test_fake_provider_satisfies_protocol() -> None:
    assert isinstance(FakeProvider({}), DecisionProvider)
