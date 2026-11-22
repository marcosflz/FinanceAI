# ruff: noqa: F811  (``client`` es un fixture importado de test_agent)
"""Skills: creador asistido, publicación, uso en el chat y en bots (sin red)."""

from __future__ import annotations

from src.tests.test_agent import (  # noqa: F401  (``client`` es un fixture)
    _events,
    _login,
    _script,
    _thread,
    call,
    client,
    says,
)

SKILL_MD = """---
name: resumen-mensual
description: Úsala cuando el usuario pida un resumen mensual de gastos por categoría.
---

1. Llama a spending_by_category con el mes pedido.
2. Responde con una tabla y el total en formato 1.234,56 €.
"""


def _create_with_creator(client, headers, monkeypatch, content: str = SKILL_MD) -> int:
    _script(
        monkeypatch,
        call("w1", "write_draft_file", path="SKILL.md", content=content),
        call("v1", "validate_draft"),
        says("He creado la skill; pruébala con un mes concreto."),
    )
    draft_id = client.post("/api/v3/agent/skill-drafts", json={}, headers=headers).json()["id"]
    events = _events(
        client.post(
            f"/api/v3/agent/skill-drafts/{draft_id}/messages",
            json={"message": "Quiero una skill de resumen mensual"},
            headers=headers,
        )
    )
    assert events[-1]["type"] == "RUN_FINISHED", events[-1]
    validated = [e for e in events if e["type"] == "TOOL_CALL_RESULT" and e["name"] == "validate_draft"]
    assert validated and validated[0]["result"]["ok"] is True
    return draft_id


def test_creator_writes_draft_and_publishes(client, monkeypatch):
    headers = _login(client)
    draft_id = _create_with_creator(client, headers, monkeypatch)

    detail = client.get(f"/api/v3/agent/skill-drafts/{draft_id}").json()
    assert detail["files"]["SKILL.md"] == SKILL_MD
    assert detail["validation"]["name"] == "resumen-mensual"
    assert detail["revision"] == 1
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    # La conversación del creador no aparece en el chat normal.
    threads = client.get("/api/v3/agent/threads").json()["items"]
    assert all(t["origin"] != "skill_creator" for t in threads)

    published = client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    again = client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    assert again.status_code == 409  # sin cambios

    skills = client.get("/api/v3/agent/skills").json()["items"]
    assert [(s["name"], s["version"], s["enabled_in_chat"]) for s in skills] == [
        ("resumen-mensual", 1, True)
    ]


def test_manual_edit_uses_revision_and_new_version(client, monkeypatch):
    headers = _login(client)
    draft_id = _create_with_creator(client, headers, monkeypatch)
    client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    stale = client.patch(
        f"/api/v3/agent/skill-drafts/{draft_id}",
        json={"revision": 0, "files": {"SKILL.md": SKILL_MD + "\n3. Añade un gráfico.\n"}},
        headers=headers,
    )
    assert stale.status_code == 409
    saved = client.patch(
        f"/api/v3/agent/skill-drafts/{draft_id}",
        json={"revision": 1, "files": {"SKILL.md": SKILL_MD + "\n3. Añade un gráfico.\n"}},
        headers=headers,
    )
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    published = client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    assert published.json()["version"] == 2

    # Un segundo borrador con el mismo nombre no puede publicarse.
    other = _create_with_creator(client, headers, monkeypatch)
    clash = client.post(f"/api/v3/agent/skill-drafts/{other}/publish", headers=headers)
    assert clash.status_code == 409


def test_invalid_draft_cannot_be_published(client, monkeypatch):
    headers = _login(client)
    draft_id = client.post("/api/v3/agent/skill-drafts", json={}, headers=headers).json()["id"]
    client.patch(
        f"/api/v3/agent/skill-drafts/{draft_id}",
        json={"revision": 0, "files": {"SKILL.md": "---\nname: Mal Nombre\ndescription: x\n---\nhola"}},
        headers=headers,
    )
    response = client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    assert response.status_code == 422


def test_chat_injects_catalog_and_explicit_skill(client, monkeypatch):
    headers = _login(client)
    draft_id = _create_with_creator(client, headers, monkeypatch)
    client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)

    llm = _script(monkeypatch, says("Resumen de octubre: 22,49 €."))
    thread_id = _thread(client, headers)
    events = _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages",
            json={"message": "/resumen-mensual octubre"},
            headers=headers,
        )
    )
    names = {m.get("name") for m in llm.seen[0]}
    assert {"nas_skills_catalog", "nas_skills_active"} <= names
    active = next(m for m in llm.seen[0] if m.get("name") == "nas_skills_active")
    assert "spending_by_category" in active["content"]
    skill_events = [e for e in events if e["type"] == "SKILL_ACTIVATED"]
    assert [e["name"] for e in skill_events] == ["resumen-mensual"]

    # Desactivada en el chat → el catálogo desaparece en el siguiente turno.
    skill_id = client.get("/api/v3/agent/skills").json()["items"][0]["id"]
    client.patch(f"/api/v3/agent/skills/{skill_id}", json={"enabled_in_chat": False}, headers=headers)
    llm = _script(monkeypatch, says("Vale."))
    _events(
        client.post(
            f"/api/v3/agent/threads/{thread_id}/messages", json={"message": "gracias"}, headers=headers
        )
    )
    assert "nas_skills_catalog" not in {m.get("name") for m in llm.seen[0]}


def test_bot_skills_and_zip_roundtrip(client, monkeypatch):
    headers = _login(client)
    draft_id = _create_with_creator(client, headers, monkeypatch)
    client.post(f"/api/v3/agent/skill-drafts/{draft_id}/publish", headers=headers)
    skill_id = client.get("/api/v3/agent/skills").json()["items"][0]["id"]
    client.patch(f"/api/v3/agent/skills/{skill_id}", json={"enabled_in_chat": False}, headers=headers)

    bot = client.post(
        "/api/v3/agent/bots",
        json={"name": "Resumen", "prompt": "Haz el resumen", "cron": "0 8 1 * *", "skill_ids": [skill_id]},
        headers=headers,
    )
    assert bot.status_code == 201, bot.text
    assert bot.json()["skill_ids"] == [skill_id]
    llm = _script(monkeypatch, says("Hecho."))
    result = client.post(f"/api/v3/agent/bots/{bot.json()['id']}/run", headers=headers).json()
    assert result["status"] == "completed", result
    # El bot ve su skill aunque no esté activa en el chat.
    assert "nas_skills_catalog" in {m.get("name") for m in llm.seen[0]}

    exported = client.get(f"/api/v3/agent/skills/{skill_id}/export")
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "application/zip"
    imported = client.post(
        "/api/v3/agent/skills/import",
        files={"file": ("s.zip", exported.content, "application/zip")},
        headers=headers,
    )
    assert imported.status_code == 201, imported.text
    item = imported.json()["items"][0]
    assert item["name"] == "resumen-mensual"
    detail = client.get(f"/api/v3/agent/skill-drafts/{item['draft_id']}").json()
    assert detail["files"]["SKILL.md"] == SKILL_MD

    client.delete(f"/api/v3/agent/skills/{skill_id}", headers=headers)
    bots = client.get("/api/v3/agent/bots").json()["items"]
    assert bots[0]["skill_ids"] == []
