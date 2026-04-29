"""
Base Extractor class.

The contract:
- Subclasses implement _extract(artifact_bytes, content_type, source_row)
  -> Iterable[ExtractedClaim].
- The base class handles: claim insert, evidence_link insert, idempotency,
  extractor versioning, fetch_log-equivalent for extraction.

This mirrors the Scraper pattern: provenance writing is structurally
inescapable, not developer discipline.

Why this matters: every claim downstream (a stockout risk, a route closure
prediction) must be traceable back to the artifact and source it came from.
That lineage is the single biggest credibility differentiator in the demo.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

import psycopg
import structlog

from . import db_extras

log = structlog.get_logger(__name__)


@dataclass
class ExtractedClaim:
    """One atomic fact extracted from an artifact."""
    claim_type: str                            # e.g. 'imd_weather_obs', 'orbat_unit_location'
    payload: dict[str, Any]                    # the actual extracted JSON
    confidence: float = 1.0                    # 0.0 - 1.0
    valid_from: str | None = None              # ISO date
    valid_to: str | None = None                # ISO date
    locator: dict[str, Any] = field(default_factory=dict)
                                               # page_no, bbox, xpath, char_offset...


class Extractor(ABC):
    """Abstract base for all extractor classes (PDF, HTML, JSON, etc.)."""

    EXTRACTOR_NAME: str = ""        # subclasses set, e.g. 'pdf:imd_bulletin'
    EXTRACTOR_VERSION: str = "0.1.0"

    @abstractmethod
    def _extract(
        self,
        artifact_bytes: bytes,
        content_type: str | None,
        source_row: dict[str, Any],
        artifact_meta: dict[str, Any],
    ) -> Iterable[ExtractedClaim]:
        """Concrete extraction logic. Subclasses implement this only."""
        ...

    # ----- public API — do not override --------------------------------

    def extract(self, artifact_id: str) -> int:
        """
        Load an artifact, run extraction, write claim + evidence_link rows.
        Returns count of claims written.
        Idempotent: if the same (artifact_id, extractor_name, extractor_version,
        claim_type, payload-hash) already exists, the claim is skipped.
        """
        artifact = db_extras.fetch_artifact_with_source(artifact_id)
        if artifact is None:
            raise ValueError(f"artifact_id not found: {artifact_id}")

        from .blob import read_blob
        content = read_blob(artifact["blob_path"])

        source_row = {
            "source_id": artifact["source_id"],
            "name": artifact["source_name"],
            "category": artifact["category"],
            "realism_tier": artifact["realism_tier"],
        }
        artifact_meta = {
            "artifact_id": artifact["artifact_id"],
            "fetched_url": artifact["fetched_url"],
            "fetched_at": artifact["fetched_at"],
        }

        n_written = 0
        for claim in self._extract(content, artifact["content_type"], source_row, artifact_meta):
            inserted = db_extras.insert_claim_with_evidence(
                claim_type=claim.claim_type,
                payload=claim.payload,
                confidence=claim.confidence,
                valid_from=claim.valid_from,
                valid_to=claim.valid_to,
                extractor_name=self.EXTRACTOR_NAME,
                extractor_version=self.EXTRACTOR_VERSION,
                artifact_id=artifact_id,
                locator=claim.locator,
            )
            if inserted:
                n_written += 1

        log.info(
            "extract_done",
            artifact_id=artifact_id,
            extractor=self.EXTRACTOR_NAME,
            version=self.EXTRACTOR_VERSION,
            claims_written=n_written,
        )
        return n_written
