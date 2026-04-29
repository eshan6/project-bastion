"""
PDF extraction.

Two-stage strategy:
1. pdfplumber for text-based PDFs (most government PDFs from 2015+ are text).
2. OCR (pytesseract via pdf2image) fallback for scanned PDFs.

Detection: if pdfplumber yields < 100 chars across the whole document,
we treat it as scanned and route to OCR.

This is a base class with reusable utilities. Concrete IMD/CAG/etc.
extractors subclass this and override _claims_from_pages().
"""
from __future__ import annotations
import io
import re
from abc import abstractmethod
from dataclasses import dataclass
from typing import Iterable, Iterator

import structlog

from ..core.extractor_base import Extractor, ExtractedClaim

log = structlog.get_logger(__name__)

# Optional imports — keep heavy deps soft so the package imports without them.
_PDFPLUMBER_ERR: Exception | None = None
_PYTESSERACT_ERR: Exception | None = None
try:
    import pdfplumber
except ImportError as e:
    _PDFPLUMBER_ERR = e
try:
    import pytesseract
    from pdf2image import convert_from_bytes
except ImportError as e:
    _PYTESSERACT_ERR = e


@dataclass
class PdfPage:
    """One extracted page."""
    page_no: int                    # 1-indexed
    text: str
    method: str                     # 'pdfplumber' | 'ocr'
    bbox_words: list[dict] | None = None
                                    # pdfplumber: [{'text','x0','x1','top','bottom'}, ...]


class PdfExtractor(Extractor):
    """Base class for PDF extractors. Subclass and override _claims_from_pages."""

    EXTRACTOR_NAME = "pdf:base"

    # Threshold for scanned-PDF detection
    _MIN_TEXT_FOR_TEXT_PDF = 100

    def _extract(self, artifact_bytes, content_type, source_row, artifact_meta):
        if _PDFPLUMBER_ERR is not None:
            raise RuntimeError(f"pdfplumber not available: {_PDFPLUMBER_ERR}")

        pages = list(self._read_text_pages(artifact_bytes))
        total_chars = sum(len(p.text) for p in pages)
        if total_chars < self._MIN_TEXT_FOR_TEXT_PDF:
            if _PYTESSERACT_ERR is not None:
                log.warning(
                    "pdf_likely_scanned_no_ocr",
                    artifact_id=artifact_meta["artifact_id"],
                    text_chars=total_chars,
                    err=str(_PYTESSERACT_ERR),
                )
                return
            log.info(
                "pdf_falling_back_to_ocr",
                artifact_id=artifact_meta["artifact_id"], text_chars=total_chars,
            )
            pages = list(self._ocr_pages(artifact_bytes))

        yield from self._claims_from_pages(pages, source_row, artifact_meta)

    # ----- helpers used by subclasses ----------------------------------

    def _read_text_pages(self, pdf_bytes: bytes) -> Iterator[PdfPage]:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for i, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                # pdfplumber word boxes — useful for locator construction.
                try:
                    words = page.extract_words(use_text_flow=True)
                except Exception:
                    words = None
                yield PdfPage(page_no=i, text=text, method="pdfplumber", bbox_words=words)

    def _ocr_pages(self, pdf_bytes: bytes) -> Iterator[PdfPage]:
        # Render each page to image then OCR. Slow but reliable for scans.
        images = convert_from_bytes(pdf_bytes, dpi=200)
        for i, img in enumerate(images, start=1):
            text = pytesseract.image_to_string(img)
            yield PdfPage(page_no=i, text=text, method="ocr", bbox_words=None)

    # ----- subclasses override this ------------------------------------

    @abstractmethod
    def _claims_from_pages(
        self,
        pages: list[PdfPage],
        source_row: dict,
        artifact_meta: dict,
    ) -> Iterable[ExtractedClaim]:
        ...


# ---- text-utility helpers used by concrete extractors -------------------

# Numbers + units: "12.5 mm", "-15.3 °C", "32.5°C", "120 km"
_NUM_UNIT = re.compile(
    r"(?P<num>-?\d+(?:\.\d+)?)\s*(?P<unit>°?[CFcf]|mm|cm|m|km|kt|kmph|km/h)",
    re.IGNORECASE,
)


def find_num_unit(text: str) -> list[tuple[float, str]]:
    """Pull (number, unit) tuples from arbitrary text."""
    out = []
    for m in _NUM_UNIT.finditer(text):
        try:
            out.append((float(m.group("num")), m.group("unit").lower()))
        except ValueError:
            continue
    return out
