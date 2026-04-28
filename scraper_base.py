"""
Base Scraper class.

The contract:
- Subclasses implement _fetch_one(url, source_row) -> FetchResult.
- Everything else (rate limit, sha256, dedupe, blob write, raw_artifacts
  insert, fetch_log row, source state update) happens in this base class
  and CANNOT be skipped or overridden by subclasses.

This is the Lighthouse-pattern principle: provenance is not optional,
not an afterthought, not something a developer can forget. It is
structurally inescapable.
"""
from __future__ import annotations
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import structlog

from . import db, blob
from .ratelimit import LIMITER

log = structlog.get_logger(__name__)


@dataclass
class FetchResult:
    """Output of a single fetch attempt by a subclass."""
    url: str
    content: bytes | None = None              # None means failure
    http_status: int | None = None
    content_type: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    error_kind: str | None = None             # 'http_error', 'timeout', 'blocked', 'parse_error'
    error_detail: str | None = None


@dataclass
class IngestOutcome:
    """What happened end-to-end for one URL."""
    url: str
    outcome: str                               # 'success', 'http_error', 'timeout', 'blocked', 'parse_error', 'skipped_dup'
    artifact_id: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None


class Scraper(ABC):
    """
    Abstract base for all scraper classes.
    Subclasses: StaticScraper, DynamicScraper, BulkScraper.
    """

    # subclasses set this so the catalogue's scrape_class can be matched
    SCRAPE_CLASS: str = ""

    def __init__(self, source_row: dict[str, Any]) -> None:
        self.source = source_row
        self.source_id: str = source_row["source_id"]
        self.rate_limit_seconds: float = float(source_row.get("rate_limit_seconds") or 3.0)
        self.user_agent: str = source_row.get("user_agent") or "BastionResearchBot/0.1"

    # ----- subclass surface ---------------------------------------------

    @abstractmethod
    def _fetch_one(self, url: str) -> FetchResult:
        """Concrete fetch logic. Subclasses implement this only."""
        ...

    # ----- public API — do not override ---------------------------------

    def ingest(self, url: str) -> IngestOutcome:
        """
        Fetch a single URL and write all provenance rows.
        This is the only entry point external callers should use.
        """
        # 1. Rate limit (per source)
        wait_ms = int(LIMITER.wait(self.source_id, self.rate_limit_seconds) * 1000)

        # 2. Fetch (subclass)
        t0 = time.monotonic()
        try:
            result = self._fetch_one(url)
        except Exception as e:
            result = FetchResult(
                url=url,
                error_kind="parse_error",
                error_detail=f"{type(e).__name__}: {e}",
            )
        duration_ms = int((time.monotonic() - t0) * 1000)

        # 3. Failure path — log and bail
        if result.content is None:
            outcome = result.error_kind or "http_error"
            db.write_fetch_log(
                source_id=self.source_id,
                target_url=url,
                outcome=outcome,
                http_status=result.http_status,
                error_detail=result.error_detail,
            )
            db.update_source_state(self.source_id, success=False)
            log.warning(
                "fetch_failed",
                source_id=self.source_id, url=url,
                outcome=outcome, status=result.http_status,
                detail=result.error_detail,
            )
            return IngestOutcome(url=url, outcome=outcome, duration_ms=duration_ms)

        # 4. Success path: blob + artifact row
        blob_path, sha256, size = blob.write_blob(
            self.source_id, result.content, result.content_type,
        )
        artifact_id = db.insert_artifact(
            source_id=self.source_id,
            fetched_url=url,
            http_status=result.http_status,
            content_type=result.content_type,
            content_sha256=sha256,
            blob_path=blob_path,
            size_bytes=size,
            response_headers=dict(result.response_headers),
            fetch_duration_ms=duration_ms,
        )

        if artifact_id is None:
            # Idempotent re-fetch: same content as before.
            db.write_fetch_log(
                source_id=self.source_id,
                target_url=url,
                outcome="skipped_dup",
                http_status=result.http_status,
            )
            db.update_source_state(self.source_id, success=True)
            log.info(
                "fetch_dedup",
                source_id=self.source_id, url=url, sha256=sha256[:12],
                wait_ms=wait_ms, fetch_ms=duration_ms,
            )
            return IngestOutcome(
                url=url, outcome="skipped_dup",
                sha256=sha256, size_bytes=size, duration_ms=duration_ms,
            )

        db.write_fetch_log(
            source_id=self.source_id,
            target_url=url,
            outcome="success",
            http_status=result.http_status,
            artifact_id=artifact_id,
        )
        db.update_source_state(self.source_id, success=True)
        log.info(
            "fetch_ok",
            source_id=self.source_id, url=url, sha256=sha256[:12],
            size=size, wait_ms=wait_ms, fetch_ms=duration_ms,
            artifact_id=artifact_id,
        )
        return IngestOutcome(
            url=url, outcome="success", artifact_id=artifact_id,
            sha256=sha256, size_bytes=size, duration_ms=duration_ms,
        )
