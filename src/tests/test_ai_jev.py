"""Tests de contrato del proveedor Jev (TypeSafe), sin red real."""

from __future__ import annotations

import json

import httpx
import pytest

from src.ai.jev import (
    JevAuthError,
    JevProvider,
    JevResponseError,
)
from src.ai.schemas import DecisionQuestion

STATE_SENTINEL = "estado-secreto-que-no-debe-aparecer-en-errores"


def _provider(handler, **kwargs):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    options = {
        "base_url": "https://api.typesafe.ai/v1/systemone",
        "model": "jev-latest",
        "max_retries": 2,
        "backoff_base": 0.5,
    }
    options.update(kwargs)
    provider = JevProvider(
        api_key="typesafe-test-key",
        transport=httpx.MockTransport(wrapped),
        sleep=lambda _: None,
        **options,
    )
    return provider, calls


def _answer_payload(**overrides) -> dict:
    payload = {
        "model": "jev-1.13.0",
        "answers": {
            "categoria": {
                "type": "choice",
                "choice": "Alimentación",
                "confidence": 0.97,
                "probabilities": {
                    "Alimentación": 0.97,
                    "Transporte": 0.02,
                    "Otros": 0.01,
                },
            },
            "es_transferencia_interna": {"type": "noul", "noul": 0.02},
        },
        "usage": {"input_tokens": 120, "output_tokens": 10},
    }
    payload.update(overrides)
    return payload


def test_choice_request_and_answer() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(200, json=_answer_payload())

    provider, _ = _provider(handler)
    try:
        result = provider.system_one(
            {
                "merchant": "AHORRAMAS",
                "amount": "-38.06",
                "mcc": "5411",
                "precedents": [],
            },
            {
                "categoria": DecisionQuestion.choice(
                    "¿Qué categoría es?",
                    {
                        "Alimentación": "Supermercado",
                        "Transporte": "Gasolina y transporte",
                        "Otros": None,
                    },
                ),
                "es_transferencia_interna": DecisionQuestion.noul(
                    "¿Es una transferencia entre cuentas propias?"
                ),
            },
        )
    finally:
        provider.close()

    request = captured["request"]
    assert request.url.path == "/v1/systemone"
    assert request.headers["authorization"] == "Bearer typesafe-test-key"
    assert request.headers["user-agent"] == "financial-tools/0.1"
    body = json.loads(request.content)
    assert body["model"] == "jev-latest"
    assert body["state"]["merchant"] == "AHORRAMAS"
    assert body["questions"]["categoria"]["type"] == "choice"
    assert body["questions"]["categoria"]["criteria"]["Otros"] is None
    assert (
        body["questions"]["es_transferencia_interna"]["type"] == "noul"
    )

    assert result.model == "jev-1.13.0"
    assert result.requested_model == "jev-latest"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 10

    category = result.answers["categoria"]
    assert category.type == "choice"
    assert category.choice == "Alimentación"
    assert category.confidence == pytest.approx(0.97)
    assert category.confidence_derived is False
    assert category.probabilities["Transporte"] == pytest.approx(0.02)
    assert category.top2_margin == pytest.approx(0.95)
    assert category.selected_probability == pytest.approx(0.97)

    transfer = result.answers["es_transferencia_interna"]
    assert transfer.type == "noul"
    assert transfer.noul == pytest.approx(0.02)
    assert transfer.confidence == pytest.approx(0.96)
    assert transfer.confidence_derived is True


def test_noul_confidence_is_derived_when_missing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "urgente": {"type": "noul", "noul": 0.90},
                    "no_urgente": {"type": "noul", "noul": 0.10},
                },
                "usage": {},
            },
        )

    provider, _ = _provider(handler)
    try:
        answers = provider.ask(
            STATE_SENTINEL,
            {
                "urgente": DecisionQuestion.noul("¿Es urgente?"),
                "no_urgente": DecisionQuestion.noul("¿Es urgente?"),
            },
        )
    finally:
        provider.close()

    assert answers["urgente"].effective_confidence == pytest.approx(0.80)
    assert answers["urgente"].confidence == pytest.approx(0.80)
    assert answers["no_urgente"].effective_confidence == pytest.approx(0.80)


def test_score_answer() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "frustration": {
                        "type": "score",
                        "score": 1.0,
                        "confidence": 0.67,
                        "legend": {
                            "0": "Calm",
                            "1": "Frustrated but civil",
                            "2": "Very angry",
                        },
                        "probabilities": {"0": 0.10, "1": 0.67, "2": 0.23},
                    }
                },
                "usage": {"input_tokens": 30, "output_tokens": 5},
            },
        )

    provider, _ = _provider(handler)
    try:
        result = provider.system_one(
            STATE_SENTINEL,
            {
                "frustration": DecisionQuestion.score(
                    "¿Cómo de frustrado está?",
                    ["Calm", "Frustrated but civil", "Very angry"],
                )
            },
        )
    finally:
        provider.close()

    answer = result.answers["frustration"]
    assert answer.type == "score"
    assert answer.score == pytest.approx(1.0)
    assert answer.confidence == pytest.approx(0.67)
    assert answer.legend["2"] == "Very angry"
    assert answer.probabilities["1"] == pytest.approx(0.67)


def test_rate_limit_retries_then_succeeds() -> None:
    calls: list[int] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(200, json=_answer_payload())

    provider, _ = _provider(handler, max_retries=2)
    provider._sleep = sleeps.append
    try:
        answers = provider.ask(
            {"merchant": "AHORRAMAS"},
            {"categoria": DecisionQuestion.choice("¿Categoría?", {"Alimentación": ""})},
        )
    finally:
        provider.close()

    assert len(calls) == 2
    assert sleeps == [0.5]
    assert answers["categoria"].choice == "Alimentación"


def test_auth_error_is_not_retried_and_does_not_echo_state() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            401,
            json={"error": "invalid key", "state": STATE_SENTINEL},
        )

    provider, _ = _provider(handler, max_retries=3)
    try:
        with pytest.raises(JevAuthError) as exc_info:
            provider.ask(
                STATE_SENTINEL,
                {"categoria": DecisionQuestion.choice("¿Categoría?", {"A": ""})},
            )
    finally:
        provider.close()

    assert len(calls) == 1
    assert STATE_SENTINEL not in str(exc_info.value)
    assert "typesafe-test-key" not in str(exc_info.value)


def test_invalid_json_retries_then_raises() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, text="no soy JSON")

    provider, _ = _provider(handler, max_retries=1)
    try:
        with pytest.raises(JevResponseError) as exc_info:
            provider.ask(
                STATE_SENTINEL,
                {"categoria": DecisionQuestion.choice("¿Categoría?", {"A": ""})},
            )
    finally:
        provider.close()

    assert len(calls) == 2
    assert STATE_SENTINEL not in str(exc_info.value)


def test_missing_api_key_raises_without_request(monkeypatch) -> None:
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=_answer_payload())

    provider = JevProvider(api_key="", transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(JevAuthError):
            provider.ask(
                {"merchant": "X"},
                {"categoria": DecisionQuestion.choice("¿Categoría?", {"A": ""})},
            )
    finally:
        provider.close()

    assert calls == []


def test_questions_accept_plain_mappings() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "jev-1.13.0",
                "answers": {
                    "categoria": {
                        "type": "choice",
                        "choice": "Alimentación",
                        "confidence": 0.9,
                        "probabilities": {"Alimentación": 0.9, "Otros": 0.1},
                    }
                },
                "usage": {},
            },
        )

    provider, _ = _provider(handler)
    try:
        answers = provider.ask(
            "state",
            {
                "categoria": {
                    "type": "choice",
                    "instructions": "¿Categoría?",
                    "criteria": {"Alimentación": "", "Otros": ""},
                }
            },
        )
    finally:
        provider.close()

    assert answers["categoria"].choice == "Alimentación"


def test_session_id_is_not_required_for_jev() -> None:
    """Jev no usa x-opencode-session; el header no debe enviarse."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert "x-opencode-session" not in request.headers
        return httpx.Response(200, json=_answer_payload())

    provider, _ = _provider(handler)
    try:
        provider.ask(
            {"merchant": "AHORRAMAS"},
            {"categoria": DecisionQuestion.choice("¿Categoría?", {"Alimentación": ""})},
        )
    finally:
        provider.close()
