"""Smoke tests de la API v3 de negocio (auth + cuentas + analytics)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.auth.passwords import hash_password
from src.auth.service import create_user
from src.config import reset_settings
from src.db.session import get_engine, reset_engine, session_scope
from src.models import (
    Account,
    Asset,
    AssetOpeningPosition,
    Categoria,
    Classification,
    FinancialMovement,
    NormalizedEvent,
    PortfolioSnapshot,
    PortfolioSnapshotPosition,
    RawRow,
    SourceFile,
)

PASSWORD = "CorrectHorseBatteryStaple1"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "api.db"
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-" + "x" * 32)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TYPESAFE_API_KEY", "")
    reset_settings()
    reset_engine()

    from src.models import Base

    Base.metadata.create_all(get_engine())
    with session_scope() as s:
        create_user(
            s,
            email="admin@example.com",
            password_hash=hash_password(PASSWORD),
        )
        tr = Account(
            nombre="Trade Republic",
            iban="ES6415860001480335421911",
            tipo="broker_central",
            es_propia=True,
        )
        s.add(tr)
        s.flush()
        sf = SourceFile(
            source="test",
            filename="test.csv",
            file_hash="a" * 64,
            parser_version="test",
            status="parsed",
            row_count=1,
        )
        s.add(sf)
        s.flush()
        rr = RawRow(
            source_file_id=sf.id,
            row_index=0,
            payload="{}",
            row_hash="b" * 64,
        )
        s.add(rr)
        s.flush()
        ev = NormalizedEvent(
            raw_row_id=rr.id,
            broker_type="CASH_CARD_TRANSACTION",
            kind="gasto",
            value_date=date(2026, 1, 2),
            amount=Decimal("-38.06"),
            currency="EUR",
            fingerprint="c" * 64,
            description_clean="AHORRAMAS",
        )
        s.add(ev)
        s.flush()
        fm = FinancialMovement(
            event_id=ev.id,
            account_id=tr.id,
            kind="gasto",
            direction="-",
            amount=Decimal("-38.06"),
            currency="EUR",
            value_date=date(2026, 1, 2),
            estado="pendiente",
            merchant="AHORRAMAS",
        )
        s.add(fm)
        s.flush()
        cat = Categoria(nombre="Alimentación")
        s.add(cat)
        s.flush()
        s.add(Classification(
            movement_id=fm.id,
            categoria_id=cat.id,
            origen="rule",
            confianza=Decimal("0.99"),
            vigente=True,
        ))

    from src.api import app

    try:
        yield TestClient(app)
    finally:
        reset_engine()
        reset_settings()


def _login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v3/auth/login",
        json={"email": "admin@example.com", "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    return {"X-CSRF-Token": client.cookies["ft_csrf"]}


def test_v3_requires_auth(client: TestClient):
    for path in (
        "/api/v3/movements",
        "/api/v3/accounts",
        "/api/v3/analytics/summary",
        "/api/v3/portfolio/summary",
    ):
        assert client.get(path).status_code == 401


def test_v3_movements_and_analytics(client: TestClient):
    headers = _login(client)
    movements = client.get("/api/v3/movements?page_size=10")
    assert movements.status_code == 200, movements.text
    body = movements.json()
    assert body["total"] == 1
    assert body["items"][0]["merchant"] == "AHORRAMAS"

    stats = client.get("/api/v3/movements/stats")
    assert stats.status_code == 200
    assert stats.json()["total"] == 1

    summary = client.get("/api/v3/analytics/summary")
    assert summary.status_code == 200
    assert summary.json()["gastos"] == 38.06

    categories = client.get("/api/v3/analytics/by-category")
    assert categories.status_code == 200
    assert categories.json()["items"][0]["categoria"] == "Alimentación"

    health = client.get("/api/v3/analytics/data-health")
    assert health.status_code == 200
    assert health.json()["total_movimientos"] == 1

    accounts = client.get("/api/v3/accounts")
    assert accounts.status_code == 200
    assert accounts.json()["items"][0]["nombre"] == "Trade Republic"

    # CSRF obligatorio en mutaciones.
    assert client.patch("/api/v3/movements/1", json={"estado": "aprobado"}).status_code == 403
    updated = client.patch(
        "/api/v3/movements/1",
        json={"estado": "aprobado"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text


def test_v3_classify_next_skips_already_categorized(client: TestClient):
    headers = _login(client)
    response = client.post("/api/v3/classify-next?limit=1", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["processed"] == 0


def test_v3_accounts_can_be_deleted_or_archived(client: TestClient):
    headers = _login(client)

    empty = client.post(
        "/api/v3/accounts",
        json={"nombre": "N26", "tipo": "efectivo_externa"},
        headers=headers,
    )
    assert empty.status_code == 201, empty.text
    empty_id = empty.json()["id"]

    deleted = client.delete(f"/api/v3/accounts/{empty_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["mode"] == "hard"
    assert all(item["id"] != empty_id for item in client.get("/api/v3/accounts").json()["items"])

    accounts = client.get("/api/v3/accounts").json()["items"]
    tr_id = next(item["id"] for item in accounts if item["nombre"] == "Trade Republic")
    archived = client.delete(f"/api/v3/accounts/{tr_id}", headers=headers)
    assert archived.status_code == 200, archived.text
    assert archived.json()["mode"] == "archived"
    assert archived.json()["references"]["movimientos_origen"] == 1

    assert all(
        item["id"] != tr_id for item in client.get("/api/v3/accounts").json()["items"]
    )
    with_inactive = client.get("/api/v3/accounts?include_inactive=true").json()["items"]
    archived_item = next(item for item in with_inactive if item["id"] == tr_id)
    assert archived_item["activo"] is False

    restored = client.patch(
        f"/api/v3/accounts/{tr_id}", json={"activo": True}, headers=headers
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["activo"] is True


def test_v3_taxonomy_categories_tree_and_validation(client: TestClient):
    headers = _login(client)
    categories = client.get("/api/v3/categories")
    assert categories.status_code == 200, categories.text
    root = next(item for item in categories.json()["items"] if item["nombre"] == "Alimentación")
    assert root["aplica_a"] == "gasto"
    assert root["path"] == "Alimentación"

    child = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Supermercado test",
            "parent_id": root["id"],
            "aplica_a": "gasto",
            "color": "#22c55e",
        },
        headers=headers,
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    assert child.json()["path"] == "Alimentación › Supermercado test"

    incompatible = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Incompatible",
            "parent_id": root["id"],
            "aplica_a": "ingreso",
        },
        headers=headers,
    )
    assert incompatible.status_code == 400

    grandchild = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Carnicería test",
            "parent_id": child_id,
            "aplica_a": "gasto",
        },
        headers=headers,
    )
    assert grandchild.status_code == 400, grandchild.text

    # Mover una raíz dentro de una subcategoría se rechaza (dos niveles).
    cycle = client.patch(
        f"/api/v3/categories/{root['id']}",
        json={"parent_id": child_id},
        headers=headers,
    )
    assert cycle.status_code == 400

    # Una categoría usada no se puede borrar; se archiva.
    used = next(item for item in categories.json()["items"] if item["usage_count"] == 1)
    blocked = client.delete(f"/api/v3/categories/{used['id']}", headers=headers)
    assert blocked.status_code == 409
    archived = client.patch(
        f"/api/v3/categories/{used['id']}", json={"activa": False}, headers=headers
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["activa"] is False

    # Un nodo sin uso se puede borrar.
    deleted = client.delete(f"/api/v3/categories/{child_id}", headers=headers)
    assert deleted.status_code == 200, deleted.text


def test_v3_parent_category_assignment_routes_to_default_otros(client: TestClient):
    headers = _login(client)
    created = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Categoría agrupadora test",
            "aplica_a": "gasto",
            "color": "#6366f1",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    root_id = created.json()["id"]
    assert created.json()["assignable"] is False

    categories = client.get("/api/v3/categories").json()["items"]
    root = next(item for item in categories if item["id"] == root_id)
    assert root["assignable"] is False
    default = next(
        item
        for item in categories
        if item["parent_id"] == root_id and item["es_default"] is True
    )
    assert default["nombre"] == "Otros"

    updated = client.patch(
        "/api/v3/movements/1",
        json={"categoria_id": root_id},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["classification"]["categoria_id"] == default["id"]


def test_v3_movement_category_filter_includes_subcategories(client: TestClient):
    headers = _login(client)
    categories = client.get("/api/v3/categories").json()["items"]
    root = next(item for item in categories if item["nombre"] == "Alimentación")
    child = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Supermercado filtro",
            "parent_id": root["id"],
            "aplica_a": "gasto",
        },
        headers=headers,
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]

    with session_scope() as s:
        account = s.query(Account).first()
        source = s.query(SourceFile).first()
        row = RawRow(
            source_file_id=source.id,
            row_index=1,
            payload="{}",
            row_hash="d" * 64,
        )
        s.add(row)
        s.flush()
        event = NormalizedEvent(
            raw_row_id=row.id,
            broker_type="CASH_CARD_TRANSACTION",
            kind="gasto",
            value_date=date(2026, 1, 3),
            amount=Decimal("-12.34"),
            currency="EUR",
            fingerprint="e" * 64,
            description_clean="SUPERMERCADO FILTRO",
        )
        s.add(event)
        s.flush()
        movement = FinancialMovement(
            event_id=event.id,
            account_id=account.id,
            kind="gasto",
            direction="-",
            amount=Decimal("-12.34"),
            currency="EUR",
            value_date=date(2026, 1, 3),
            estado="aprobado",
            merchant="SUPERMERCADO FILTRO",
        )
        s.add(movement)
        s.flush()
        s.add(
            Classification(
                movement_id=movement.id,
                categoria_id=child_id,
                origen="user",
                confianza=Decimal("1.0"),
                vigente=True,
            )
        )

    filtered_root = client.get(f"/api/v3/movements?categoria_id={root['id']}")
    assert filtered_root.status_code == 200, filtered_root.text
    assert filtered_root.json()["total"] == 2

    filtered_child = client.get(f"/api/v3/movements?categoria_id={child_id}")
    assert filtered_child.status_code == 200, filtered_child.text
    assert filtered_child.json()["total"] == 1


def test_v3_taxonomy_tags_and_groups(client: TestClient):
    headers = _login(client)

    group = client.post(
        "/api/v3/tag-groups",
        json={"nombre": "Viajes test", "color": "#14b8a6"},
        headers=headers,
    )
    assert group.status_code == 201, group.text
    group_id = group.json()["id"]

    tag = client.post(
        "/api/v3/tags",
        json={"nombre": "Korea test", "color": "#14b8a6", "group_id": group_id},
        headers=headers,
    )
    assert tag.status_code == 201, tag.text
    tag_id = tag.json()["id"]
    assert tag.json()["group_nombre"] == "Viajes test"

    moved = client.patch(
        f"/api/v3/tags/{tag_id}", json={"group_id": None}, headers=headers
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["group_id"] is None

    groups = client.get("/api/v3/tag-groups")
    assert groups.status_code == 200
    ungrouped = groups.json()["ungrouped"]
    assert any(item["id"] == tag_id for item in ungrouped)

    deleted_group = client.delete(f"/api/v3/tag-groups/{group_id}", headers=headers)
    assert deleted_group.status_code == 200, deleted_group.text
    deleted_tag = client.delete(f"/api/v3/tags/{tag_id}", headers=headers)
    assert deleted_tag.status_code == 200, deleted_tag.text


def test_model_settings_roundtrip(client: TestClient):
    headers = _login(client)
    current = client.get("/api/v3/settings/models")
    assert current.status_code == 200, current.text
    assert current.json()["jev_reference_max"] == 40

    updated = client.patch(
        "/api/v3/settings/models",
        json={
            "jev_reference_max": 12,
            "classification_batch_size": 6,
            "jev_max_calls_per_run": 20,
            "ocr_dpi": 200,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["jev_reference_max"] == 12
    assert updated.json()["classification_batch_size"] == 6

    invalid = client.patch(
        "/api/v3/settings/models",
        json={"jev_reference_max": 999},
        headers=headers,
    )
    assert invalid.status_code == 422


def test_account_initial_balance_date_filters_movements(client: TestClient):
    headers = _login(client)
    account_id = client.get("/api/v3/accounts").json()["items"][0]["id"]

    before = client.patch(
        f"/api/v3/accounts/{account_id}",
        json={"balance_inicial": 100, "balance_inicial_fecha": "2026-01-03"},
        headers=headers,
    )
    assert before.status_code == 200, before.text
    assert before.json()["balance"] == 100

    after = client.patch(
        f"/api/v3/accounts/{account_id}",
        json={"balance_inicial_fecha": "2026-01-01"},
        headers=headers,
    )
    assert after.status_code == 200, after.text
    assert after.json()["balance"] == 61.94


def test_analytics_period_filters(client: TestClient):
    _login(client)
    in_range = client.get(
        "/api/v3/analytics/summary?desde=2026-01-01&hasta=2026-01-31"
    )
    assert in_range.status_code == 200
    assert in_range.json()["gastos"] == 38.06
    assert "01/01/2026" in in_range.json()["period"]["label"]

    out_of_range = client.get(
        "/api/v3/analytics/summary?desde=2026-02-01&hasta=2026-02-28"
    )
    assert out_of_range.status_code == 200
    assert out_of_range.json()["gastos"] == 0
    assert out_of_range.json()["flujo_neto"] == 0

    cashflow = client.get(
        "/api/v3/analytics/cashflow?desde=2026-02-01&hasta=2026-02-28"
    )
    assert cashflow.status_code == 200
    items = cashflow.json()["items"]
    assert len(items) == 1
    assert items[0]["month"] == "2026-02"
    assert items[0]["ingresos"] == 0
    assert items[0]["gastos"] == 0


def test_analytics_cashflow_granularity(client: TestClient):
    _login(client)
    daily = client.get(
        "/api/v3/analytics/cashflow"
        "?desde=2026-01-01&hasta=2026-01-03&granularity=day"
    )
    assert daily.status_code == 200, daily.text
    assert [item["month"] for item in daily.json()["items"]] == [
        "2026-01-01",
        "2026-01-02",
        "2026-01-03",
    ]
    assert daily.json()["items"][1]["gastos"] == 38.06
    assert daily.json()["granularity"] == "day"

    yearly = client.get(
        "/api/v3/analytics/cashflow"
        "?desde=2025-01-01&hasta=2026-12-31&granularity=year"
    )
    assert yearly.status_code == 200, yearly.text
    assert [item["month"] for item in yearly.json()["items"]] == ["2025", "2026"]
    assert yearly.json()["items"][0]["gastos"] == 0
    assert yearly.json()["items"][1]["gastos"] == 38.06

    weekly = client.get(
        "/api/v3/analytics/cashflow"
        "?desde=2026-01-01&hasta=2026-01-15&granularity=week"
    )
    assert weekly.status_code == 200, weekly.text
    assert [item["month"] for item in weekly.json()["items"]] == [
        "2025-12-29",
        "2026-01-05",
        "2026-01-12",
    ]
    assert weekly.json()["items"][0]["gastos"] == 38.06
    assert weekly.json()["granularity"] == "week"


def test_analytics_cashflow_all_returns_every_bucket(client: TestClient):
    _login(client)
    with session_scope() as s:
        source_file = s.query(SourceFile).first()
        account = s.query(Account).first()
        raw_row = RawRow(
            source_file_id=source_file.id,
            row_index=1,
            payload="{}",
            row_hash="d" * 64,
        )
        s.add(raw_row)
        s.flush()
        event = NormalizedEvent(
            raw_row_id=raw_row.id,
            broker_type="CASH_CARD_TRANSACTION",
            kind="gasto",
            value_date=date(2025, 1, 2),
            amount=Decimal("-10.00"),
            currency="EUR",
            fingerprint="e" * 64,
            description_clean="TEST",
        )
        s.add(event)
        s.flush()
        s.add(FinancialMovement(
            event_id=event.id,
            account_id=account.id,
            kind="gasto",
            direction="-",
            amount=Decimal("-10.00"),
            currency="EUR",
            value_date=date(2025, 1, 2),
            estado="pendiente",
            merchant="TEST",
        ))

    limited = client.get(
        "/api/v3/analytics/cashflow?months=1&granularity=month"
    )
    assert limited.status_code == 200, limited.text
    assert [item["month"] for item in limited.json()["items"]] == ["2026-01"]

    everything = client.get(
        "/api/v3/analytics/cashflow?all=true&granularity=month"
    )
    assert everything.status_code == 200, everything.text
    assert [item["month"] for item in everything.json()["items"]] == [
        "2025-01",
        "2026-01",
    ]


def test_analytics_exclude_transfer_categories_and_tab_uses_treatment(client: TestClient):
    headers = _login(client)
    with session_scope() as s:
        account = s.query(Account).first()
        root = Categoria(
            nombre="Transferencias",
            aplica_a="ambos",
            tratamiento="transferencia",
            excluir_kpis=True,
        )
        s.add(root)
        s.flush()
        child = Categoria(
            nombre="Otros",
            parent_id=root.id,
            aplica_a="ambos",
            tratamiento="transferencia",
            excluir_kpis=True,
            es_default=True,
        )
        s.add(child)
        s.flush()
        sf = s.query(SourceFile).first()
        rr = RawRow(
            source_file_id=sf.id,
            row_index=1,
            payload="{}",
            row_hash="d" * 64,
        )
        s.add(rr)
        s.flush()
        ev = NormalizedEvent(
            raw_row_id=rr.id,
            broker_type="CASH_TRANSFER_AGENTIC",
            kind="transferencia_interna",
            value_date=date(2026, 1, 4),
            amount=Decimal("100.00"),
            currency="EUR",
            fingerprint="e" * 64,
            description_clean="TRASPASO",
        )
        s.add(ev)
        s.flush()
        fm = FinancialMovement(
            event_id=ev.id,
            account_id=account.id,
            kind="transferencia_interna",
            direction="+",
            amount=Decimal("100.00"),
            currency="EUR",
            value_date=date(2026, 1, 4),
            estado="aprobado",
            merchant="TRASPASO",
        )
        s.add(fm)
        s.flush()
        s.add(Classification(
            movement_id=fm.id,
            categoria_id=child.id,
            origen="rule",
            confianza=Decimal("0.99"),
            vigente=True,
        ))

    summary = client.get("/api/v3/analytics/summary")
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["gastos"] == 38.06
    assert body["ingresos"] == 0
    assert body["transferencias_netas"] == 100.0

    cashflow = client.get("/api/v3/analytics/cashflow?desde=2026-01-01&hasta=2026-01-31")
    assert cashflow.status_code == 200, cashflow.text
    assert cashflow.json()["items"][0]["gastos"] == 38.06
    assert cashflow.json()["items"][0]["ingresos"] == 0

    by_category = client.get("/api/v3/analytics/by-category")
    assert by_category.status_code == 200, by_category.text
    assert all(
        item["categoria"] != "Transferencias › Otros"
        for item in by_category.json()["items"]
    )
    with_excluded = client.get("/api/v3/analytics/by-category?include_excluded=true")
    assert with_excluded.status_code == 200, with_excluded.text
    assert any(
        item["categoria"] == "Transferencias › Otros"
        for item in with_excluded.json()["items"]
    )

    tab = client.get("/api/v3/movements?tab=transferencias", headers=headers)
    assert tab.status_code == 200, tab.text
    assert tab.json()["total"] == 1


def test_upload_allows_automatic_account_resolution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("IMPORT_QUEUE_MODE", "worker")
    headers = _login(client)
    created = client.post(
        "/api/v3/accounts",
        json={
            "nombre": "Revolut Cuenta Corriente",
            "iban": "ES1815830001189076828491",
            "tipo": "efectivo_externa",
            "broker": "revolut",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    response = client.post(
        "/api/v3/imports",
        files={"files": ("extracto.csv", b"date,amount\n2026-01-01,-1\n", "text/csv")},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["import"]["status"] == "queued"
    assert response.json()["import"]["account_id"] is None


def test_confirm_account_creates_and_requeues_atomically(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("IMPORT_QUEUE_MODE", "worker")
    headers = _login(client)
    with session_scope() as s:
        sf = SourceFile(
            source="agentic_statement",
            filename="revolut.pdf",
            file_hash="f" * 64,
            parser_version="agentic-v1",
            status="needs_review",
            storage_path=str(tmp_path / "revolut.pdf"),
            extraction_meta=json.dumps({
                "detected": {
                    "bank": "Revolut",
                    "account_iban": "ES0815830001139109642173",
                    "product": "Cuenta Conjunta",
                }
            }),
        )
        s.add(sf)
        s.flush()
        import_id = sf.id

    response = client.post(
        f"/api/v3/imports/{import_id}/confirm-account",
        json={
            "action": "create",
            "account": {
                "nombre": "Revolut Cuenta Conjunta",
                "iban": "ES0815830001139109642173",
                "tipo": "efectivo_externa",
                "broker": "revolut",
                "es_propia": True,
                "moneda": "EUR",
            },
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    with session_scope() as s:
        account = s.query(Account).filter_by(
            iban="ES0815830001139109642173"
        ).one()
        sf = s.query(SourceFile).filter_by(id=import_id).one()
        assert sf.account_id == account.id
        assert sf.status == "queued"
        assert sf.error is None



def _quarantined_import(tmp_path: Path, **overrides) -> int:
    stored = tmp_path / "stored.pdf"
    stored.write_bytes(b"%PDF-1.4 test")
    values = dict(
        source="agentic_statement",
        filename="Revolut_2026_conjunta.pdf",
        file_hash="e" * 64,
        parser_version="agentic-v1",
        status="needs_review",
        storage_path=str(stored),
        balance_start=Decimal("120.50"),
        balance_start_date=date(2026, 1, 1),
        extraction_meta=json.dumps({
            "detected": {
                "bank": "Revolut",
                "account_iban": "ES08 1583 0001 1391 0964 2173",
                "product": None,
            },
            "account_match": {
                "status": "new_account",
                "reason": "El IBAN detectado no pertenece a ninguna cuenta registrada.",
                "requires_confirmation": True,
                "candidates": [],
            },
        }),
    )
    values.update(overrides)
    with session_scope() as s:
        sf = SourceFile(**values)
        s.add(sf)
        s.flush()
        return sf.id


def test_import_list_exposes_pending_account_action(
    client: TestClient, tmp_path: Path
):
    headers = _login(client)
    import_id = _quarantined_import(tmp_path)
    response = client.get("/api/v3/imports", headers=headers)
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["id"] == import_id)
    action = item["pending_action"]
    assert action["type"] == "create_account"
    proposed = action["proposed_account"]
    assert proposed["nombre"] == "Revolut Cuenta Conjunta"
    assert proposed["iban"] == "ES0815830001139109642173"
    assert proposed["broker"] == "revolut"
    assert proposed["tipo"] == "efectivo_externa"
    assert proposed["balance_inicial"] == 120.5
    assert proposed["balance_inicial_fecha"] == "2026-01-01"
    assert item["size_bytes"] == len(b"%PDF-1.4 test")


def test_proposed_account_name_does_not_repeat_bank():
    from src.api_v3_data import _proposed_account_name

    assert _proposed_account_name("Trade Republic", "Trade Republic", "x.pdf") == "Trade Republic"
    assert _proposed_account_name("Revolut", None, "Revolut_2026_personal.pdf") == (
        "Revolut Cuenta Corriente"
    )
    assert _proposed_account_name(None, None, "a.csv") == "Cuenta detectada"


def test_delete_import_discards_file_without_data(
    client: TestClient, tmp_path: Path
):
    headers = _login(client)
    import_id = _quarantined_import(tmp_path)
    response = client.delete(f"/api/v3/imports/{import_id}", headers=headers)
    assert response.status_code == 200, response.text
    assert not (tmp_path / "stored.pdf").exists()
    with session_scope() as s:
        assert s.query(SourceFile).filter_by(id=import_id).first() is None


def test_delete_import_refuses_processing_file(
    client: TestClient, tmp_path: Path
):
    headers = _login(client)
    import_id = _quarantined_import(tmp_path, status="processing")
    response = client.delete(f"/api/v3/imports/{import_id}", headers=headers)
    assert response.status_code == 409


def test_portfolio_uses_market_value_and_unknown_cost_is_not_zero(
    client: TestClient,
):
    _login(client)
    with session_scope() as s:
        account = s.query(Account).first()
        amzn = Asset(
            symbol="AMZN", isin="US0231351067", nombre="Amazon",
            asset_class="stock", moneda="EUR",
        )
        msft = Asset(
            symbol="MSFT", isin="US5949181045", nombre="Microsoft",
            asset_class="stock", moneda="EUR",
        )
        s.add_all([amzn, msft])
        s.flush()
        snapshot = PortfolioSnapshot(
            account_id=account.id,
            snapshot_date=date(2026, 11, 2),
            custody_ref="portfolio",
            cash_declared=Decimal("50"),
            total_declared=Decimal("400"),
        )
        s.add(snapshot)
        s.flush()
        s.add_all([
            PortfolioSnapshotPosition(
                snapshot_id=snapshot.id,
                asset_id=amzn.id,
                quantity=Decimal("1"),
                price=Decimal("200"),
                value=Decimal("200"),
                price_date=date(2026, 11, 2),
            ),
            PortfolioSnapshotPosition(
                snapshot_id=snapshot.id,
                asset_id=msft.id,
                quantity=Decimal("1"),
                price=Decimal("150"),
                value=Decimal("150"),
                price_date=date(2026, 11, 2),
            ),
            AssetOpeningPosition(
                account_id=account.id,
                asset_id=amzn.id,
                as_of_date=date(2026, 1, 1),
                quantity=Decimal("1"),
                cost_total=None,
                cost_status="unknown",
                source="snapshot",
            ),
            AssetOpeningPosition(
                account_id=account.id,
                asset_id=msft.id,
                as_of_date=date(2026, 1, 1),
                quantity=Decimal("1"),
                cost_total=Decimal("100"),
                cost_status="known",
                source="snapshot",
            ),
        ])

    response = client.get("/api/v3/portfolio/summary")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["valor_total"] == 350.0
    assert body["coste_total"] == 100.0
    assert body["pnl_no_realizado"] == 50.0
    by_symbol = {position["symbol"]: position for position in body["posiciones"]}
    assert by_symbol["AMZN"]["datos_incompletos"] is True
    assert by_symbol["AMZN"]["cobertura_coste"] == 0.0
    assert by_symbol["MSFT"]["pnl_no_realizado"] == 50.0
    assert any("coste desconocido" in warning for warning in body["avisos"])

    history = client.get("/api/v3/portfolio/history")
    assert history.status_code == 200, history.text
    assert history.json()["items"][0]["total"] == 400.0


def test_v3_subcategory_inherits_treatment_and_bulk_resolves_leaf(client: TestClient):
    headers = _login(client)
    root = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Inversiones test",
            "aplica_a": "ambos",
            "tratamiento": "inversion",
            "color": "#0f766e",
        },
        headers=headers,
    )
    assert root.status_code == 201, root.text
    root_id = root.json()["id"]
    assert root.json()["assignable"] is False

    child = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Ventas test",
            "parent_id": root_id,
            "aplica_a": "ingreso",
            "tratamiento": "normal",
        },
        headers=headers,
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    assert child.json()["tratamiento"] == "inversion"
    assert child.json()["excluir_kpis"] is True
    assert child.json()["depth"] == 1

    mismatch = client.patch(
        f"/api/v3/categories/{child_id}",
        json={"tratamiento": "normal"},
        headers=headers,
    )
    assert mismatch.status_code == 400

    grandchild = client.post(
        "/api/v3/categories",
        json={"nombre": "Nieta test", "parent_id": child_id},
        headers=headers,
    )
    assert grandchild.status_code == 400

    bulk = client.post(
        "/api/v3/movements/bulk",
        json={"ids": [1], "action": "set_category", "categoria_id": child_id},
        headers=headers,
    )
    assert bulk.status_code == 200, bulk.text
    with session_scope() as s:
        current = (
            s.query(Classification)
            .filter_by(movement_id=1, vigente=True)
            .one()
        )
        assert current.categoria_id == child_id


def test_v3_partial_classification_update_preserves_category(client: TestClient):
    headers = _login(client)
    with session_scope() as s:
        before = (
            s.query(Classification)
            .filter_by(movement_id=1, vigente=True)
            .one()
            .categoria_id
        )
    updated = client.patch(
        "/api/v3/movements/1",
        json={"subtipo": "variable"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["classification"]["categoria_id"] == before
    assert updated.json()["classification"]["subtipo"] == "variable"


def test_v3_investment_sale_does_not_inflate_income(client: TestClient):
    with session_scope() as s:
        account = s.query(Account).first()
        source = s.query(SourceFile).first()
        row = RawRow(
            source_file_id=source.id,
            row_index=2,
            payload="{}",
            row_hash="e" * 64,
        )
        s.add(row)
        s.flush()
        event = NormalizedEvent(
            raw_row_id=row.id,
            broker_type="SELL",
            kind="inversion_venta",
            value_date=date(2026, 1, 3),
            amount=Decimal("100.00"),
            currency="EUR",
            fingerprint="f" * 64,
            description_clean="SELL TRADE",
        )
        s.add(event)
        s.flush()
        movement = FinancialMovement(
            event_id=event.id,
            account_id=account.id,
            kind="inversion_venta",
            direction="+",
            amount=Decimal("100.00"),
            currency="EUR",
            value_date=date(2026, 1, 3),
            estado="aprobado",
            merchant="Venta test",
        )
        s.add(movement)
        s.flush()
        category = Categoria(
            nombre="Ingresos test",
            aplica_a="ingreso",
            tratamiento="normal",
            excluir_kpis=False,
        )
        s.add(category)
        s.flush()
        s.add(Classification(
            movement_id=movement.id,
            categoria_id=category.id,
            origen="broker",
            confianza=Decimal("0.99"),
            vigente=True,
        ))

    headers = _login(client)
    summary = client.get("/api/v3/analytics/summary", headers=headers)
    assert summary.status_code == 200, summary.text
    assert summary.json()["ingresos"] == 0
    assert summary.json()["gastos"] == 38.06


def test_v3_root_treatment_can_change_to_normal(client: TestClient):
    headers = _login(client)
    root = client.post(
        "/api/v3/categories",
        json={
            "nombre": "Raíz KPI test",
            "aplica_a": "ambos",
            "tratamiento": "inversion",
            "excluir_kpis": True,
        },
        headers=headers,
    )
    assert root.status_code == 201, root.text
    root_id = root.json()["id"]
    child = client.post(
        "/api/v3/categories",
        json={"nombre": "Hija KPI test", "parent_id": root_id},
        headers=headers,
    )
    assert child.status_code == 201, child.text
    child_id = child.json()["id"]
    assert child.json()["tratamiento"] == "inversion"

    updated = client.patch(
        f"/api/v3/categories/{root_id}",
        json={"tratamiento": "normal"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["tratamiento"] == "normal"
    assert updated.json()["excluir_kpis"] is False
    child_after = client.get("/api/v3/categories").json()["items"]
    child_payload = next(item for item in child_after if item["id"] == child_id)
    assert child_payload["tratamiento"] == "normal"
    assert child_payload["excluir_kpis"] is False


def test_reprocess_requeues_in_worker_mode(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.setenv("IMPORT_QUEUE_MODE", "worker")
    headers = _login(client)
    import_id = _quarantined_import(tmp_path, status="failed")
    response = client.post(f"/api/v3/imports/{import_id}/reprocess", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "queued"


def test_needs_review_without_account_block_has_no_blocking_action(
    client: TestClient, tmp_path: Path
):
    headers = _login(client)
    import_id = _quarantined_import(
        tmp_path,
        extraction_meta=json.dumps({"account_match": {"status": "match"}}),
    )
    with session_scope() as s:
        sf = s.query(SourceFile).filter_by(id=import_id).one()
        sf.account_id = s.query(Account).first().id
    item = next(
        i for i in client.get("/api/v3/imports", headers=headers).json()["items"]
        if i["id"] == import_id
    )
    assert item["pending_action"] is None
