"""
Registry: maps the catalogue's `scrape_class` enum value to a Scraper subclass.

This is the dispatch point. CLI calls registry.get(source_row['scrape_class']),
constructs the scraper with the source row, and calls scraper.ingest(url).
"""
from __future__ import annotations
from typing import Type

from ..core.scraper_base import Scraper
from .static_scraper import StaticScraper
from .dynamic_scraper import DynamicScraper
from .bulk_scraper import BulkScraper

# Catalogue scrape_class values that route to a real scraper class.
# Other values ('manual_download', 'tile_raster', 'api_json', 'pdf_document',
# 'rss_atom') are handled either by the same StaticScraper or by source-specific
# code in bastion/sources/.
_REGISTRY: dict[str, Type[Scraper]] = {
    "static_html": StaticScraper,
    "dynamic_js": DynamicScraper,
    "bulk_crawl": BulkScraper,
    # Routed to StaticScraper unless overridden per-source:
    "pdf_document": StaticScraper,
    "api_json": StaticScraper,
    "rss_atom": StaticScraper,
    "tile_raster": BulkScraper,    # tiles can be big; stream them
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
