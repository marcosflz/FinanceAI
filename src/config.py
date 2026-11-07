"""Configuración tipada de la aplicación.

Lee variables de entorno y, en desarrollo, el fichero ``.env`` de la raíz
del repositorio. Nunca se registran secretos: las claves y hashes usan
``SecretStr`` y el resumen seguro de :meth:`Settings.safe_summary` los omite.

La configuración se cachea con ``get_settings()`` para no releer el entorno
en cada petición. En tests se puede limpiar la caché con
``reset_settings()``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Carga .env también en os.environ para módulos heredados que usan os.getenv
# (llm_config, clientes de IA, scripts). pydantic-settings ya lo lee para
# Settings, pero no exporta cada variable al proceso.
load_dotenv()

_DEV_SESSION_SECRET = "dev-only-insecure-session-secret-change-me"
_DEFAULT_FALLBACK_MODELS = [
    "glm-5.3-flash",
    "qwen3.8-flash",
    "mimo-v2.6-flash",
    "gpt-6-luna",
]


def _parse_list(value: Any) -> list[str]:
    """Acepta listas JSON, listas separadas por comas o listas ya tipadas."""
    if value is None or value == "":
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:  # pragma: no cover - defensivo
                raise ValueError("La lista debe ser JSON válido o valores separados por comas") from exc
            if not isinstance(parsed, list):
                raise ValueError("La lista debe ser un array JSON")
            return [str(item).strip() for item in parsed if str(item).strip()]
        return [item.strip() for item in raw.split(",") if item.strip()]
    raise ValueError("Valor de lista no soportado")


def _normalise_database_url(value: str) -> str:
    """Fuerza el driver psycopg v3 sin romper URLs SQLite existentes."""
    url = (value or "").strip()
    if not url:
        return "sqlite:///./financial.db"
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    """Configuración efectiva de la aplicación."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Entorno y almacenamiento
    env: str = Field(default="dev", validation_alias="ENV")
    data_dir: Path = Field(default=Path("data/files"), validation_alias="DATA_DIR")
    database_url: str = Field(
        default="sqlite:///./financial.db", validation_alias="DATABASE_URL"
    )

    # Sesiones / cookies
    session_secret: SecretStr = Field(
        default=SecretStr(_DEV_SESSION_SECRET), validation_alias="SESSION_SECRET"
    )
    session_ttl_days: int = Field(default=7, ge=1, le=365, validation_alias="SESSION_TTL_DAYS")
    # None = automático (Secure en prod, no Secure en dev). Un valor explícito
    # permite servir por HTTP en LAN sin romper el login.
    cookie_secure: bool | None = Field(default=None, validation_alias="COOKIE_SECURE")

    # Administrador inicial
    admin_email: str | None = Field(default=None, validation_alias="ADMIN_EMAIL")
    admin_password_hash: SecretStr | None = Field(
        default=None, validation_alias="ADMIN_PASSWORD_HASH"
    )

    # Proveedores externos (nunca se loguean)
    typesafe_api_key: SecretStr | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")
    opencode_api_key: SecretStr | None = Field(default=None, validation_alias="OPENCODE_API_KEY")
    opencode_model: str = Field(
        default="deepseek-v4.1-flash", validation_alias="OPENCODE_MODEL"
    )
    opencode_fallback_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: list(_DEFAULT_FALLBACK_MODELS),
        validation_alias="OPENCODE_FALLBACK_MODELS",
    )

    # CORS (same-origin por defecto en desarrollo)
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"],
        validation_alias="CORS_ORIGINS",
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _validate_database_url(cls, value: Any) -> str:
        return _normalise_database_url(str(value) if value is not None else "")

    @field_validator("data_dir", mode="before")
    @classmethod
    def _validate_data_dir(cls, value: Any) -> Path:
        return Path(str(value)) if value not in (None, "") else Path("data/files")

    @field_validator("admin_email", mode="before")
    @classmethod
    def _empty_email_to_none(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value.strip() if isinstance(value, str) else value

    @field_validator("admin_password_hash", mode="before")
    @classmethod
    def _empty_hash_to_none(cls, value: Any) -> Any:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("typesafe_api_key", "opencode_api_key", mode="before")
    @classmethod
    def _empty_secret_to_none(cls, value: Any) -> Any:
        if isinstance(value, SecretStr):
            value = value.get_secret_value()
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("opencode_fallback_models", "cors_origins", mode="before")
    @classmethod
    def _validate_lists(cls, value: Any) -> list[str]:
        return _parse_list(value)

    @field_validator("env", mode="before")
    @classmethod
    def _normalise_env(cls, value: Any) -> str:
        raw = str(value or "dev").strip().lower()
        if raw in {"production", "prod"}:
            return "prod"
        return raw

    @model_validator(mode="after")
    def _reject_insecure_production_secret(self) -> Settings:
        secret = self.session_secret.get_secret_value()
        weak = {
            "",
            _DEV_SESSION_SECRET,
            "cambia-esto-por-un-secreto-aleatorio",
            "change-me",
        }
        if self.is_production and (secret in weak or len(secret) < 32):
            raise ValueError(
                "SESSION_SECRET debe ser un valor aleatorio de al menos 32 caracteres "
                "en producción"
            )
        return self

    # ── Propiedades derivadas ────────────────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.env == "prod"

    @property
    def sqlalchemy_database_url(self) -> str:
        return self.database_url

    @property
    def session_cookie_name(self) -> str:
        # El prefijo __Host- exige Secure, Path=/ y ausencia de Domain.
        return "__Host-ft_session" if self.cookie_secure_effective else "ft_session"

    @property
    def csrf_cookie_name(self) -> str:
        return "ft_csrf"

    @property
    def cookie_secure_effective(self) -> bool:
        if self.cookie_secure is not None:
            return bool(self.cookie_secure)
        return self.is_production

    @property
    def session_ttl_seconds(self) -> int:
        return int(self.session_ttl_days * 24 * 60 * 60)

    @property
    def session_secret_value(self) -> str:
        return self.session_secret.get_secret_value()

    @property
    def admin_password_hash_value(self) -> str | None:
        if self.admin_password_hash is None:
            return None
        return self.admin_password_hash.get_secret_value()

    def ensure_data_dir(self) -> Path:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return self.data_dir

    def safe_summary(self) -> dict[str, Any]:
        """Resumen apto para logs/health: nunca incluye secretos."""
        return {
            "env": self.env,
            "database_url": _redact_database_url(self.database_url),
            "data_dir": str(self.data_dir),
            "session_ttl_days": self.session_ttl_days,
            "cookie_secure": self.cookie_secure_effective,
            "admin_email": self.admin_email,
            "opencode_model": self.opencode_model,
            "opencode_fallback_models": list(self.opencode_fallback_models),
            "cors_origins": list(self.cors_origins),
            "typesafe_configured": self.typesafe_api_key is not None,
            "opencode_configured": self.opencode_api_key is not None,
        }


def _redact_database_url(url: str) -> str:
    """Oculta la contraseña de una URL de base de datos."""
    if "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" not in rest:
        return url
    credentials, host = rest.rsplit("@", 1)
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Devuelve la configuración cacheada de la aplicación."""
    return Settings()


def reset_settings() -> None:
    """Limpia la caché de configuración (tests y cambios de entorno)."""
    get_settings.cache_clear()
