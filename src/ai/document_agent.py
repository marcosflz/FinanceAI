"""Agente documental: probe y herramientas deterministas.

Este módulo implementa la parte local del agente:

- ``FileProbe``: MIME, extensión, magic bytes, tamaño, páginas y cifrado.
- Allowlist de herramientas (sin shell, sin red, sin llamadas a APIs).
- ``extract_text``/``extract_tables`` para texto/CSV y, si está instalado
  ``pdfplumber``, para PDFs con capa de texto.
- ``reconcile_balance`` con ``Decimal`` y tolerancia de 0,01.
- Validaciones del ``DocumentEnvelope`` (evidencia, cuenta, periodo, saldo).

La interpretación semántica y las llamadas a OpenCode Go viven en
``src/ingest/agentic.py``. OCR, visión multimodal y render de páginas quedan
como ``Protocol`` inyectables para la fase D.
"""

from __future__ import annotations

import csv
import io
import mimetypes
import re
import time
import zipfile
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from .schemas import (
    Balances,
    DocumentEnvelope,
    DocumentIssue,
    DocumentType,
    DocumentUnit,
    EnvelopeConfidence,
    TraceStep,
)

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_PAGES = 200
BALANCE_TOLERANCE = Decimal("0.01")


class AgentTool(str, Enum):
    """Allowlist de herramientas del agente; el modelo no las invoca."""

    probe_file = "probe_file"
    extract_text = "extract_text"
    extract_tables = "extract_tables"
    render_page = "render_page"
    reconcile_balance = "reconcile_balance"
    finish_envelope = "finish_envelope"


TOOL_ALLOWLIST = frozenset(tool.value for tool in AgentTool)


class FileKind(str, Enum):
    csv = "csv"
    pdf = "pdf"
    image = "image"
    xlsx = "xlsx"
    ofx = "ofx"
    qif = "qif"
    text = "text"
    unknown = "unknown"


class FileProbe(BaseModel):
    """Resultado determinista de inspeccionar un fichero."""

    model_config = ConfigDict(extra="ignore")

    path: str
    filename: str
    extension: str
    mime_type: str | None = None
    size_bytes: int
    magic_hex: str = ""
    kind: FileKind = FileKind.unknown
    page_count: int | None = None
    encrypted: bool | None = None
    warnings: list[str] = Field(default_factory=list)


class ExtractedText(BaseModel):
    """Texto nativo de una página (o del fichero completo si no hay páginas)."""

    page: int | None = None
    text: str = ""


class ExtractedTable(BaseModel):
    """Tabla extraída de una página, con celdas como texto."""

    page: int | None = None
    rows: list[list[str]] = Field(default_factory=list)
    bbox: list[float] | None = None


class ReconciliationResult(BaseModel):
    """Conciliación entre la suma de importes y el delta de saldo."""

    opening: Decimal | None = None
    closing: Decimal | None = None
    expected_delta: Decimal = Decimal("0")
    actual_delta: Decimal = Decimal("0")
    difference: Decimal = Decimal("0")
    tolerance: Decimal = BALANCE_TOLERANCE
    currency: str = "EUR"
    ok: bool = False


class PageRenderer(Protocol):
    """Renderer de páginas a PNG (se inyectará en F4)."""

    def render(self, path: str | Path, page: int, *, dpi: int = 150) -> bytes:
        ...


class OcrEngine(Protocol):
    """Motor OCR opcional para escaneados/recibos (se inyectará en F4)."""

    def extract_text(self, path: str | Path, page: int | None = None) -> str:
        ...


# ---------------------------------------------------------------------------
# FileProbe
# ---------------------------------------------------------------------------


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _detect_zip_kind(path: Path, extension: str) -> FileKind:
    if extension in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return FileKind.xlsx
    try:
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError):
        return FileKind.unknown
    if any(name.startswith("xl/") for name in names):
        return FileKind.xlsx
    return FileKind.unknown


def _detect_kind(path: Path, head: bytes, extension: str) -> FileKind:
    if head.startswith(b"%PDF-"):
        return FileKind.pdf
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return FileKind.image
    if head.startswith(b"\xff\xd8\xff"):
        return FileKind.image
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return FileKind.image
    if head.startswith(b"II*\x00") or head.startswith(b"MM\x00*"):
        return FileKind.image
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return FileKind.image
    if head.startswith(b"PK\x03\x04"):
        return _detect_zip_kind(path, extension)

    if extension == ".pdf":
        return FileKind.pdf
    if extension in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"}:
        return FileKind.image
    if extension in {".xlsx", ".xlsm", ".xltx", ".xltm"}:
        return FileKind.xlsx

    if extension in {".csv", ".tsv"}:
        return FileKind.csv
    if extension in {".ofx", ".qfx"}:
        return FileKind.ofx
    if extension == ".qif":
        return FileKind.qif
    if extension in {".txt", ".text", ".md"}:
        return FileKind.text

    text_head = _decode_text(head)
    upper_head = text_head.upper()
    if "OFXHEADER" in upper_head[:500] or "<OFX>" in upper_head[:5000]:
        return FileKind.ofx
    if text_head.lstrip().upper().startswith("!TYPE:"):
        return FileKind.qif

    first_line = next((line for line in text_head.splitlines() if line.strip()), "")
    if first_line and any(delimiter in first_line for delimiter in (",", ";", "\t", "|")):
        return FileKind.csv
    if text_head.strip():
        return FileKind.text
    return FileKind.unknown


def _probe_pdf_details(data: bytes) -> tuple[int | None, bool]:
    page_count = len(re.findall(rb"/Type\s*/Page\b", data))
    encrypted = b"/Encrypt" in data
    return (page_count or None), encrypted


def probe_file(path: str | Path) -> FileProbe:
    """Inspecciona un fichero sin ejecutar código ni llamar a la red."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(str(file_path))
    if not file_path.is_file():
        raise IsADirectoryError(str(file_path))

    size = file_path.stat().st_size
    with file_path.open("rb") as handle:
        head = handle.read(8192)
    extension = file_path.suffix.lower()
    kind = _detect_kind(file_path, head, extension)
    mime_type, _ = mimetypes.guess_type(file_path.name)

    page_count: int | None = None
    encrypted: bool | None = None
    warnings: list[str] = []

    if kind is FileKind.pdf:
        if size <= 20 * 1024 * 1024:
            page_count, encrypted = _probe_pdf_details(file_path.read_bytes())
        else:
            warnings.append("PDF grande: no se cuentan páginas en el probe")
    if size == 0:
        warnings.append("fichero vacío")
    if kind is FileKind.unknown:
        warnings.append("tipo de fichero no reconocido")

    return FileProbe(
        path=str(file_path),
        filename=file_path.name,
        extension=extension,
        mime_type=mime_type,
        size_bytes=size,
        magic_hex=head[:8].hex(),
        kind=kind,
        page_count=page_count,
        encrypted=encrypted,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Conciliación
# ---------------------------------------------------------------------------


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def reconcile_balance(
    opening: Decimal | str | float | None,
    closing: Decimal | str | float | None,
    amounts: Iterable[Decimal | str | float | None],
    *,
    tolerance: Decimal | str | float = BALANCE_TOLERANCE,
    currency: str = "EUR",
) -> ReconciliationResult:
    """Comprueba ``Σ importes == saldo_final - saldo_inicial``.

    Los importes deben venir con signo (el criterio del proyecto: el signo de
    ``amount`` es la única verdad direccional).
    """
    opening_decimal = _to_decimal(opening)
    closing_decimal = _to_decimal(closing)
    tolerance_decimal = _to_decimal(tolerance) or BALANCE_TOLERANCE
    total = sum(
        (parsed for value in amounts if (parsed := _to_decimal(value)) is not None),
        Decimal("0"),
    )

    if opening_decimal is None or closing_decimal is None:
        return ReconciliationResult(
            opening=opening_decimal,
            closing=closing_decimal,
            expected_delta=total,
            actual_delta=Decimal("0"),
            difference=total,
            tolerance=tolerance_decimal,
            currency=currency,
            ok=False,
        )

    actual_delta = closing_decimal - opening_decimal
    difference = total - actual_delta
    return ReconciliationResult(
        opening=opening_decimal,
        closing=closing_decimal,
        expected_delta=total,
        actual_delta=actual_delta,
        difference=difference,
        tolerance=tolerance_decimal,
        currency=currency,
        ok=abs(difference) <= tolerance_decimal,
    )


# ---------------------------------------------------------------------------
# Validaciones del envelope
# ---------------------------------------------------------------------------


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "warning",
    evidence_id: str | None = None,
) -> DocumentIssue:
    return DocumentIssue(
        code=code,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        evidence_id=evidence_id,
    )


def validate_envelope(
    envelope: DocumentEnvelope,
    *,
    balance_tolerance: Decimal = BALANCE_TOLERANCE,
) -> list[DocumentIssue]:
    """Validaciones deterministas; nunca auto-aprueba un documento dudoso."""
    issues: list[DocumentIssue] = []

    if envelope.document_type is DocumentType.unknown:
        issues.append(
            _issue(
                "DOCUMENT_TYPE_UNKNOWN",
                "No se ha identificado el tipo de documento",
                severity="error",
            )
        )
    if not envelope.bank:
        issues.append(
            _issue("BANK_NOT_DETECTED", "No se ha detectado el banco", severity="warning")
        )
    if (
        envelope.account is None
        or (not envelope.account.iban_masked and not envelope.account.name)
    ):
        issues.append(
            _issue(
                "ACCOUNT_NOT_IDENTIFIED",
                "No se ha identificado la cuenta/IBAN del documento",
                severity="error",
            )
        )
    if envelope.period and envelope.period.start and envelope.period.end:
        if envelope.period.start > envelope.period.end:
            issues.append(
                _issue(
                    "PERIOD_INVALID",
                    "El periodo termina antes de empezar",
                    severity="error",
                )
            )

    seen_texts: set[tuple[int | None, str]] = set()
    transaction_units: list[DocumentUnit] = []
    for index, unit in enumerate(envelope.units):
        has_evidence = bool(
            unit.page is not None
            or unit.bbox
            or (unit.raw_text or "").strip()
            or unit.evidence_id
        )
        if not has_evidence:
            issues.append(
                _issue(
                    "MISSING_EVIDENCE",
                    f"La unidad {index} no tiene page/bbox/raw_text/evidence_id",
                    severity="error",
                )
            )
        if unit.kind == "transaction":
            transaction_units.append(unit)
        if unit.raw_text:
            key = (unit.page, unit.raw_text.strip())
            if key in seen_texts:
                issues.append(
                    _issue(
                        "DUPLICATE_UNIT",
                        f"La unidad {index} repite el texto de otra unidad",
                        severity="warning",
                        evidence_id=unit.evidence_id,
                    )
                )
            seen_texts.add(key)

    balances: Balances | None = envelope.balances
    if balances and balances.opening is not None and balances.closing is not None:
        if transaction_units and all(
            "amount" in unit.fields for unit in transaction_units
        ):
            amounts = [unit.fields.get("amount") for unit in transaction_units]
            reconciliation = reconcile_balance(
                balances.opening,
                balances.closing,
                amounts,
                tolerance=balance_tolerance,
                currency=balances.currency,
            )
            if not reconciliation.ok:
                issues.append(
                    _issue(
                        "BALANCE_MISMATCH",
                        "La suma de importes no cuadra con el delta de saldo: "
                        f"diferencia {reconciliation.difference}",
                        severity="error",
                    )
                )

    if envelope.confidence.overall < 0.80:
        issues.append(
            _issue(
                "LOW_CONFIDENCE",
                f"Confianza global {envelope.confidence.overall:.2f} < 0.80",
                severity="warning",
            )
        )

    return issues


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


class DocumentIntakeAgent:
    """Orquestador determinista con allowlist de herramientas.

    No llama a OpenCode Go ni a Jev. El modelo multimodal se usará en F4 para
    páginas ambiguas, pero siempre devolverá JSON validado y el orquestador
    seguirá decidiendo qué herramienta ejecutar.
    """

    def __init__(
        self,
        *,
        renderer: PageRenderer | None = None,
        ocr: OcrEngine | None = None,
        max_file_bytes: int = MAX_FILE_BYTES,
        max_pages: int = MAX_PAGES,
    ) -> None:
        self.renderer = renderer
        self.ocr = ocr
        self.max_file_bytes = max_file_bytes
        self.max_pages = max_pages

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(sorted(TOOL_ALLOWLIST))

    # -- tools ------------------------------------------------------------

    def probe_file(self, path: str | Path) -> FileProbe:
        return probe_file(path)

    def extract_text(
        self,
        path: str | Path,
        probe: FileProbe | None = None,
    ) -> list[ExtractedText]:
        """Texto nativo; PDF requiere ``pdfplumber`` y OCR una implementación."""
        file_probe = probe or self.probe_file(path)

        if file_probe.kind in {
            FileKind.csv,
            FileKind.text,
            FileKind.ofx,
            FileKind.qif,
        }:
            data = Path(path).read_bytes()
            return [ExtractedText(page=None, text=_decode_text(data))]

        if file_probe.kind is FileKind.pdf:
            try:
                import pdfplumber  # type: ignore[import-not-found]
            except ImportError as exc:
                raise NotImplementedError(
                    "La extracción de texto de PDF requiere 'pdfplumber'. "
                    "Instálalo o inyecta un extractor en F4."
                ) from exc
            pages: list[ExtractedText] = []
            with pdfplumber.open(str(path)) as pdf:
                if len(pdf.pages) > self.max_pages:
                    raise ValueError(
                        f"PDF con {len(pdf.pages)} páginas > {self.max_pages}"
                    )
                for index, page in enumerate(pdf.pages):
                    pages.append(
                        ExtractedText(page=index, text=page.extract_text() or "")
                    )
            return pages

        if file_probe.kind is FileKind.image:
            if self.ocr is None:
                raise NotImplementedError(
                    "OCR no configurado: inyecta un OcrEngine para imágenes/escaneos"
                )
            return [
                ExtractedText(page=None, text=self.ocr.extract_text(path))
            ]

        if file_probe.kind is FileKind.xlsx:
            raise NotImplementedError(
                "La lectura de XLSX se implementará en el adaptador de F4"
            )

        raise ValueError(f"tipo de fichero no soportado: {file_probe.kind.value}")

    def extract_tables(
        self,
        path: str | Path,
        probe: FileProbe | None = None,
    ) -> list[ExtractedTable]:
        """Tablas deterministas para CSV; PDF/XLSX quedan para F4."""
        file_probe = probe or self.probe_file(path)

        if file_probe.kind in {FileKind.csv, FileKind.text}:
            text = self.extract_text(path, file_probe)[0].text
            sample = text[:8192]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = csv.excel
            rows = [
                [cell.strip() for cell in row]
                for row in csv.reader(io.StringIO(text), dialect)
            ]
            return [ExtractedTable(page=None, rows=rows)]

        if file_probe.kind is FileKind.pdf:
            try:
                import pdfplumber  # type: ignore[import-not-found]
            except ImportError as exc:
                raise NotImplementedError(
                    "La extracción de tablas de PDF requiere 'pdfplumber'"
                ) from exc
            tables: list[ExtractedTable] = []
            with pdfplumber.open(str(path)) as pdf:
                if len(pdf.pages) > self.max_pages:
                    raise ValueError(
                        f"PDF con {len(pdf.pages)} páginas > {self.max_pages}"
                    )
                for index, page in enumerate(pdf.pages):
                    for table in page.extract_tables() or []:
                        tables.append(
                            ExtractedTable(
                                page=index,
                                rows=[
                                    ["" if cell is None else str(cell) for cell in row]
                                    for row in table
                                ],
                                bbox=list(page.bbox) if page.bbox else None,
                            )
                        )
            return tables

        if file_probe.kind is FileKind.xlsx:
            raise NotImplementedError(
                "La lectura de tablas XLSX se implementará en F4"
            )

        raise ValueError(f"tipo de fichero no soportado: {file_probe.kind.value}")

    def render_page(
        self,
        path: str | Path,
        page: int,
        *,
        dpi: int = 150,
    ) -> bytes:
        """Renderiza una página a PNG si hay un renderer inyectado."""
        if self.renderer is None:
            raise NotImplementedError(
                "Render de páginas no configurado: inyecta un PageRenderer "
                "(pdf2image/pymupdf) en F4"
            )
        return self.renderer.render(path, page, dpi=dpi)

    def reconcile_balance(
        self,
        opening: Decimal | str | float | None,
        closing: Decimal | str | float | None,
        amounts: Iterable[Decimal | str | float | None],
        *,
        tolerance: Decimal | str | float = BALANCE_TOLERANCE,
        currency: str = "EUR",
    ) -> ReconciliationResult:
        return reconcile_balance(
            opening, closing, amounts, tolerance=tolerance, currency=currency
        )

    def finish_envelope(self, envelope: DocumentEnvelope) -> DocumentEnvelope:
        """Añade validaciones, deduplica incidencias y fija ``needs_review``."""
        issues = list(envelope.issues)
        issues.extend(validate_envelope(envelope))

        merged: list[DocumentIssue] = []
        seen: set[tuple[str, str, str | None]] = set()
        for issue in issues:
            key = (issue.code, issue.message, issue.evidence_id)
            if key in seen:
                continue
            seen.add(key)
            merged.append(issue)

        has_error = any(issue.severity == "error" for issue in merged)
        low_confidence = envelope.confidence.overall < 0.80
        needs_review = bool(envelope.needs_review or has_error or low_confidence)

        return envelope.model_copy(
            update={"issues": merged, "needs_review": needs_review}
        )

    # -- orquestación determinista ---------------------------------------

    def run(
        self,
        path: str | Path,
        *,
        document_type_hint: str | None = None,
    ) -> DocumentEnvelope:
        """Probe + texto/tablas + validaciones. Sin APIs reales.

        El resultado siempre queda en ``needs_review`` en este esqueleto: todavía
        no hay adaptador semántico que convierta ``raw_text`` en movimientos.
        """
        trace: list[TraceStep] = []
        started = time.perf_counter()
        probe = self.probe_file(path)
        trace.append(
            TraceStep(
                step="probe_file",
                ms=round((time.perf_counter() - started) * 1000.0, 3),
                detail=f"kind={probe.kind.value} size={probe.size_bytes}",
            )
        )

        issues: list[DocumentIssue] = []
        units: list[DocumentUnit] = []
        extraction_confidence = 0.0

        if probe.size_bytes > self.max_file_bytes:
            issues.append(
                _issue(
                    "FILE_TOO_LARGE",
                    f"Fichero de {probe.size_bytes} bytes > {self.max_file_bytes}",
                    severity="error",
                )
            )
        else:
            extract_started = time.perf_counter()
            try:
                pages = self.extract_text(path, probe)
            except NotImplementedError as exc:
                issues.append(
                    _issue(
                        "EXTRACTOR_UNAVAILABLE",
                        str(exc),
                        severity="error",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - se reporta como issue
                issues.append(
                    _issue(
                        "EXTRACTION_FAILED",
                        f"{type(exc).__name__}: {exc}",
                        severity="error",
                    )
                )
            else:
                for extracted in pages[: self.max_pages]:
                    units.append(
                        DocumentUnit(
                            kind="raw_text",
                            page=extracted.page,
                            raw_text=extracted.text[:20000] or None,
                            fields={},
                            confidence=0.50,
                        )
                    )
                extraction_confidence = 0.50 if units else 0.0
                issues.append(
                    _issue(
                        "EXTRACTION_INCOMPLETE",
                        "Esqueleto determinista: falta interpretar los campos de "
                        "texto en unidades de negocio",
                        severity="warning",
                    )
                )
            trace.append(
                TraceStep(
                    step="extract_text",
                    ms=round((time.perf_counter() - extract_started) * 1000.0, 3),
                    detail=f"units={len(units)}",
                )
            )

        envelope = DocumentEnvelope(
            document_type=(
                document_type_hint
                if document_type_hint is not None
                else self._document_type_for(probe)
            ),
            bank=None,
            account=None,
            period=None,
            balances=None,
            units=units,
            candidates=[],
            issues=issues,
            confidence=EnvelopeConfidence(
                overall=extraction_confidence,
                extraction=extraction_confidence,
                account=0.0,
            ),
            trace=trace,
            needs_review=True,
            source_file=probe.filename,
        )
        finished = self.finish_envelope(envelope)
        return finished

    @staticmethod
    def _document_type_for(probe: FileProbe) -> DocumentType:
        if probe.kind in {FileKind.csv, FileKind.pdf, FileKind.ofx, FileKind.qif}:
            return DocumentType.bank_statement
        return DocumentType.unknown


__all__ = [
    "AgentTool",
    "DocumentIntakeAgent",
    "ExtractedTable",
    "ExtractedText",
    "FileKind",
    "FileProbe",
    "MAX_FILE_BYTES",
    "MAX_PAGES",
    "OcrEngine",
    "PageRenderer",
    "ReconciliationResult",
    "TOOL_ALLOWLIST",
    "probe_file",
    "reconcile_balance",
    "validate_envelope",
]
