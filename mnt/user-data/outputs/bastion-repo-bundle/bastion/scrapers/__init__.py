"""
Registry: maps catalogue's scrape_class enum value to a Scraper subclass.

Other catalogue scrape_class values (manual_download) are handled either by
StaticScraper or by source-specific code.
"""
from __future__ import annotations
from typing import Type

from ..core.scraper_base import Scraper
from .static_scraper import StaticScraper
from .dynamic_scraper import DynamicScraper
from .bulk_scraper import BulkScraper

_REGISTRY: dict[str, Type[Scraper]] = {
    "static_html": StaticScraper,
    "dynamic_js": DynamicScraper,
    "bulk_crawl": BulkScraper,
    "pdf_document": StaticScraper,
    "api_json": StaticScraper,
    "rss_atom": StaticScraper,
    "tile_raster": BulkScraper,
}


def get_scraper_class(scrape_class: str) -> Type[Scraper]:
    if scrape_class not in _REGISTRY:
        raise ValueError(
            f"No scraper registered for scrape_class={scrape_class!r}. "
            f"Known: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[scrape_class]


__all__ = [
    "Scraper", "StaticScraper", "DynamicScraper", "BulkScraper",
    "get_scraper_class",
]
