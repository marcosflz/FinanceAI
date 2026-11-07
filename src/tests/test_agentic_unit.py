"""Tests del extractor agéntico con cliente LLM falso (sin red)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook

from src.ai.document_agent import ExtractedText, FileKind, FileProbe
from src.ai.schemas import LLMResult
from src.ingest.agentic import (
    AgenticStatementExtractor,
    PdfPageDraft,
    PdfRow,
    PdfSummaryDraft,
    StatementMapping,
    StatementMappingDraft,
    _summary_from_text,
)


class FakeClient:
    model = "fake-model"

    def __init__(self, parsed=None, *, by_schema=None):
        self.parsed = parsed
        self.by_schema = by_schema or {}
        self.calls: list[dict] = []

    def complete(self, **kwargs):
        self.calls.append(kwargs)
        parsed = self.by_schema.get(kwargs.get("schema"), self.parsed)
        return LLMResult(parsed=parsed, model=self.model)


class FakeIntake:
    def __init__(self, text: str):
        self.text = text

    def probe_file(self, path):
        return FileProbe(
            path=str(path),
            filename=Path(path).name,
            extension=".pdf",
            size_bytes=len(self.text),
            kind=FileKind.pdf,
            page_count=1,
        )

    def extract_text(self, path, probe=None):
        return [ExtractedText(page=0, text=self.text)]


def _mapping_draft(**mapping):
    return StatementMappingDraft(
        mapping=StatementMapping(**mapping),
        confidence=0.9,
    )


def test_csv_mapping_is_applied_deterministically(tmp_path: Path):
    path = tmp_path / "banco.csv"
    path.write_text(
        "Fecha;Importe;Concepto;Moneda\n"
        "01/02/2026;-12,34;Supermercado;EUR\n"
        "02/02/2026;50,00;Nomina;EUR\n",
        encoding="utf-8",
    )
    client = FakeClient(
        _mapping_draft(
            date_column="Fecha",
            amount_column="Importe",
            description_column="Concepto",
            currency_column="Moneda",
            date_format="dd/mm/yyyy",
            decimal_separator=",",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    assert len(result.events) == 2
    assert result.events[0]["value_date"] == date(2026, 2, 1)
    assert result.events[0]["amount"] == Decimal("-12.34")
    assert result.events[0]["kind"] == "gasto"
    assert result.events[1]["amount"] == Decimal("50.00")
    assert result.events[1]["kind"] == "ingreso"
    assert result.period_start == date(2026, 2, 1)
    assert result.period_end == date(2026, 2, 2)
    assert client.calls[0]["schema"] is StatementMappingDraft


def test_csv_header_aliases_complete_a_sparse_mapping(tmp_path: Path):
    path = tmp_path / "banco.csv"
    path.write_text(
        "date,amount,description,currency\n"
        "2026-03-01,-9.99,Cafe,EUR\n",
        encoding="utf-8",
    )
    client = FakeClient(
        _mapping_draft(
            date_column="date",
            amount_column="amount",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    event = result.events[0]
    assert event["description_clean"] == "Cafe"
    assert event["currency"] == "EUR"


def test_csv_asset_delivery_without_amount_becomes_aporte(tmp_path: Path):
    path = tmp_path / "activos.csv"
    path.write_text(
        "date,type,symbol,shares,price,amount,description\n"
        "2026-04-01,FREE_RECEIPT,SOL,0.5,100.00,,Entrega Solana\n",
        encoding="utf-8",
    )
    client = FakeClient(
        _mapping_draft(
            date_column="date",
            amount_column="amount",
            description_column="description",
            kind_column="type",
            asset_symbol_column="symbol",
            shares_column="shares",
            price_column="price",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    event = result.events[0]
    assert event["kind"] == "aporte_activo"
    assert event["amount"] is None
    assert event["asset_symbol"] == "SOL"
    assert event["shares"] == Decimal("0.5")
    assert event["price"] == Decimal("100.00")


def test_xlsx_sheet_is_normalized(tmp_path: Path):
    path = tmp_path / "banco.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Movimientos"
    sheet.append(["Fecha", "Importe", "Concepto", "Saldo"])
    sheet.append(["01/02/2026", -12.34, "Supermercado", 100.00])
    sheet.append(["02/02/2026", 50.00, "Nomina", 150.00])
    workbook.save(path)

    client = FakeClient(
        _mapping_draft(
            date_column="Fecha",
            amount_column="Importe",
            description_column="Concepto",
            balance_column="Saldo",
            date_format="dd/mm/yyyy",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    assert len(result.events) == 2
    assert result.events[0]["amount"] == Decimal("-12.34")
    assert result.events[1]["kind"] == "ingreso"
    assert result.metadata["format"] == "xlsx"
    assert result.metadata["reconciliation"]["ok"] is True
    assert result.events[0]["_sheet"] == "Movimientos"


def test_csv_running_balance_marks_mismatch(tmp_path: Path):
    path = tmp_path / "descuadre.csv"
    path.write_text(
        "date,amount,description,balance\n"
        "2026-02-01,-10.00,Cafe,90.00\n"
        "2026-02-02,-5.00,Pan,80.00\n",
        encoding="utf-8",
    )
    client = FakeClient(
        _mapping_draft(
            date_column="date",
            amount_column="amount",
            description_column="description",
            balance_column="balance",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    assert result.metadata["reconciliation"]["ok"] is False
    assert any("no concilia" in issue for issue in result.issues)



def test_csv_detects_header_after_preamble_when_agent_mapping_is_stale(tmp_path: Path):
    path = tmp_path / "banco.csv"
    path.write_text(
        "Extracto;Banco\n"
        "Fecha;Importe;Concepto\n"
        "01/02/2026;-12,34;Supermercado\n",
        encoding="utf-8",
    )
    client = FakeClient(
        _mapping_draft(
            header_row=0,
            date_column="date",
            amount_column="amount",
            description_column="description",
            date_format="dd/mm/yyyy",
            sign_convention="signed",
        )
    )
    with AgenticStatementExtractor(client=client) as extractor:
        result = extractor.extract(path)

    assert len(result.events) == 1
    assert result.events[0]["value_date"] == date(2026, 2, 1)
    assert result.events[0]["amount"] == Decimal("-12.34")
    assert result.metadata["mapping"]["header_row"] == 1

class MultiPageIntake:
    def __init__(self, pages: list[str]):
        self.pages = pages

    def probe_file(self, path):
        return FileProbe(
            path=str(path),
            filename=Path(path).name,
            extension=".pdf",
            size_bytes=sum(len(page) for page in self.pages),
            kind=FileKind.pdf,
            page_count=len(self.pages),
        )

    def extract_text(self, path, probe=None):
        return [
            ExtractedText(page=index, text=text)
            for index, text in enumerate(self.pages)
        ]


def test_pdf_sections_propagate_currency_and_skip_non_importable_pages():
    pages = [
        "Extracto en EUR\nRevolut Bank\nTransacciones de la cuenta\n1 ene 2026 Compra -10,00",
        "Extracto en KRW\nTransacciones de la cuenta\n1 ene 2026 Compra -1000 KRW",
        "Revertidas entre el 1 de enero y el 2 de noviembre\nCompra 10,00",
        "Extracto en EUR\nTransacciones de Pockets personales\nRetirada 5,00",
    ]
    page_row = PdfRow(
        value_date="2026-01-01",
        amount="-10.00",
        description="Compra",
        raw_text="Compra",
    )
    client = FakeClient(by_schema={
        PdfPageDraft: PdfPageDraft(rows=[page_row]),
        PdfSummaryDraft: PdfSummaryDraft(currency="EUR"),
    })
    with AgenticStatementExtractor(
        client=client, intake=MultiPageIntake(pages)
    ) as extractor:
        result = extractor.extract("fake.pdf")

    assert [event["currency"] for event in result.events] == ["EUR", "KRW"]
    sections = result.metadata["sections"]
    assert [section["status"] for section in sections] == [
        "main", "main", "reversed", "secondary_product"
    ]
    assert len(result.metadata["ignored_sections"]) == 2


def test_pdf_more_than_thirty_pages_is_supported():
    pages = [
        f"Trade Republic\nPágina {index}\n1 ene 2026 Compra -1,00"
        for index in range(50)
    ]
    client = FakeClient(by_schema={
        PdfPageDraft: PdfPageDraft(rows=[PdfRow(
            value_date="2026-01-01",
            amount="-1.00",
            description="Compra",
            raw_text="Compra",
        )]),
        PdfSummaryDraft: PdfSummaryDraft(),
    })
    # El mismo schema devuelve una fila por página; basta para verificar que el
    # límite ya no bloquea el PDF de Trade Republic.
    with AgenticStatementExtractor(
        client=client, intake=MultiPageIntake(pages)
    ) as extractor:
        result = extractor.extract("fake.pdf")
    assert len(result.events) == 50
    assert result.metadata["pages"] == 50


def test_pdf_summary_uses_main_account_not_global_total():
    text = (
        "Extracto en EUR\n"
        "Cuenta (Cuenta Corriente) 64,61 € 34.292,83 € 34.228,22 € 0,00 €\n"
        "Pockets personales y grupales 1.251,52 € 1.251,52 € 0,00 € 0,00 €\n"
        "Total 1.316,13 € 36.044,46 € 34.728,33 € 0,00 €"
    )
    summary = _summary_from_text([ExtractedText(page=0, text=text)])
    assert summary is not None
    assert summary.opening_balance == "64.61"
    assert summary.closing_balance == "0.00"
    assert summary.currency == "EUR"


def test_pdf_page_rows_are_normalized_with_evidence():
    client = FakeClient(
        by_schema={
            PdfPageDraft: PdfPageDraft(
                rows=[
                    PdfRow(
                        value_date="2025-12-01",
                        amount="-7.95",
                        description="Waylet",
                        raw_text="30 nov 2025 1 dic 2025 Waylet €7.95",
                    )
                ]
            ),
            PdfSummaryDraft: PdfSummaryDraft(),
        }
    )
    intake = FakeIntake("30 nov 2025 1 dic 2025 Waylet €7.95")
    with AgenticStatementExtractor(client=client, intake=intake) as extractor:
        result = extractor.extract("fake.pdf")

    assert len(result.events) == 1
    assert result.events[0]["amount"] == Decimal("-7.95")
    assert result.events[0]["kind"] == "gasto"
    assert result.raw_rows[0]["page"] == 0
    assert "Waylet" in result.raw_rows[0]["raw_text"]
