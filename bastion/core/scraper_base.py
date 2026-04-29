"""
Base Scraper class.

Subclasses implement _fetch_one(url) -> FetchResult. Everything else
(rate limit, sha256, dedupe, blob write, raw_artifacts insert,
fetch_log row, source state update) happens in this base class and
CANNOT be skipped.

Provenance is structurally inescapable, not developer discipline.
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
    """Output of a single fetch attempt."""
    url: str
    content: bytes | None = None
    http_status: int | None = None
    content_type: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    error_kind: str | None = None
    error_detail: str | None = None


@dataclass
class IngestOutcome:
    """End-to-end outcome for one URL."""
    url: str
    outcome: str
    artifact_id: str | None = None
    sha256: str | None = None
    size_bytes: int | None = None
    duration_ms: int | None = None


class Scraper(ABC):
    SCRAPE_CLASS: str = ""

    def __init__(self, source_row: dict[str, Any]) -> None:
        self.source = source_row
        self.source_id: str = source_row["source_id"]
        self.rate_limit_seconds: float = float(source_row.get("rate_limit_seconds") or 3.0)
        self.user_agent: str = source_row.get("user_agent") or "BastionResearchBot/0.1"

    @abstractmethod
    def _fetch_one(self, url: str) -> FetchResult:
        ...

    def ingest(self, url: str) -> IngestOutcome:
        wait_ms = int(LIMITER.wait(self.source_id, self.rate_limit_seconds) * 1000)

        t0 = time.monotonic()
        try:
            result = self._fetch_one(url)
        except Exception as e:
            result = FetchResult(
                url=url, error_kind="parse_error",
                error_detail=f"{type(e).__name__}: {e}",
            )
        duration_ms = int((time.monotonic() - t0) * 1000)

        if result.content is None:
            outcome = result.error_kind or "http_error"
            db.write_fetch_log(
                source_id=self.source_id, target_url=url, outcome=outcome,
                http_status=result.http_status, error_detail=result.error_detail,
            )
            db.update_source_state(self.source_id, success=False)
            log.warning(
                "fetch_failed", source_id=self.source_id, url=url,
                outcome=outcome, status=result.http_status, detail=result.error_detail,
            )
            return IngestOutcome(url=url, outcome=outcome, duration_ms=duration_ms)

        blob_path, sha256, size = blob.write_blob(
            self.source_id, result.content, result.content_type,
        )
        artifact_id = db.insert_artifact(
            source_id=self.source_id, fetched_url=url,
            http_status=result.http_status, content_type=result.content_type,
            content_sha256=sha256, blob_path=blob_path, size_bytes=size,
            response_headers=dict(result.response_headers),
            fetch_duration_ms=duration_ms,
        )

        if artifact_id is None:
            db.write_fetch_log(
                source_id=self.source_id, target_url=url, outcome="skipped_dup",
                http_status=result.http_status,
            )
            db.update_source_state(self.source_id, success=True)
            log.info(
                "fetch_dedup", source_id=self.source_id, url=url,
                sha256=sha256[:12], wait_ms=wait_ms, fetch_ms=duration_ms,
            )
            return IngestOutcome(
                url=url, outcome="skipped_dup", sha256=sha256,
                size_bytes=size, duration_ms=duration_ms,
            )

        db.write_fetch_log(
            source_id=self.source_id, target_url=url, outcome="success",
            http_status=result.http_status, artifact_id=artifact_id,
        )
        db.update_source_state(self.source_id, success=True)
        log.info(
            "fetch_ok", source_id=self.source_id, url=url, sha256=sha256[:12],
            size=size, wait_ms=wait_ms, fetch_ms=duration_ms, artifact_id=artifact_id,
        )
        return IngestOutcome(
            url=url, outcome="success", artifact_id=artifact_id,
            sha256=sha256, size_bytes=size, duration_ms=duration_ms,
        )
