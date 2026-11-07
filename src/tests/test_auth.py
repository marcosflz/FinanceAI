"""Tests de autenticación: Argon2id, sesiones, cookies, CSRF y rate limit."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from src.api_v3 import health_router, protected_router, public_router
from src.auth.cookies import set_session_cookie
from src.auth.passwords import hash_password, validate_password_strength, verify_password
from src.auth.service import (
    create_session,
    create_user,
    get_valid_session,
    touch_session,
)
from src.auth.tokens import (
    generate_csrf_token,
    generate_session_token,
    hash_session_token,
    verify_csrf_token,
)
from src.config import Settings, reset_settings
from src.db.session import get_engine, reset_engine, session_scope
from src.models import Base, LoginAttempt, Session as UserSession, User

ADMIN_PASSWORD = "CorrectHorseBatteryStaple1"
NEW_PASSWORD = "AnotherVeryLongPassword2"


@pytest.fixture()
def app_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """SQLite temporal aislada; no toca financial.db ni APIs externas."""
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("SESSION_TTL_DAYS", "7")
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.delenv("OPENCODE_API_KEY", raising=False)

    reset_settings()
    reset_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)
    try:
        yield db_path
    finally:
        reset_engine()
        reset_settings()


@pytest.fixture()
def client(app_env) -> TestClient:
    app = FastAPI()
    app.include_router(public_router)
    app.include_router(protected_router)
    app.include_router(health_router)
    return TestClient(app)


@pytest.fixture()
def admin(app_env):
    with session_scope() as session:
        user = create_user(
            session,
            email="admin@example.com",
            password_hash=hash_password(ADMIN_PASSWORD),
        )
        session.flush()
        user_id = user.id
    return {"email": "admin@example.com", "password": ADMIN_PASSWORD, "id": user_id}


def _login(client: TestClient, password: str = ADMIN_PASSWORD, email: str = "admin@example.com"):
    return client.post(
        "/api/v3/auth/login", json={"email": email, "password": password}
    )


def _csrf_headers(client: TestClient) -> dict[str, str]:
    token = client.cookies.get("ft_csrf")
    assert token
    return {"X-CSRF-Token": token}


def _set_cookies(response) -> list[str]:
    return response.headers.get_list("set-cookie")


class TestPasswords:
    def test_hash_is_argon2id_and_verifies(self):
        password_hash = hash_password(ADMIN_PASSWORD)
        assert password_hash.startswith("$argon2id$")
        assert ADMIN_PASSWORD not in password_hash
        assert verify_password(password_hash, ADMIN_PASSWORD)
        assert not verify_password(password_hash, "incorrecta")

    def test_rejects_short_password(self):
        with pytest.raises(ValueError):
            validate_password_strength("corta")

    def test_invalid_hash_is_false(self):
        assert not verify_password("no-es-un-hash", ADMIN_PASSWORD)


class TestTokens:
    def test_session_token_is_opaque_and_hashed(self):
        token = generate_session_token()
        assert len(token) >= 32
        digest = hash_session_token(token)
        assert digest != token
        assert len(digest) == 64
        assert digest == hashlib.sha256(token.encode()).hexdigest()

    def test_csrf_signature(self):
        secret = "secreto-de-test"
        token = generate_csrf_token(secret)
        assert verify_csrf_token(secret, token)
        assert not verify_csrf_token(secret, token + "x")
        assert not verify_csrf_token("otro-secreto", token)
        assert not verify_csrf_token(secret, None)


class TestSessionLifecycle:
    def test_expired_session_is_invalid(self, app_env, admin):
        with session_scope() as session:
            user = session.query(User).filter_by(email=admin["email"]).one()
            token, _ = create_session(
                session,
                user=user,
                ttl_days=7,
                now=datetime.utcnow() - timedelta(days=8),
            )
        with session_scope() as session:
            assert get_valid_session(session, token) is None

    def test_touch_rotates_token_after_24h(self, app_env, admin):
        with session_scope() as session:
            user = session.query(User).filter_by(email=admin["email"]).one()
            token, row = create_session(
                session,
                user=user,
                ttl_days=7,
                now=datetime.utcnow() - timedelta(hours=25),
            )
            old_hash = row.token_hash
            new_token = touch_session(session, row, ttl_days=7)
            assert new_token is not None and new_token != token
            assert row.token_hash == hash_session_token(new_token)
            assert row.token_hash != old_hash

        with session_scope() as session:
            assert get_valid_session(session, token) is None
            assert get_valid_session(session, new_token) is not None


class TestLogin:
    def test_protected_route_requires_session(self, client):
        assert client.get("/api/v3/auth/me").status_code == 401
        assert client.get("/api/v3/health").status_code == 200
        assert client.get("/healthz").status_code == 200

    def test_login_sets_cookies_and_session(self, client, admin):
        response = _login(client)
        assert response.status_code == 200, response.text
        cookies = "\n".join(_set_cookies(response)).lower()
        assert "ft_session=" in cookies
        assert "ft_csrf=" in cookies
        assert "httponly" in cookies
        assert "samesite=lax" in cookies
        assert "path=/" in cookies
        assert "domain=" not in cookies
        assert "secure" not in cookies  # ENV=test

        token = client.cookies.get("ft_session")
        assert token
        with session_scope() as session:
            row = session.query(UserSession).one()
            assert row.token_hash == hash_session_token(token)
            assert row.token_hash != token
            assert row.revoked_at is None

        me = client.get("/api/v3/auth/me")
        assert me.status_code == 200
        assert me.json()["email"] == admin["email"]
        assert me.json()["remaining_seconds"] > 0

    def test_wrong_password_and_unknown_user_are_generic(self, client, admin):
        wrong = _login(client, password="incorrecta")
        unknown = _login(client, email="nadie@example.com", password="incorrecta")
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"] == "Credenciales inválidas"
        with session_scope() as session:
            attempts = session.query(LoginAttempt).all()
            assert len(attempts) == 2
            assert all(attempt.ok is False for attempt in attempts)

    def test_rate_limit_after_five_failures(self, client, admin):
        for _ in range(5):
            assert _login(client, password="incorrecta").status_code == 401
        blocked = _login(client)
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"].isdigit()
        # Incluso con la contraseña correcta sigue bloqueado hasta la ventana.
        assert _login(client).status_code == 429


class TestCsrfAndLogout:
    def test_logout_requires_csrf(self, client, admin):
        assert _login(client).status_code == 200
        without_csrf = client.post("/api/v3/auth/logout")
        assert without_csrf.status_code == 403

        wrong = client.post(
            "/api/v3/auth/logout", headers={"X-CSRF-Token": "token-falso"}
        )
        assert wrong.status_code == 403

        ok = client.post("/api/v3/auth/logout", headers=_csrf_headers(client))
        assert ok.status_code == 204
        assert client.get("/api/v3/auth/me").status_code == 401
        with session_scope() as session:
            row = session.query(UserSession).one()
            assert row.revoked_at is not None

    def test_logout_all_revokes_every_session(self, client, admin):
        assert _login(client).status_code == 200
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)
        assert client.post("/api/v3/auth/logout-all", headers=headers).status_code == 204
        assert client.get("/api/v3/auth/me").status_code == 401
        with session_scope() as session:
            rows = session.query(UserSession).all()
            assert len(rows) == 2
            assert all(row.revoked_at is not None for row in rows)


class TestChangePassword:
    def test_change_password_revokes_old_token_and_rotates(self, client, admin):
        assert _login(client).status_code == 200
        old_token = client.cookies.get("ft_session")
        headers = _csrf_headers(client)

        response = client.post(
            "/api/v3/auth/change-password",
            json={
                "current_password": ADMIN_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
            headers=headers,
        )
        assert response.status_code == 200, response.text
        new_token = client.cookies.get("ft_session")
        assert new_token and new_token != old_token

        # El token anterior deja de valer inmediatamente.
        client.cookies.clear()
        client.cookies.set("ft_session", old_token)
        assert client.get("/api/v3/auth/me").status_code == 401

        client.cookies.clear()
        assert _login(client, password=ADMIN_PASSWORD).status_code == 401
        assert _login(client, password=NEW_PASSWORD).status_code == 200

    def test_change_password_validates_current_and_length(self, client, admin):
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)
        wrong_current = client.post(
            "/api/v3/auth/change-password",
            json={"current_password": "incorrecta", "new_password": NEW_PASSWORD},
            headers=headers,
        )
        assert wrong_current.status_code == 400
        short = client.post(
            "/api/v3/auth/change-password",
            json={"current_password": ADMIN_PASSWORD, "new_password": "corta"},
            headers=headers,
        )
        assert short.status_code == 422


class TestProfile:
    def test_update_name_and_get_me(self, client, admin):
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)

        response = client.patch(
            "/api/v3/auth/profile",
            json={"name": "  Marcos Florez  "},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Marcos Florez"
        assert response.json()["email"] == admin["email"]

        me = client.get("/api/v3/auth/me")
        assert me.status_code == 200
        assert me.json()["name"] == "Marcos Florez"

        with session_scope() as session:
            assert session.get(User, admin["id"]).name == "Marcos Florez"

    def test_profile_requires_csrf(self, client, admin):
        assert _login(client).status_code == 200
        assert (
            client.patch("/api/v3/auth/profile", json={"name": "Sin CSRF"}).status_code
            == 403
        )

    def test_profile_requires_session(self, client):
        assert (
            client.patch("/api/v3/auth/profile", json={"name": "Sin sesión"}).status_code
            == 401
        )

    def test_invalid_email_is_rejected(self, client, admin):
        assert _login(client).status_code == 200
        response = client.patch(
            "/api/v3/auth/profile",
            json={"email": "no-es-un-email"},
            headers=_csrf_headers(client),
        )
        assert response.status_code == 422

    def test_clear_name_falls_back_to_email_local_part(self, client, admin):
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)
        assert (
            client.patch(
                "/api/v3/auth/profile", json={"name": "Nombre temporal"}, headers=headers
            ).status_code
            == 200
        )
        cleared = client.patch(
            "/api/v3/auth/profile", json={"name": None}, headers=headers
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["name"] == "admin"
        with session_scope() as session:
            assert session.get(User, admin["id"]).name is None

    def test_email_change_requires_current_password(self, client, admin):
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)

        missing = client.patch(
            "/api/v3/auth/profile",
            json={"email": "nuevo@example.com"},
            headers=headers,
        )
        assert missing.status_code == 400
        assert "contraseña actual" in missing.json()["detail"]

        wrong = client.patch(
            "/api/v3/auth/profile",
            json={
                "email": "nuevo@example.com",
                "current_password": "incorrecta",
            },
            headers=headers,
        )
        assert wrong.status_code == 400

    def test_email_change_updates_login_identity(self, client, admin):
        assert _login(client).status_code == 200
        headers = _csrf_headers(client)
        new_email = "marcos@example.com"

        response = client.patch(
            "/api/v3/auth/profile",
            json={"email": new_email, "current_password": ADMIN_PASSWORD},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        assert response.json()["email"] == new_email

        client.cookies.clear()
        assert _login(client, email=admin["email"]).status_code == 401
        assert _login(client, email=new_email).status_code == 200

        with session_scope() as session:
            assert session.get(User, admin["id"]).email == new_email

    def test_email_cannot_collide_with_another_user(self, client, admin):
        with session_scope() as session:
            create_user(
                session,
                email="otro@example.com",
                password_hash=hash_password("AnotherVeryLongPassword2"),
            )

        assert _login(client).status_code == 200
        response = client.patch(
            "/api/v3/auth/profile",
            json={
                "email": "otro@example.com",
                "current_password": ADMIN_PASSWORD,
            },
            headers=_csrf_headers(client),
        )
        assert response.status_code == 409


class TestCookieFlags:
    def test_production_cookie_is_host_prefixed_and_secure(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        settings = Settings(
            _env_file=None,
            ENV="prod",
            SESSION_SECRET="x" * 48,
            DATABASE_URL="sqlite://",
        )
        response = Response()
        set_session_cookie(response, "opaque-token", settings)
        cookie = response.headers["set-cookie"].lower()
        assert cookie.startswith("__host-ft_session=")
        assert "secure" in cookie
        assert "httponly" in cookie
        assert "samesite=lax" in cookie
        assert "path=/" in cookie
        assert "domain=" not in cookie
        assert settings.session_cookie_name == "__Host-ft_session"
