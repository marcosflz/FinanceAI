"""OCR local para imágenes y PDFs escaneados.

El OCR solo convierte píxeles en texto. La interpretación sigue siendo del
extractor agéntico (DeepSeek V4.1 Flash por defecto): nunca se usa un modelo de
visión como primario.
"""

from __future__ import annotations

import os
from pathlib import Path

from .document_agent import ExtractedText


class OcrUnavailable(RuntimeError):
    """No hay motor OCR disponible en el entorno."""


class TesseractOcr:
    """Motor OCR basado en Tesseract + pypdfium2.

    Requiere el binario ``tesseract`` y el paquete de idioma español
    (``tesseract-ocr-spa``). En la imagen Docker se instalan ambos.
    """

    name = "tesseract"

    def __init__(
        self,
        *,
        lang: str | None = None,
        dpi: int | None = None,
        timeout: int = 90,
    ) -> None:
        self.lang = lang or os.getenv("OCR_LANG", "spa+eng")
        self.dpi = dpi or int(os.getenv("OCR_DPI", "250"))
        self.timeout = timeout

    def _pytesseract(self):
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise OcrUnavailable(
                "pytesseract no está instalado; instala las dependencias de OCR"
            ) from exc
        return pytesseract

    def _image_to_text(self, image) -> str:
        from PIL import ImageOps

        pytesseract = self._pytesseract()
        prepared = ImageOps.autocontrast(image.convert("L"))
        try:
            return pytesseract.image_to_string(
                prepared,
                lang=self.lang,
                config="--psm 6",
                timeout=self.timeout,
            )
        except pytesseract.TesseractNotFoundError as exc:  # pragma: no cover
            raise OcrUnavailable(
                "El binario 'tesseract' no está instalado en el sistema"
            ) from exc
        except RuntimeError as exc:  # timeout de pytesseract
            raise OcrUnavailable(f"OCR agotó el tiempo: {exc}") from exc

    def extract_text(self, path: str | Path, page: int | None = None) -> str:
        """OCR de una imagen suelta."""
        from PIL import Image, ImageOps

        image = Image.open(path)
        try:
            image = ImageOps.exif_transpose(image)
        except Exception:
            pass
        return self._image_to_text(image).strip()

    def extract_pdf_pages(self, path: str | Path) -> list[ExtractedText]:
        """Renderiza y aplica OCR a cada página de un PDF escaneado."""
        try:
            import pypdfium2 as pdfium
        except ImportError as exc:  # pragma: no cover
            raise OcrUnavailable(
                "pypdfium2 no está instalado; no se puede renderizar el PDF"
            ) from exc

        document = pdfium.PdfDocument(str(path))
        pages: list[ExtractedText] = []
        try:
            for index in range(len(document)):
                page_obj = document[index]
                bitmap = page_obj.render(scale=self.dpi / 72)
                image = bitmap.to_pil()
                pages.append(
                    ExtractedText(page=index, text=self._image_to_text(image).strip())
                )
        finally:
            document.close()
        return pages


__all__ = ["OcrUnavailable", "TesseractOcr"]
