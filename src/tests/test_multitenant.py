"""TENANT_MODE=per_user con SQLCipher: aislamiento, claves y worker."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.auth import tenancy
from src.auth.passwords import hash_password
from src.auth.service import create_user
from src.config import reset_settings
from src.db.session import NoTenantContext, _session, central_session, reset_engine
from src.db.tenant import TenantContext, TenantUnavailable, tenant_db_path, use_tenant
from src.models import CentralJob, KeyLease, SourceFile, User
from src.models import Session as UserSession

PASSWORD_A = "CorrectHorseBatteryStaple1"
PASSWORD_B = "AnotherVeryLongPassword2"


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("TENANT_MODE", "per_user")
    monkeypatch.setenv("TENANT_ENCRYPTION", "true")
    monkeypatch.setenv("TENANT_DIR", str(tmp_path / "tenants"))
    monkeypatch.setenv("CENTRAL_DATABASE_URL", f"sqlite:///{tmp_path / 'central.db'}")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'unused.db'}")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    monkeypatch.delenv("IMPORT_QUEUE_MODE", raising=False)
    reset_settings()
    reset_engine()
    tenancy.reset_refresh_throttle()

    from src.db.session import init_db

    init_db()
    with central_session() as db:
        create_user(db, email="a@example.com", password_hash=hash_password(PASSWORD_A))
        create_user(db, email="b@example.com", password_hash=hash_password(PASSWORD_B))
    try:
        yield tmp_path
    finally:
        reset_engine()
        reset_settings()


def _client() -> TestClient:
    from src.api import app

    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> tuple[dict, dict]:
    response = client.post("/api/v3/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return {"X-CSRF-Token": body["csrf_token"]}, body


def _account(client: TestClient, headers: dict, nombre: str) -> None:
    created = client.post("/api/v3/accounts", json={"nombre": nombre}, headers=headers)
    assert created.status_code == 201, created.text


def _account_names(client: TestClient) -> set[str]:
    response = client.get("/api/v3/accounts")
    assert response.status_code == 200, response.text
    data = response.json()
    items = data["items"] if isinstance(data, dict) else data
    return {item["nombre"] for item in items}


def test_first_login_creates_keys_and_isolates_users(env):
    a, b = _client(), _client()
    headers_a, body_a = _login(a, "a@example.com", PASSWORD_A)
    headers_b, body_b = _login(b, "b@example.com", PASSWORD_B)
    # La clave de recuperación solo se entrega en el primer login.
    assert len(body_a["recovery_key"].replace("-", "")) == 32
    assert "recovery_key" in body_b
    _, again = _login(_client(), "a@example.com", PASSWORD_A)
    assert "recovery_key" not in again

    _account(a, headers_a, "Cuenta de A")
    _account(b, headers_b, "Cuenta de B")
    assert "Cuenta de A" in _account_names(a)
    assert "Cuenta de B" not in _account_names(a)
    assert "Cuenta de B" in _account_names(b)
    assert "Cuenta de A" not in _account_names(b)

    with central_session() as db:
        users = {u.email: u for u in db.query(User).all()}
        assert users["a@example.com"].tenant_id != users["b@example.com"].tenant_id
        assert users["a@example.com"].dek_wrapped_pw
        tenant_a = users["a@example.com"].tenant_id
        # La sesión guarda la DEK envuelta, nunca en claro.
        rows = db.query(UserSession).filter_by(user_id=users["a@example.com"].id).all()
        assert all(row.dek_wrapped and row.dek_wrapped.startswith("v1.") for row in rows)

    path = tenant_db_path(tenant_a)
    assert path.exists()
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(path).execute("SELECT count(*) FROM accounts").fetchone()
    assert b"Cuenta de A" not in path.read_bytes()


def test_data_access_without_tenant_context_fails(env):
    with pytest.raises(NoTenantContext):
        with _session():
            pass


def test_wrong_key_cannot_open_tenant(env):
    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    _account(a, headers, "Secreta")
    with central_session() as db:
        user = db.query(User).filter_by(email="a@example.com").one()
        tenant_id, user_id = user.tenant_id, user.id
    reset_engine()
    with use_tenant(TenantContext(user_id, tenant_id, b"\x00" * 32)):
        with pytest.raises(TenantUnavailable):
            with _session():
                pass


def test_change_password_rewraps_key_and_keeps_data(env):
    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    _account(a, headers, "Persistente")
    new_password = "BrandNewPasswordForA3"
    response = a.post(
        "/api/v3/auth/change-password",
        json={"current_password": PASSWORD_A, "new_password": new_password},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    reset_engine()  # fuerza reabrir el SQLite con la DEK re-desenvuelta

    fresh = _client()
    bad = fresh.post("/api/v3/auth/login", json={"email": "a@example.com", "password": PASSWORD_A})
    assert bad.status_code == 401
    _login(fresh, "a@example.com", new_password)
    assert "Persistente" in _account_names(fresh)


def test_recovery_key_resets_password_without_losing_data(env):
    a = _client()
    headers, body = _login(a, "a@example.com", PASSWORD_A)
    recovery_key = body["recovery_key"]
    _account(a, headers, "Recuperable")

    anon = _client()
    wrong = anon.post(
        "/api/v3/auth/recover",
        json={
            "email": "a@example.com",
            "recovery_key": "AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA-AAAA",
            "new_password": "RecoveredPassword4567",
        },
    )
    assert wrong.status_code == 401
    ok = anon.post(
        "/api/v3/auth/recover",
        json={
            "email": "a@example.com",
            "recovery_key": recovery_key.lower(),
            "new_password": "RecoveredPassword4567",
        },
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["recovery_key"] != recovery_key
    # Las sesiones anteriores quedan revocadas.
    assert a.get("/api/v3/accounts").status_code == 401

    reset_engine()
    fresh = _client()
    _login(fresh, "a@example.com", "RecoveredPassword4567")
    assert "Recuperable" in _account_names(fresh)


def test_session_rotation_rewraps_key(env):
    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    _account(a, headers, "Rotada")
    with central_session() as db:
        row = db.query(UserSession).filter(UserSession.revoked_at.is_(None)).first()
        old_hash = row.token_hash
        row.created_at = datetime.utcnow() - timedelta(days=2)
    assert "Rotada" in _account_names(a)
    with central_session() as db:
        row = db.query(UserSession).filter(UserSession.revoked_at.is_(None)).first()
        assert row.token_hash != old_hash
    # La cookie nueva sigue desenvolviendo la DEK.
    reset_engine()
    assert "Rotada" in _account_names(a)


def test_invite_lets_user_choose_password(env):
    import secrets

    from src.auth.tokens import hash_session_token

    token = secrets.token_urlsafe(32)
    with central_session() as db:
        db.add(
            User(
                email="c@example.com",
                password_hash="!invited",
                role="user",
                created_at=datetime.utcnow(),
                invite_token_hash=hash_session_token(token),
                invite_expires_at=datetime.utcnow() + timedelta(days=1),
            )
        )
    c = _client()
    response = c.post(
        "/api/v3/auth/accept-invite",
        json={"token": token, "password": "InvitedUserPassword5"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["recovery_key"]
    headers = {"X-CSRF-Token": response.json()["csrf_token"]}
    _account(c, headers, "Cuenta de C")
    again = _client().post(
        "/api/v3/auth/accept-invite",
        json={"token": token, "password": "InvitedUserPassword6"},
    )
    assert again.status_code == 400


def test_worker_processes_import_with_ram_only_lease(env, monkeypatch):
    from src import import_worker

    monkeypatch.setenv("IMPORT_QUEUE_MODE", "worker")
    seen: list[bytes] = []

    def fake_process_import(path, **kwargs):
        seen.append(Path(path).read_bytes())
        with _session() as s:
            sf = s.query(SourceFile).filter_by(id=kwargs["source_file_id"]).one()
            sf.status = "parsed"

    monkeypatch.setattr(import_worker, "process_import", fake_process_import)

    worker = import_worker.WorkerIdentity()
    worker.heartbeat(force=True)

    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    content = b"date,amount\n2026-01-01,-1\n"
    response = a.post(
        "/api/v3/imports",
        files={"files": ("extracto.csv", content, "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    import_id = response.json()["import"]["id"]

    with central_session() as db:
        job = db.query(CentralJob).one()
        assert (job.kind, job.ref_id, job.status) == ("import", import_id, "queued")
        assert db.query(KeyLease).filter_by(worker_key_id=worker.id).count() == 1
        tenant_id = db.query(User).filter_by(email="a@example.com").one().tenant_id

    # El fichero guardado va cifrado en disco.
    stored = list((env / "tenants" / tenant_id / "files").glob("*.csv"))
    assert stored and content not in stored[0].read_bytes()

    reset_engine()  # el worker es otro proceso: no comparte motores abiertos
    assert import_worker.run_central_once(worker) is True
    assert seen == [content]
    with central_session() as db:
        assert db.query(CentralJob).one().status == "done"


def test_worker_restart_waits_for_unlock(env, monkeypatch):
    from src import import_worker

    monkeypatch.setenv("IMPORT_QUEUE_MODE", "worker")
    monkeypatch.setattr(import_worker, "process_import", lambda *a, **k: None)
    old_worker = import_worker.WorkerIdentity()
    old_worker.heartbeat(force=True)

    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    response = a.post(
        "/api/v3/imports",
        files={"files": ("extracto.csv", b"date,amount\n2026-01-02,-2\n", "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text

    # "Reinicio": la privada anterior se pierde y el worker nuevo no tiene concesión.
    new_worker = import_worker.WorkerIdentity()
    new_worker.heartbeat(force=True)
    assert import_worker.run_central_once(new_worker) is True
    with central_session() as db:
        assert db.query(CentralJob).one().status == "waiting_unlock"

    # La siguiente petición del usuario vuelve a sellar la DEK y reencola.
    tenancy.reset_refresh_throttle()
    assert a.get("/api/v3/accounts").status_code == 200
    with central_session() as db:
        assert db.query(CentralJob).one().status == "queued"
        assert db.query(KeyLease).filter_by(worker_key_id=new_worker.id).count() == 1


def test_export_plain_and_encrypted_database(env):
    import sqlcipher3

    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    _account(a, headers, "Exportable")

    bad = a.post(
        "/api/v3/export/database", json={"password": "wrong-password-123"}, headers=headers
    )
    assert bad.status_code == 400

    plain = a.post(
        "/api/v3/export/database",
        json={"password": PASSWORD_A, "format": "sqlite"},
        headers=headers,
    )
    assert plain.status_code == 200, plain.text
    out = env / "plain.db"
    out.write_bytes(plain.content)
    names = [r[0] for r in sqlite3.connect(out).execute("SELECT nombre FROM accounts")]
    assert "Exportable" in names

    enc = a.post(
        "/api/v3/export/database",
        json={"password": PASSWORD_A, "format": "sqlcipher", "passphrase": "my-backup-passphrase"},
        headers=headers,
    )
    assert enc.status_code == 200, enc.text
    out_enc = env / "enc.db"
    out_enc.write_bytes(enc.content)
    with pytest.raises(sqlite3.DatabaseError):
        sqlite3.connect(out_enc).execute("SELECT count(*) FROM accounts").fetchone()
    conn = sqlcipher3.dbapi2.connect(str(out_enc))
    conn.execute("PRAGMA key = 'my-backup-passphrase'")
    assert "Exportable" in [r[0] for r in conn.execute("SELECT nombre FROM accounts")]


def test_admin_invites_user(env):
    with central_session() as db:
        db.query(User).filter_by(email="a@example.com").one().role = "admin"
        db.query(User).filter_by(email="b@example.com").one().role = "user"
    admin = _client()
    headers, _ = _login(admin, "a@example.com", PASSWORD_A)
    invited = admin.post(
        "/api/v3/admin/users", json={"email": "New@Example.com"}, headers=headers
    )
    assert invited.status_code == 201, invited.text
    token = invited.json()["invite_token"]
    assert invited.json()["user"]["invite_pending"] is True

    # Sin aceptar no se puede entrar.
    assert _client().post(
        "/api/v3/auth/login", json={"email": "new@example.com", "password": "!invited"}
    ).status_code == 401

    guest = _client()
    accepted = guest.post(
        "/api/v3/auth/accept-invite", json={"token": token, "password": "GuestPassword12345"}
    )
    assert accepted.status_code == 200, accepted.text

    user_b = _client()
    _login(user_b, "b@example.com", PASSWORD_B)
    assert user_b.get("/api/v3/admin/users").status_code == 403
    listing = admin.get("/api/v3/admin/users").json()["items"]
    assert {u["email"] for u in listing} == {"a@example.com", "b@example.com", "new@example.com"}


def test_scheduled_bot_runs_with_automation_lease(env, monkeypatch):
    from src import import_worker

    monkeypatch.setenv("AGENT_FAKE_LLM", "1")  # modelo determinista sin red
    worker = import_worker.WorkerIdentity()
    worker.heartbeat(force=True)

    a = _client()
    headers, _ = _login(a, "a@example.com", PASSWORD_A)
    bot = a.post(
        "/api/v3/agent/bots",
        json={"name": "Diario", "prompt": "Hazme un resumen", "cron": "0 9 * * *"},
        headers=headers,
    )
    assert bot.status_code == 201, bot.text
    with central_session() as db:
        job = db.query(CentralJob).filter_by(kind="bot_run").one()
        assert job.run_at > datetime.utcnow()
        # Reloj simulado: ya toca.
        job.run_at = datetime.utcnow() - timedelta(seconds=1)

    # Un worker recién reiniciado no tiene concesión para este usuario.
    fresh = import_worker.WorkerIdentity()
    fresh.heartbeat(force=True)
    with central_session() as db:
        db.query(KeyLease).delete()
    assert import_worker.run_central_once(fresh) is True
    with central_session() as db:
        assert db.query(CentralJob).filter_by(kind="bot_run").one().status == "waiting_unlock"

    # Opt-in de automatizaciones: concesión sellada para los workers vivos.
    enabled = a.put(
        "/api/v3/auth/automation",
        json={"enabled": True, "password": PASSWORD_A, "days": 7},
        headers=headers,
    )
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["workers"] == 2
    tenancy.reset_refresh_throttle()
    assert a.get("/api/v3/accounts").status_code == 200  # reencola waiting_unlock

    reset_engine()  # el worker es otro proceso
    assert import_worker.run_central_once(fresh) is True
    with central_session() as db:
        jobs = db.query(CentralJob).filter_by(kind="bot_run").order_by(CentralJob.id).all()
        assert [j.status for j in jobs] == ["done", "queued"]
        assert jobs[1].run_at > datetime.utcnow()

    threads = a.get("/api/v3/agent/threads?origin=routine").json()["items"]
    assert len(threads) == 1
    notes = a.get("/api/v3/agent/notifications").json()
    assert notes["items"][0]["kind"] == "bot_completed"
    detail = a.get(f"/api/v3/agent/threads/{threads[0]['id']}").json()
    assert any(p.get("name") == "get_overview" for m in detail["messages"] for p in m["parts"])

    # Desactivar revoca la concesión de automatización.
    off = a.put(
        "/api/v3/auth/automation",
        json={"enabled": False, "password": PASSWORD_A},
        headers=headers,
    )
    assert off.status_code == 200
    with central_session() as db:
        assert db.query(KeyLease).filter_by(purpose="automation").count() == 0
