"""Bastion core: db, blob, rate-limit, base scraper, base extractor."""
from .scraper_base import Scraper, FetchResult, IngestOutcome
from .extractor_base import Extractor, ExtractedClaim
from .config import get_config

__all__ = [
    "Scraper", "FetchResult", "IngestOutcome",
    "Extractor", "ExtractedClaim",
    "get_config",
]
