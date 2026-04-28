"""
BulkScraper — for large files and crawl-depth scenarios.

Two regimes:
1. Single large file (Geofabrik PBF, Sentinel-2 tile): stream-download
   to a temp file, then hand bytes to the base class.
2. Multi-page crawl (news archive 2010-2025): not implemented as a
   single scraper. Instead, the source module emits a list of URLs,
   the base class is called per URL via StaticScraper, and the rate
   limiter throttles. We don't need scrapy's framework for what we do.

Decision: the original plan called for scrapy. After working the design,
scrapy is overkill — its scheduler/middleware machinery duplicates what
our base Scraper + RateLimiter already do. So BulkScraper is just a
streaming variant of StaticScraper, sized for large payloads.
"""
from __future__ import annotations
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from ..core.scraper_base import Scraper, FetchResult
from ..core.config import get_config

log = structlog.get_logger(__name__)

# 256 MB hard ceiling per artifact. Above this, we're either misusing the
# tool or the source needs a manual-download workflow.
_MAX_BYTES = 256 * 1024 * 1024


class BulkScraper(Scraper):
    SCRAPE_CLASS = "bulk_crawl"

    def _fetch_one(self, url: str) -> FetchResult:
        cfg = get_config()
        try:
            return self._stream_download(url, cfg.default_timeout * 4)  # longer timeout for big files
        except httpx.TimeoutException as e:
            return FetchResult(url=url, error_kind="timeout", error_detail=str(e))
        except Exception as e:
            return FetchResult(
                url=url, error_kind="parse_error",
                error_detail=f"{type(e).__name__}: {e}",
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=5, max=60), reraise=True)
    def _stream_download(self, url: str, timeout: float) -> FetchResult:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
        }
        chunks: list[bytes] = []
        total = 0
        with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=True) as r:
            if r.status_code >= 400:
                return FetchResult(
                    url=url, http_status=r.status_code,
                    error_kind="blocked" if r.status_code in (401, 403, 451) else "http_error",
                    error_detail=f"HTTP {r.status_code}",
                )
            for chunk in r.iter_bytes(chunk_size=1 << 20):  # 1 MiB
                chunks.append(chunk)
                total += len(chunk)
                if total > _MAX_BYTES:
                    return FetchResult(
                        url=url, http_status=r.status_code,
                        error_kind="parse_error",
                        error_detail=f"exceeded {_MAX_BYTES} bytes; switch to manual_download",
                    )
            return FetchResult(
                url=url,
                content=b"".join(chunks),
                http_status=r.status_code,
                content_type=r.headers.get("content-type"),
                response_headers={k.lower(): v for k, v in r.headers.items()},
            )
