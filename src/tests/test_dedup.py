"""Tests unitarios de fingerprint/scoring y de la cola L3."""

from __future__ import annotations

from decimal import Decimal

from src.dedup import compute_fingerprint, score_similarity


class TestFingerprint:
    def test_deterministic_and_normalizes_amount(self):
        a = compute_fingerprint(
            "2026-01-15", "-10.005", "EUR", "gasto", "Compra 123e4567-e89b-12d3-a456-426614174000",
        )
        b = compute_fingerprint(
            "2026-01-15", "-10.01", "EUR", "gasto", "compra",
        )
        assert a == b

    def test_different_amount_changes_fingerprint(self):
        a = compute_fingerprint("2026-01-15", "-10.00", "EUR", "gasto", "Compra")
        b = compute_fingerprint("2026-01-15", "-10.01", "EUR", "gasto", "Compra")
        assert a != b

    def test_iban_is_ignored(self):
        a = compute_fingerprint(
            "2026-01-15", "-10.00", "EUR", "gasto",
            "Transferencia (ES1815830001189076828491)",
        )
        b = compute_fingerprint(
            "2026-01-15", "-10.00", "EUR", "gasto", "Transferencia",
        )
        assert a == b


class TestScore:
    def test_identical_is_high(self):
        score = score_similarity(
            "2026-01-15", "2026-01-15", Decimal("-10"), Decimal("-10"),
            "AHORRAMAS", "AHORRAMAS", "gasto", "gasto",
        )
        assert score >= 0.8

    def test_far_dates_or_amounts_do_not_match(self):
        score = score_similarity(
            "2026-01-15", "2026-02-15", Decimal("-10"), Decimal("-10"),
            "AHORRAMAS", "AHORRAMAS", "gasto", "gasto",
        )
        assert score < 0.8
        score = score_similarity(
            "2026-01-15", "2026-01-15", Decimal("-10"), Decimal("-99"),
            "AHORRAMAS", "AHORRAMAS", "gasto", "gasto",
        )
        assert score < 0.8
