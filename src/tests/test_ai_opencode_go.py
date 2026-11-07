"""Tests de contrato del cliente OpenCode Go (sin red real)."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest
from pydantic import BaseModel

from src.ai.opencode_go import (
    OpenCodeAuthError,
    OpenCodeGoClient,
    OpenCodeResponseError,
    api_family_for_model,
    parse_json_text,
)

PRIMARY = "deepseek-v4.1-flash"
FALLBACK = "glm-5.3-flash"


class CategoryAnswer(BaseModel):
    category: str
    confidence: float


def _chat_payload(
    content: str,
    *,
    model: str = PRIMARY,
    allowance: object = 0.0012,
) -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cost": 0.0001,
            "opencode": {
                "billing_source": "go",
                "list_cost": 0.0001,
                "allowance": allowance,
                "tokens": {
                    "input": 100,
                    "output": 20,
                    "reasoning": 3,
                    "cache_read": 5,
                    "cache_write_5m": 0,
                    "cache_write_1h": 0,
                },
            },
        },
    }


def _responses_payload(
    text: str,
    *,
    model: str = "gpt-6-luna",
    allowance: object = 0.002,
) -> dict:
    return {
        "id": "resp-test",
        "object": "response",
        "model": model,
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": 50,
            "output_tokens": 10,
            "total_tokens": 60,
            "cost": 0.0002,
            "opencode": {
                "billing_source": "go",
                "list_cost": 0.0002,
                "allowance": allowance,
            },
        },
    }


def _client(handler, **kwargs):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    options = {
        "base_url": "https://opencode.ai/inference/go",
        "model": PRIMARY,
        "fallback_models": [],
        "max_retries": 3,
        "backoff_base": 0.5,
        "min_allowance_ratio": 0.20,
    }
    options.update(kwargs)
    client = OpenCodeGoClient(
        api_key="oc_sk_test",
        transport=httpx.MockTransport(wrapped),
        sleep=lambda _: None,
        **options,
    )
    return client, calls


def test_chat_structured_success_and_headers() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=_chat_payload(
                json.dumps({"category": "Alimentación", "confidence": 0.97})
            ),
        )

    client, calls = _client(handler)
    try:
        result = client.chat(
            [{"role": "user", "content": "clasifica AHORRAMAS"}],
            model=PRIMARY,
            schema=CategoryAnswer,
            session_id="session-123",
        )
    finally:
        client.close()

    assert len(calls) == 1
    request = captured["request"]
    assert request.url.path == "/inference/go/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer oc_sk_test"
    assert request.headers["user-agent"] == "financial-tools/0.1"
    assert request.headers["x-opencode-session"] == "session-123"

    body = json.loads(request.content)
    assert body["model"] == PRIMARY
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]
    assert schema["name"] == "CategoryAnswer"
    assert schema["strict"] is True
    assert schema["schema"]["title"] == "CategoryAnswer"
    assert body["temperature"] == 0.0

    assert isinstance(result.parsed, CategoryAnswer)
    assert result.parsed.category == "Alimentación"
    assert result.parsed.confidence == 0.97
    assert result.model == PRIMARY
    assert result.api == "chat"
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 20
    assert result.usage.total_tokens == 120
    assert result.usage.reasoning_tokens == 3
    assert result.usage.cache_read_tokens == 5
    assert result.usage.billing_source == "go"
    assert result.billing_source == "go"
    assert result.allowance.spent_usd == Decimal("0.0012")
    assert result.allowance.is_low() is False
    assert result.raw["id"] == "chatcmpl-test"


def test_chat_invalid_json_retries_and_succeeds() -> None:
    calls: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model"])
        if len(calls) == 1:
            return httpx.Response(200, json=_chat_payload("esto no es JSON"))
        return httpx.Response(
            200,
            json=_chat_payload(
                json.dumps({"category": "Transporte", "confidence": 0.9})
            ),
        )

    client, _ = _client(handler, max_retries=1)
    client._sleep = sleeps.append
    try:
        result = client.chat(
            [{"role": "user", "content": "clasifica"}],
            schema=CategoryAnswer,
        )
    finally:
        client.close()

    assert calls == [PRIMARY, PRIMARY]
    assert sleeps == [0.5]
    assert result.parsed is not None
    assert result.parsed.category == "Transporte"


def test_rate_limit_retries_then_succeeds_same_model() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model"])
        if len(calls) == 1:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(
            200,
            json=_chat_payload(
                json.dumps({"category": "Ocio", "confidence": 0.95})
            ),
        )

    client, _ = _client(handler, max_retries=2)
    try:
        result = client.chat(
            [{"role": "user", "content": "clasifica"}],
            schema=CategoryAnswer,
        )
    finally:
        client.close()

    assert calls == [PRIMARY, PRIMARY]
    assert result.parsed.category == "Ocio"


def test_rate_limit_falls_back_to_next_model() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == PRIMARY:
            return httpx.Response(429, json={"error": "rate limit"})
        return httpx.Response(
            200,
            json=_chat_payload(
                json.dumps({"category": "Alimentación", "confidence": 0.93}),
                model=model,
            ),
        )

    client, _ = _client(
        handler,
        max_retries=0,
        fallback_models=[FALLBACK],
    )
    try:
        result = client.complete(
            messages=[{"role": "user", "content": "clasifica"}],
            schema=CategoryAnswer,
        )
    finally:
        client.close()

    assert calls == [PRIMARY, FALLBACK]
    assert result.model == FALLBACK
    assert result.fallback_used is True
    assert result.attempted_models == [PRIMARY, FALLBACK]


def test_auth_error_never_retries_or_falls_back() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": "invalid api key"})

    client, _ = _client(
        handler,
        max_retries=3,
        fallback_models=[FALLBACK],
    )
    try:
        with pytest.raises(OpenCodeAuthError) as exc_info:
            client.complete(
                messages=[{"role": "user", "content": "clasifica"}],
                schema=CategoryAnswer,
            )
    finally:
        client.close()

    assert len(calls) == 1
    assert "oc_sk_test" not in str(exc_info.value)


def test_responses_structured_output() -> None:
    captured: dict[str, httpx.Request] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        return httpx.Response(
            200,
            json=_responses_payload(
                json.dumps({"category": "Salud", "confidence": 0.98})
            ),
        )

    client, _ = _client(handler)
    try:
        result = client.responses(
            "clasifica la farmacia",
            model="gpt-6-luna",
            schema=CategoryAnswer,
            session_id="doc-1",
        )
    finally:
        client.close()

    request = captured["request"]
    assert request.url.path == "/inference/go/openai/v1/responses"
    body = json.loads(request.content)
    assert body["input"] == "clasifica la farmacia"
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["name"] == "CategoryAnswer"
    assert body["text"]["format"]["schema"]["title"] == "CategoryAnswer"

    assert isinstance(result.parsed, CategoryAnswer)
    assert result.parsed.category == "Salud"
    assert result.api == "responses"
    assert result.usage.input_tokens == 50
    assert result.usage.output_tokens == 10
    assert result.usage.billing_source == "go"


def test_low_allowance_triggers_fallback() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        calls.append(model)
        if model == PRIMARY:
            return httpx.Response(
                200,
                json=_chat_payload(
                    json.dumps({"category": "Alimentación", "confidence": 0.99}),
                    allowance={"spent": 9.9, "limit": 10, "remaining": 0.1},
                ),
            )
        return httpx.Response(
            200,
            json=_chat_payload(
                json.dumps({"category": "Alimentación", "confidence": 0.98}),
                model=model,
            ),
        )

    client, _ = _client(handler, fallback_models=[FALLBACK])
    try:
        result = client.complete(
            messages=[{"role": "user", "content": "clasifica"}],
            schema=CategoryAnswer,
        )
    finally:
        client.close()

    assert calls == [PRIMARY, FALLBACK]
    assert result.model == FALLBACK
    assert result.fallback_used is True


def test_invalid_json_exhausts_retries() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content)["model"])
        return httpx.Response(200, json=_chat_payload("sigo sin ser JSON"))

    client, _ = _client(handler, max_retries=1)
    try:
        with pytest.raises(OpenCodeResponseError):
            client.chat(
                [{"role": "user", "content": "clasifica"}],
                schema=CategoryAnswer,
            )
    finally:
        client.close()

    assert calls == [PRIMARY, PRIMARY]


def test_env_configuration_and_model_deduplication(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_API_KEY", "oc_sk_env")
    monkeypatch.setenv("OPENCODE_MODEL", FALLBACK)
    monkeypatch.setenv(
        "OPENCODE_FALLBACK_MODELS", f"mimo-v2.6-flash, gpt-6-luna, {FALLBACK}"
    )

    client = OpenCodeGoClient()
    try:
        assert client.api_key == "oc_sk_env"
        assert client.model == FALLBACK
        assert client.fallback_models == ("mimo-v2.6-flash", "gpt-6-luna")
    finally:
        client.close()


def test_empty_fallback_env_disables_fallbacks(monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_FALLBACK_MODELS", "")

    client = OpenCodeGoClient(api_key="oc_sk_test")
    try:
        assert client.fallback_models == ()
    finally:
        client.close()


def test_missing_api_key_raises_before_any_request(monkeypatch) -> None:
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    client = OpenCodeGoClient(
        api_key="",
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(OpenCodeAuthError):
            client.chat([{"role": "user", "content": "hola"}])
    finally:
        client.close()

    assert calls == []


def test_complete_routes_gpt_to_responses() -> None:
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(
            200,
            json=_responses_payload(
                json.dumps({"category": "Ocio", "confidence": 0.99})
            ),
        )

    client, _ = _client(handler)
    try:
        result = client.complete(
            messages=[{"role": "user", "content": "clasifica"}],
            model="gpt-6-luna",
            schema=CategoryAnswer,
        )
    finally:
        client.close()

    assert paths == ["/inference/go/openai/v1/responses"]
    assert result.api == "responses"
    assert result.parsed.category == "Ocio"


def test_api_family_routing() -> None:
    assert api_family_for_model(PRIMARY) == "chat"
    assert api_family_for_model("glm-5.3-flash") == "chat"
    assert api_family_for_model("qwen3.8-flash") == "chat"
    assert api_family_for_model("mimo-v2.6-flash") == "chat"
    assert api_family_for_model("gpt-6-luna") == "responses"
    assert api_family_for_model("claude-haiku-5-5") == "anthropic"
    assert api_family_for_model("gemini-4-argon") == "google"
    assert (
        api_family_for_model("glm-5.3-flash", {"glm-5.3-flash": "responses"})
        == "responses"
    )


def test_parse_json_text_tolerates_markdown_fences() -> None:
    assert parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_text('texto antes {"a": 1} texto después') == {"a": 1}
    with pytest.raises(ValueError):
        parse_json_text("sin JSON")


def test_allowance_infers_remaining_from_used_and_limit() -> None:
    from src.ai.schemas import Allowance

    usage = Allowance.from_payload({"used": 95, "limit": 100})
    assert usage.remaining_usd == Decimal("5")
    assert usage.remaining_ratio == pytest.approx(0.05)
    assert usage.is_low() is True

    fraction = Allowance.from_payload({"remaining": 0.10})
    assert fraction.remaining_pct == pytest.approx(0.10)
    assert fraction.is_low() is True

    no_budget_info = Allowance.from_payload(0.0012)
    assert no_budget_info.spent_usd == Decimal("0.0012")
    assert no_budget_info.is_low() is False
