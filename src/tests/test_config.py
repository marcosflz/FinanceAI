"""Tests de configuración tipada y carga de entorno."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.config import Settings, get_settings, reset_settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in (
        "ENV",
        "DATABASE_URL",
        "DATA_DIR",
        "SESSION_SECRET",
        "SESSION_TTL_DAYS",
        "COOKIE_SECURE",
        "ADMIN_EMAIL",
        "ADMIN_PASSWORD_HASH",
        "TYPESAFE_API_KEY",
        "OPENCODE_API_KEY",
        "OPENCODE_MODEL",
        "OPENCODE_FALLBACK_MODELS",
        "CORS_ORIGINS",
    ):
        monkeypatch.delenv(name, raising=False)
    reset_settings()
    yield
    reset_settings()


def test_defaults():
    settings = Settings(_env_file=None)
    assert settings.env == "dev"
    assert settings.database_url == "sqlite:///./financial.db"
    assert settings.data_dir.as_posix() == "data/files"
    assert settings.session_ttl_days == 7
    assert settings.opencode_model == "deepseek-v4.1-flash"
    assert settings.cookie_secure_effective is False
    assert settings.session_cookie_name == "ft_session"


def test_database_url_postgres_uses_psycopg3():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://usuario:secreto@db:5432/financial",
    )
    assert settings.database_url == "postgresql+psycopg://usuario:secreto@db:5432/financial"


def test_lists_accept_comma_separated_and_json(monkeypatch):
    monkeypatch.setenv("OPENCODE_FALLBACK_MODELS", "glm-5.3-flash, qwen3.8-flash")
    monkeypatch.setenv("CORS_ORIGINS", '["https://app.example.com"]')
    settings = Settings(_env_file=None)
    assert settings.opencode_fallback_models == ["glm-5.3-flash", "qwen3.8-flash"]
    assert settings.cors_origins == ["https://app.example.com"]


def test_loads_env_file(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ENV=test\n"
        "OPENCODE_MODEL=modelo-desde-env-file\n"
        "OPENCODE_FALLBACK_MODELS=a,b\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.env == "test"
    assert settings.opencode_model == "modelo-desde-env-file"
    assert settings.opencode_fallback_models == ["a", "b"]


def test_get_settings_is_cached_and_resettable(monkeypatch):
    monkeypatch.setenv("ENV", "test")
    first = get_settings()
    second = get_settings()
    assert first is second
    reset_settings()
    assert get_settings() is not first


def test_production_requires_explicit_session_secret(monkeypatch):
    monkeypatch.delenv("SESSION_SECRET", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, ENV="prod")


def test_production_cookie_is_host_prefixed():
    settings = Settings(_env_file=None, ENV="production", SESSION_SECRET="x" * 48)
    assert settings.env == "prod"
    assert settings.is_production is True
    assert settings.cookie_secure_effective is True
    assert settings.session_cookie_name == "__Host-ft_session"


def test_safe_summary_never_exposes_secrets():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://usuario:super-secreto@db:5432/financial",
        SESSION_SECRET="otro-secreto",
        OPENCODE_API_KEY="oc_sk_secreto",
        TYPESAFE_API_KEY="typ_secreto",
    )
    summary = settings.safe_summary()
    encoded = repr(summary)
    assert "super-secreto" not in encoded
    assert "otro-secreto" not in encoded
    assert "oc_sk_secreto" not in encoded
    assert "typ_secreto" not in encoded
    assert "***" in summary["database_url"]
    assert summary["opencode_configured"] is True
    assert summary["typesafe_configured"] is True
