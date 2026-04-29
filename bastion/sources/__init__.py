"""Per-source modules — one file per source_id with the parsing logic."""
from .imd_daily_bulletin import ImdDailyBulletinExtractor
from .wikipedia_orbat import WikipediaOrbatExtractor

__all__ = ["ImdDailyBulletinExtractor", "WikipediaOrbatExtractor"]


# Registry: source_id -> Extractor class.
# Used by the CLI/orchestrator to pick the right extractor for an artifact.
EXTRACTOR_BY_SOURCE = {
    "imd_daily_bulletin": ImdDailyBulletinExtractor,
    "wikipedia_indianarmy": WikipediaOrbatExtractor,
    # Add as we wire more sources.
}
