"""Ajustes de modelos editables desde Ajustes y persistidos en ``app_config``.

Las claves de API siguen viviendo solo en el entorno/secreto del despliegue.
Aquí se guardan únicamente parámetros no sensibles: modelo, tamaño de contexto,
tamaño de lote, límites de llamadas y OCR.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .config import get_settings
from .db.session import _session
from .models import AppConfig

PREFIX = "model."
KEY_JEV_MODEL = f"{PREFIX}jev_model"
KEY_JEV_REFERENCE_MAX = f"{PREFIX}jev_reference_max"
KEY_BATCH_SIZE = f"{PREFIX}classification_batch_size"
KEY_JEV_MAX_CALLS = f"{PREFIX}jev_max_calls_per_run"
KEY_OPENCODE_MODEL = f"{PREFIX}opencode_model"
KEY_OPENCODE_FALLBACKS = f"{PREFIX}opencode_fallback_models"
KEY_OCR_LANG = f"{PREFIX}ocr_lang"
KEY_OCR_DPI = f"{PREFIX}ocr_dpi"
KEY_AUTO_APPROVE_THRESHOLD = f"{PREFIX}auto_approve_threshold"

KNOWN_KEYS = {
    KEY_JEV_MODEL,
    KEY_JEV_REFERENCE_MAX,
    KEY_BATCH_SIZE,
    KEY_JEV_MAX_CALLS,
    KEY_OPENCODE_MODEL,
    KEY_OPENCODE_FALLBACKS,
    KEY_OCR_LANG,
    KEY_OCR_DPI,
    KEY_AUTO_APPROVE_THRESHOLD,
}

DEFAULT_REFERENCE_MAX = 40
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_CALLS = 50
DEFAULT_AUTO_APPROVE_THRESHOLD = 0.95
MAX_REFERENCE_MAX = 200
MAX_BATCH_SIZE = 50
MAX_CALLS = 500
MIN_OCR_DPI = 100
MAX_OCR_DPI = 400


@dataclass(frozen=True)
class ModelSettings:
    jev_model: str
    jev_reference_max: int
    classification_batch_size: int
    jev_max_calls_per_run: int
    opencode_model: str
    opencode_fallback_models: tuple[str, ...]
    ocr_lang: str
    ocr_dpi: int
    auto_approve_threshold: float

    def to_public(self) -> dict:
        configured = get_settings()
        return {
            "jev_model": self.jev_model,
            "jev_reference_max": self.jev_reference_max,
            "classification_batch_size": self.classification_batch_size,
            "jev_max_calls_per_run": self.jev_max_calls_per_run,
            "opencode_model": self.opencode_model,
            "opencode_fallback_models": list(self.opencode_fallback_models),
            "ocr_lang": self.ocr_lang,
            "ocr_dpi": self.ocr_dpi,
            "auto_approve_threshold": self.auto_approve_threshold,
            "typesafe_configured": bool(
                configured.typesafe_api_key
                and configured.typesafe_api_key.get_secret_value()
            ),
            "opencode_configured": bool(
                configured.opencode_api_key
                and configured.opencode_api_key.get_secret_value()
            ),
            "limits": {
                "jev_reference_max": [0, MAX_REFERENCE_MAX],
                "classification_batch_size": [1, MAX_BATCH_SIZE],
                "jev_max_calls_per_run": [1, MAX_CALLS],
                "ocr_dpi": [MIN_OCR_DPI, MAX_OCR_DPI],
            },
        }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _defaults() -> ModelSettings:
    settings = get_settings()
    fallbacks = tuple(
        item.strip()
        for item in settings.opencode_fallback_models
        if item and item.strip()
    )
    return ModelSettings(
        jev_model=os.getenv("JEV_MODEL", "jev-latest"),
        jev_reference_max=max(
            0, min(_env_int("JEV_REFERENCE_MAX", DEFAULT_REFERENCE_MAX), MAX_REFERENCE_MAX)
        ),
        classification_batch_size=max(
            1, min(_env_int("CLASSIFICATION_BATCH_SIZE", DEFAULT_BATCH_SIZE), MAX_BATCH_SIZE)
        ),
        jev_max_calls_per_run=max(
            1, min(_env_int("JEV_MAX_CALLS_PER_RUN", DEFAULT_MAX_CALLS), MAX_CALLS)
        ),
        opencode_model=settings.opencode_model,
        opencode_fallback_models=fallbacks,
        ocr_lang=os.getenv("OCR_LANG", "spa+eng"),
        ocr_dpi=max(
            MIN_OCR_DPI, min(_env_int("OCR_DPI", 250), MAX_OCR_DPI)
        ),
        auto_approve_threshold=_env_float(
            "AUTO_APPROVE_THRESHOLD", DEFAULT_AUTO_APPROVE_THRESHOLD
        ),
    )


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return max(0.0, min(float(value), 1.0))
    except ValueError:
        return default


def _parse_float(value: str | None, default: float) -> float:
    try:
        parsed = float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 1.0))


def _parse_int(value: str | None, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _parse_fallbacks(value: str | None, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    return items or default


def load_model_settings(session=None) -> ModelSettings:
    defaults = _defaults()
    try:
        if session is None:
            with _session() as s:
                rows = {
                    row.key: row.value
                    for row in s.query(AppConfig).filter(AppConfig.key.in_(KNOWN_KEYS)).all()
                }
        else:
            rows = {
                row.key: row.value
                for row in session.query(AppConfig)
                .filter(AppConfig.key.in_(KNOWN_KEYS))
                .all()
            }
    except Exception:
        return defaults

    return ModelSettings(
        jev_model=(rows.get(KEY_JEV_MODEL) or defaults.jev_model).strip()
        or defaults.jev_model,
        jev_reference_max=_parse_int(
            rows.get(KEY_JEV_REFERENCE_MAX),
            defaults.jev_reference_max,
            0,
            MAX_REFERENCE_MAX,
        ),
        classification_batch_size=_parse_int(
            rows.get(KEY_BATCH_SIZE),
            defaults.classification_batch_size,
            1,
            MAX_BATCH_SIZE,
        ),
        jev_max_calls_per_run=_parse_int(
            rows.get(KEY_JEV_MAX_CALLS),
            defaults.jev_max_calls_per_run,
            1,
            MAX_CALLS,
        ),
        opencode_model=(rows.get(KEY_OPENCODE_MODEL) or defaults.opencode_model).strip()
        or defaults.opencode_model,
        opencode_fallback_models=_parse_fallbacks(
            rows.get(KEY_OPENCODE_FALLBACKS), defaults.opencode_fallback_models
        ),
        ocr_lang=(rows.get(KEY_OCR_LANG) or defaults.ocr_lang).strip()
        or defaults.ocr_lang,
        ocr_dpi=_parse_int(
            rows.get(KEY_OCR_DPI),
            defaults.ocr_dpi,
            MIN_OCR_DPI,
            MAX_OCR_DPI,
        ),
        auto_approve_threshold=_parse_float(
            rows.get(KEY_AUTO_APPROVE_THRESHOLD),
            defaults.auto_approve_threshold,
        ),
    )


def save_model_settings(session, values: dict) -> ModelSettings:
    """Upsert de ajustes validados y devuelve el estado persistido."""
    current = load_model_settings(session)
    data = {
        KEY_JEV_MODEL: str(values.get("jev_model", current.jev_model)).strip(),
        KEY_JEV_REFERENCE_MAX: str(
            _parse_int(
                str(values.get("jev_reference_max", current.jev_reference_max)),
                current.jev_reference_max,
                0,
                MAX_REFERENCE_MAX,
            )
        ),
        KEY_BATCH_SIZE: str(
            _parse_int(
                str(values.get("classification_batch_size", current.classification_batch_size)),
                current.classification_batch_size,
                1,
                MAX_BATCH_SIZE,
            )
        ),
        KEY_JEV_MAX_CALLS: str(
            _parse_int(
                str(values.get("jev_max_calls_per_run", current.jev_max_calls_per_run)),
                current.jev_max_calls_per_run,
                1,
                MAX_CALLS,
            )
        ),
        KEY_OPENCODE_MODEL: str(
            values.get("opencode_model", current.opencode_model)
        ).strip(),
        KEY_OPENCODE_FALLBACKS: ",".join(
            values.get("opencode_fallback_models")
            or list(current.opencode_fallback_models)
        ),
        KEY_OCR_LANG: str(values.get("ocr_lang", current.ocr_lang)).strip(),
        KEY_AUTO_APPROVE_THRESHOLD: str(
            _parse_float(
                str(values.get("auto_approve_threshold", current.auto_approve_threshold)),
                current.auto_approve_threshold,
            )
        ),
        KEY_OCR_DPI: str(
            _parse_int(
                str(values.get("ocr_dpi", current.ocr_dpi)),
                current.ocr_dpi,
                MIN_OCR_DPI,
                MAX_OCR_DPI,
            )
        ),
    }
    if not data[KEY_JEV_MODEL]:
        data[KEY_JEV_MODEL] = current.jev_model
    if not data[KEY_OPENCODE_MODEL]:
        data[KEY_OPENCODE_MODEL] = current.opencode_model
    if not data[KEY_OCR_LANG]:
        data[KEY_OCR_LANG] = current.ocr_lang

    for key, value in data.items():
        row = session.query(AppConfig).filter_by(key=key).first()
        if row is None:
            session.add(AppConfig(key=key, value=value))
        else:
            row.value = value
    session.flush()
    return load_model_settings(session)


__all__ = [
    "ModelSettings",
    "load_model_settings",
    "save_model_settings",
]
