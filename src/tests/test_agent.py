"""Asistente de IA: herramientas, aprobaciones, reanudación y bots (sin red)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from nas.adk.models.base_llm import BaseLlm, LlmRequest, LlmResponse, ToolCall

from src.agent import runtime
from src.auth.passwords import hash_password
from src.auth.service import create_user
from src.config import reset_settings
from src.db.session import get_engine, reset_engine, session_scope
from src.models import (
    Account,
    AgentApproval,
    AgentAudit,
    AiProvider,
    Base,
    Categoria,
    CentralBase,
    Classification,
    FinancialMovement,
    NormalizedEvent,
    RawRow,
    SourceFile,
)

PASSWORD = "CorrectHorseBatteryStaple1"


class ScriptedLlm(BaseLlm):
    model: str = "scripted"
    script: list[LlmResponse]
    seen: list[list[dict[str, Any]]] = []

    async def generate_content_async(self, request: LlmRequest) -> LlmResponse:
        self.seen.append(list(request.messages))
        return self.script.pop(0)


def call(call_id: str, name: str, **args: Any) -> LlmResponse:
    return LlmResponse(
        tool_calls=[ToolCall(id=call_id, function={"name": name, "arguments": json.dumps(args)})],
        finish_reason="tool_calls",
    )


def says(text: str) -> LlmResponse:
    return LlmResponse(content=text, usage={"input_tokens": 3, "output_tokens": 2})


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.delenv("TENANT_MODE", raising=False)
    monkeypatch.delenv("AGENT_FAKE_LLM", raising=False)
    reset_settings()
    reset_engine()
    Base.metadata.create_all(get_engine())
    CentralBase.metadata.create_all(get_engine())
    with session_scope() as s:
        create_user(s, email="admin@example.com", password_hash=hash_password(PASSWORD))
        account = Account(nombre="Cuenta", tipo="efectivo_externa", es_propia=True)
        s.add(account)
        food = Categoria(nombre="Alimentación")
        fun = Categoria(nombre="Ocio")
        s.add_all([food, fun])
        s.flush()
        sf = SourceFile(source="t", filename="t.csv", file_hash="a" * 64, parser_version="t")
        s.add(sf)
        s.flush()
        for i, (merchant, amount) in enumerate([("CINE YELMO", "-9.50"), ("NETFLIX", "-12.99")]):
            rr = RawRow(source_file_id=sf.id, row_index=i, payload="{}", row_hash=f"{i:064d}")
            s.add(rr)
            s.flush()
            ev = NormalizedEvent(
                raw_row_id=rr.id,
                broker_type="CASH_CARD_TRANSACTION",
                kind="gasto",
                value_date=date(2026, 10, 1 + i),
                amount=Decimal(amount),
                currency="EUR",
                fingerprint=f"{i:064x}",
                description_clean=merchant,
            )
            s.add(ev)
            s.flush()
            mv = FinancialMovement(
                event_id=ev.id,
                account_id=account.id,
                kind="gasto",
                direction="-",
                amount=Decimal(amount),
                amount_eur=Decimal(amount),
                currency="EUR",
                value_date=date(2026, 10, 1 + i),
                estado="pendiente",
                merchant=merchant,
            )
            s.add(mv)
            s.flush()
            s.add(Classification(movement_id=mv.id, categoria_id=food.id, origen="rule", vigente=True))

    from src.api import app

    try:
        yield TestClient(app)
    finally:
        reset_engine()
        reset_settings()


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v3/auth/login", json={"email": "admin@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": response.json()["csrf_token"]}


def _script(monkeypatch, *responses: LlmResponse) -> ScriptedLlm:
    llm = ScriptedLlm(script=list(responses), seen=[])
    monkeypatch.setattr(runtime, "build_model", lambda *_a, **_k: llm)
    monkeypatch.setenv("AGENT_FAKE_LLM", "1")  # sin proveedor configurado
    return llm


def _events(response) -> list[dict]:
    assert response.status_code == 200, response.text
    events = []
    for block in response.text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
    return events


def _thread(client, headers) -> int:
    created = client.post("/api/v3/agent/threads", json={}, headers=headers)
    assert created.status_code == 201, created.text
    return created.json()["id"]


def _category_of(movement_id: int) -> str:
    with session_scope() as s:
        cl = (
            s.query(Classification)
            .filter_by(movement_id=movement_id, vigente=True)
            .order_by(Classification.id.desc())
            .first()
        )
        return cl.categoria.nombre


def _movement_ids() -> list[int]:
    with session_scope() as s:
        return [m.id for m in s.query(FinancialMovement).order_by(FinancialMovement.id)]


def test_provider_keys_are_never_returned(client):
    headers = _login(client)
    saved = client.put(
        "/api/v3/ai/providers/openrouter",
        json={"api_key": "sk-or-v1-supersecretvalue1234", "model": "openai/gpt-6.1-sol"},
        headers=headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["key_hint"] == "…1234"
    assert saved.json()["is_default"] is True
    listing = client.get("/api/v3/ai/providers").text
    assert "supersecret" not in listing
    missing = client.put("/api/v3/ai/providers/anthropic", json={"model": "x"}, headers=headers)
    assert missing.status_code == 422


def test_chat_without_provider_is_rejected(client):
    headers = _login(client)
    thread_id = _thread(client, headers)
    response = client.post(
        f"/api/v3/agent/threads/{thread_id}/messages", json={"message": "hola"}, headers=headers
    )
    assert response.status_code == 409
    assert "proveedor" in response.json()["detail"].lower()


def test_read_tool_runs_without_approval(client, monkeypatch):
    headers = _login(client)
    llm = _script(monkeypatch, call("c1", "get_overview"), says("Has gastado 22,49 €."))
    thread_id = _thread(client, headers)
    events = _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages",
            json={"message": "¿Cuánto he gastado?"},
            headers=headers,
        )
    )
    types = [e["type"] for e in events]
    assert types[0] == "RUN_STARTED" and types[-1] == "RUN_FINISHED"
    result = next(e for e in events if e["type"] == "TOOL_CALL_RESULT")
    assert result["name"] == "get_overview" and "error" not in result["result"]
    assert "".join(e["delta"] for e in events if e["type"] == "TEXT_DELTA") == "Has gastado 22,49 €."
    # La herramienta vio los datos del usuario y el modelo recibió el resultado.
    assert llm.seen[-1][-1]["role"] == "tool"

    detail = client.get(f"/api/v3/agent/threads/{thread_id}").json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["thread"]["title"] == "¿Cuánto he gastado?"
    assert detail["thread"]["status"] == "idle"
    # Reproducción desde BD.
    replay = _events(client.get(f"/api/v3/agent/runs/{events[0]['run_id']}/events?after=1"))
    assert [e["seq"] for e in replay] == [e["seq"] for e in events[1:]]


def test_write_tool_waits_for_approval_then_applies(client, monkeypatch):
    headers = _login(client)
    first, _second = _movement_ids()
    _script(
        monkeypatch,
        call("c1", "recategorize_movements", changes=[{"movement_id": first, "category": "Ocio"}]),
        says("Listo, movido a Ocio."),
    )
    thread_id = _thread(client, headers)
    events = _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages",
            json={"message": "El cine es ocio"},
            headers=headers,
        )
    )
    approval = next(e for e in events if e["type"] == "APPROVAL_REQUIRED")["approvals"][0]
    assert approval["tool"] == "recategorize_movements"
    row = approval["preview"]["rows"][0]
    assert (row["id"], row["category"], row["new_category"]) == (first, "Alimentación", "Ocio")
    assert events[-1] == {**events[-1], "type": "RUN_FINISHED", "status": "interrupted"}
    # Nada cambia hasta aprobar, pero la auditoría ya está escrita.
    assert _category_of(first) == "Alimentación"
    with session_scope() as s:
        assert [a.decision for a in s.query(AgentAudit)] == ["ask"]
    # No se puede escribir otro mensaje con aprobaciones pendientes.
    blocked = client.post(
        f"/api/v3/agent/threads/{thread_id}/messages", json={"message": "otra"}, headers=headers
    )
    assert blocked.status_code == 409

    resumed = _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/resume",
            json={"decisions": [{"call_id": "c1", "approved": True}]},
            headers=headers,
        )
    )
    assert resumed[-1]["type"] == "RUN_FINISHED" and resumed[-1]["status"] == "completed"
    assert _category_of(first) == "Ocio"
    with session_scope() as s:
        assert [a.decision for a in s.query(AgentAudit).order_by(AgentAudit.id)] == [
            "ask",
            "approved",
            "executed",
        ]
        assert s.query(AgentApproval).one().status == "approved"


def test_denied_write_does_not_touch_data(client, monkeypatch):
    headers = _login(client)
    first, _ = _movement_ids()
    llm = _script(
        monkeypatch,
        call("c1", "update_movement_fields", movement_id=first, estado="aprobado"),
        says("Entendido, no lo apruebo."),
    )
    thread_id = _thread(client, headers)
    _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages",
            json={"message": "aprueba el cine"},
            headers=headers,
        )
    )
    _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/resume",
            json={"decisions": [{"call_id": "c1", "approved": False, "reason": "todavía no"}]},
            headers=headers,
        )
    )
    with session_scope() as s:
        assert s.query(FinancialMovement).filter_by(id=first).one().estado == "pendiente"
    tool_message = llm.seen[-1][-1]
    assert tool_message["role"] == "tool" and "todavía no" in tool_message["content"]


def test_partial_batch_approval_applies_only_selected(client, monkeypatch):
    headers = _login(client)
    first, second = _movement_ids()
    _script(
        monkeypatch,
        call(
            "c1",
            "recategorize_movements",
            changes=[
                {"movement_id": first, "category": "Ocio"},
                {"movement_id": second, "category": "Ocio"},
            ],
        ),
        says("He movido solo el cine."),
    )
    thread_id = _thread(client, headers)
    _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages",
            json={"message": "ordena el ocio"},
            headers=headers,
        )
    )
    # Simula un reinicio entre la propuesta y la aprobación: el siguiente turno
    # reconstruye el runner desde la sesión guardada.
    reset_engine()
    resumed = _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/resume",
            json={"decisions": [{"call_id": "c1", "approved": True, "selected_ids": [first]}]},
            headers=headers,
        )
    )
    assert resumed[-1]["status"] == "completed"
    result = next(e for e in resumed if e["type"] == "TOOL_CALL_RESULT")["result"]
    assert result["applied"] == [first] and result["skipped"] == [second]
    assert _category_of(first) == "Ocio"
    assert _category_of(second) == "Alimentación"


def test_unknown_tool_is_denied():
    from src.agent.policy import decide

    assert decide("get_overview") == "allow"
    assert decide("recategorize_movements") == "ask"
    assert decide("drop_database") == "deny"


def test_bot_templates_and_cron_validation(client):
    headers = _login(client)
    templates = client.get("/api/v3/agent/bots/templates").json()["items"]
    assert {t["id"] for t in templates} >= {"cashflow_weekly", "pending_review", "portfolio_daily"}
    too_often = client.post(
        "/api/v3/agent/bots",
        json={"name": "x", "prompt": "y", "cron": "*/5 * * * *"},
        headers=headers,
    )
    assert too_often.status_code == 422
    created = client.post(
        "/api/v3/agent/bots",
        json={"name": "Semanal", "prompt": "Resume", "cron": "0 8 * * 1"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    next_run = datetime.fromisoformat(created.json()["next_run_at"])
    assert datetime.utcnow() < next_run < datetime.utcnow() + timedelta(days=8)


def test_run_bot_now_creates_routine_thread_and_notification(client, monkeypatch):
    headers = _login(client)
    _script(monkeypatch, call("c1", "cashflow", months=1), says("Semana tranquila."))
    bot = client.post(
        "/api/v3/agent/bots",
        json={"name": "Semanal", "prompt": "Resume la semana", "cron": "0 8 * * 1"},
        headers=headers,
    ).json()
    result = client.post(f"/api/v3/agent/bots/{bot['id']}/run", headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    threads = client.get("/api/v3/agent/threads?origin=routine").json()["items"]
    assert threads and threads[0]["bot_id"] == bot["id"]
    notes = client.get("/api/v3/agent/notifications").json()
    assert notes["unread"] == 1 and notes["items"][0]["kind"] == "bot_completed"
    client.post("/api/v3/agent/notifications/read", json=None, headers=headers)
    assert client.get("/api/v3/agent/notifications").json()["unread"] == 0


def test_provider_row_is_used_for_credentials(client, monkeypatch):
    headers = _login(client)
    client.put(
        "/api/v3/ai/providers/deepseek",
        json={"api_key": "sk-deepseek-123456789", "model": "deepseek-chat"},
        headers=headers,
    )
    seen: dict[str, Any] = {}

    def fake_build(provider_id, api_key, model):
        seen.update(provider=provider_id, key=api_key, model=model)
        return ScriptedLlm(script=[says("ok")], seen=[])

    monkeypatch.setattr(runtime, "build_model", fake_build)
    thread_id = _thread(client, headers)
    _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages", json={"message": "hola"}, headers=headers
        )
    )
    assert seen == {"provider": "deepseek", "key": "sk-deepseek-123456789", "model": "deepseek-chat"}
    with session_scope() as s:
        assert s.query(AiProvider).one().provider == "deepseek"


def test_claude_subscription_uses_per_user_config_dir(client, monkeypatch):
    from src.agent import providers
    from src.db.tenant import TenantContext, use_tenant

    monkeypatch.delenv("AGENT_FAKE_LLM", raising=False)
    with use_tenant(TenantContext(user_id=7, tenant_id="single")):
        llm = providers.build_model("claude-code", "sk-ant-oat01-token", "default")
    assert type(llm).__name__ == "ClaudeCodeLlm"
    assert llm.oauth_token.get_secret_value() == "sk-ant-oat01-token"
    assert llm.model == "" and llm.env_policy == "scrub"
    extra = llm.transport.spawn.__func__.__closure__  # entorno propio inyectado
    assert extra is not None
    home = providers.claude_config_dir("u7")
    assert home.exists() and home.name == "u7"


def test_subscription_link_flow_stores_token_per_user(client, monkeypatch):
    from src.agent import links

    headers = _login(client)

    async def fake_start(owner):
        assert owner.endswith(":1")
        return "link-123456789", "https://claude.ai/oauth/authorize?x=1"

    async def fake_finish(link_id, owner, code):
        assert (link_id, code) == ("link-123456789", "CODE-42")
        return "sk-ant-oat01-secret-token"

    monkeypatch.setattr(links, "start_claude", fake_start)
    monkeypatch.setattr(links, "finish_claude", fake_finish)
    started = client.post("/api/v3/ai/providers/claude-code/link/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["url"].startswith("https://claude.ai/")
    done = client.post(
        "/api/v3/ai/providers/claude-code/link/finish",
        json={"link_id": "link-123456789", "code": "CODE-42"},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    assert done.json()["key_hint"] == "Claude vinculado" and done.json()["is_default"] is True
    assert "secret-token" not in client.get("/api/v3/ai/providers").text
    with session_scope() as s:
        assert s.query(AiProvider).filter_by(provider="claude-code").one().api_key == (
            "sk-ant-oat01-secret-token"
        )
    # ChatGPT no admite pegar credenciales a mano; las API keys no se vinculan.
    raw = client.put("/api/v3/ai/providers/chatgpt", json={"api_key": "x"}, headers=headers)
    assert raw.status_code == 400
    assert client.post("/api/v3/ai/providers/openai/link/start", headers=headers).status_code == 400


def test_chatgpt_token_is_refreshed_and_persisted(client, monkeypatch):
    import time as _time

    from nas.adk.models.chatgpt import oauth

    from src.agent import providers

    headers = _login(client)
    old = oauth.ChatGptCredentials(
        client_id="cid", access_token="old-access", refresh_token="old-refresh",
        expires_at=_time.time() + 10, account="me@example.com",
    )
    with session_scope() as s:
        s.add(AiProvider(provider="chatgpt", api_key=old.to_json(), model="gpt-6.1-sol",
                         enabled=True, is_default=True, created_at=datetime.utcnow()))

    async def fake_refresh(creds, **_):
        assert creds.refresh_token == "old-refresh"
        return oauth.ChatGptCredentials(
            client_id="cid", access_token="new-access", refresh_token="new-refresh",
            expires_at=_time.time() + 3600, account="me@example.com",
        )

    monkeypatch.setattr(oauth, "refresh", fake_refresh)
    seen = {}

    def fake_build(provider_id, api_key, model):
        seen["access"] = oauth.ChatGptCredentials.from_json(api_key).access_token
        return ScriptedLlm(script=[says("ok")], seen=[])

    monkeypatch.setattr(runtime, "build_model", fake_build)
    assert providers.key_hint(old.to_json(), "chatgpt") == "me@example.com"
    thread_id = _thread(client, headers)
    _events(client.post(f"/api/v3/agent/threads/{thread_id}/messages",
                        json={"message": "hola"}, headers=headers))
    assert seen["access"] == "new-access"
    with session_scope() as s:
        stored = oauth.ChatGptCredentials.from_json(
            s.query(AiProvider).filter_by(provider="chatgpt").one().api_key
        )
    assert stored.refresh_token == "new-refresh"
