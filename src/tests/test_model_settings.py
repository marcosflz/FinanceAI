"""Tests de ajustes de modelo persistidos en app_config."""

from __future__ import annotations

from src.db.session import _session
from src.model_settings import load_model_settings, save_model_settings


def test_defaults_are_available_without_rows(db):
    settings = load_model_settings()
    assert settings.jev_model
    assert settings.jev_reference_max == 40
    assert settings.classification_batch_size == 10
    assert settings.ocr_dpi >= 100
    assert settings.auto_approve_threshold == 0.95


def test_save_and_reload_runtime_settings(db):
    with _session() as session:
        saved = save_model_settings(
            session,
            {
                "jev_model": "jev-latest",
                "jev_reference_max": 25,
                "classification_batch_size": 7,
                "jev_max_calls_per_run": 12,
                "opencode_model": "deepseek-v4.1-flash",
                "opencode_fallback_models": ["glm-5.3-flash"],
                "ocr_lang": "spa",
                "ocr_dpi": 220,
                "auto_approve_threshold": 0.9,
            },
        )
    assert saved.jev_reference_max == 25
    assert saved.classification_batch_size == 7
    assert saved.ocr_dpi == 220
    assert saved.auto_approve_threshold == 0.9

    loaded = load_model_settings()
    assert loaded.jev_reference_max == 25
    assert loaded.classification_batch_size == 7
    assert loaded.jev_max_calls_per_run == 12
    assert loaded.opencode_fallback_models == ("glm-5.3-flash",)


def test_values_are_clamped_to_safe_ranges(db):
    with _session() as session:
        saved = save_model_settings(
            session,
            {
                "jev_reference_max": 999,
                "classification_batch_size": 0,
                "jev_max_calls_per_run": 9999,
                "ocr_dpi": 999,
            },
        )
    assert saved.jev_reference_max == 200
    assert saved.classification_batch_size == 1
    assert saved.jev_max_calls_per_run == 500
    assert saved.ocr_dpi == 400
