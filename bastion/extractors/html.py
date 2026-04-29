"""
HTML extraction.

Strategy:
- Use BeautifulSoup with lxml backend for structural parsing.
- For news-archive pages, use a readability-style algorithm (article body
  detection by tag density) to strip nav/footer/sidebar.
- Capture xpath of the extracted block in locator for the provenance UI
  to highlight on re-render.

Subclasses (e.g. WikipediaOrbatExtractor) implement _claims_from_soup().
"""
from __future__ import annotations
from abc import abstractmethod
from typing import Iterable

import structlog
from bs4 import BeautifulSoup

from ..core.extractor_base import Extractor, ExtractedClaim

log = structlog.get_logger(__name__)


class HtmlExtractor(Extractor):
    """Base class for HTML extractors."""

    EXTRACTOR_NAME = "html:base"

    def _extract(self, artifact_bytes, content_type, source_row, artifact_meta):
        # Decode best-effort: most Indian gov pages are utf-8; fall back to latin-1
        try:
            html_text = artifact_bytes.decode("utf-8")
        except UnicodeDecodeError:
            html_text = artifact_bytes.decode("latin-1", errors="replace")

        soup = BeautifulSoup(html_text, "lxml")
        # Strip script/style — they wreck text extraction
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        yield from self._claims_from_soup(soup, source_row, artifact_meta)

    @abstractmethod
    def _claims_from_soup(
        self,
        soup: BeautifulSoup,
        source_row: dict,
        artifact_meta: dict,
    ) -> Iterable[ExtractedClaim]:
        ...
