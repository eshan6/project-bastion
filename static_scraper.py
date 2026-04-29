"""
StaticScraper — for HTML/PDF/JSON pages that render server-side.

Used by: BRO project pages, Wikipedia, IISS/Globalsecurity/FAS,
IMD daily bulletin PDFs, CAG/Lok Sabha/Rajya Sabha PDF endpoints,
most government static pages.

- httpx; HTTP/2 opt-in via BASTION_HTTP2=1 (needs h2 package).
- Retries on 429/5xx with exponential backoff (tenacity).
- Custom UA per source.
- robots.txt is intentionally ignored (project policy).
"""
from __future__ import annotations
import logging
import os

import httpx
import structlog
from tenacity import (
    retry, stop_after_attempt, wait_exponential_jitter,
    retry_if_exception_type, before_sleep_log,
)

from ..core.scraper_base import Scraper, FetchResult
from ..core.config import get_config

log = structlog.get_logger(__name__)
_RETRY_LOG = logging.getLogger("bastion.retry")

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class _RetryableHTTPError(Exception):
    """Raised on 429/5xx so tenacity retries. Other HTTP errors do not retry."""


class StaticScraper(Scraper):
    SCRAPE_CLASS = "static_html"

    def _fetch_one(self, url: str) -> FetchResult:
        cfg = get_config()
        use_http2 = os.getenv("BASTION_HTTP2", "0") == "1"
        client = httpx.Client(
            http2=use_http2,
            follow_redirects=True,
            timeout=cfg.default_timeout,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "*/*",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        try:
            return self._fetch_with_retry(client, url)
        finally:
            client.close()

    @retry(
        retry=retry_if_exception_type((_RetryableHTTPError, httpx.TransportError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(initial=2, max=30),
        before_sleep=before_sleep_log(_RETRY_LOG, logging.WARNING),
        reraise=False,
    )
    def _fetch_with_retry(self, client: httpx.Client, url: str) -> FetchResult:
        try:
            r = client.get(url)
        except httpx.TimeoutException as e:
            return FetchResult(url=url, error_kind="timeout", error_detail=str(e))
        except httpx.TransportError:
            raise
        except Exception as e:
            return FetchResult(url=url, error_kind="parse_error",
                               error_detail=f"{type(e).__name__}: {e}")

        if r.status_code in _RETRYABLE_STATUSES:
            raise _RetryableHTTPError(f"status {r.status_code}")

        if r.status_code >= 400:
            return FetchResult(
                url=url, http_status=r.status_code,
                error_kind="blocked" if r.status_code in (401, 403, 451) else "http_error",
                error_detail=f"HTTP {r.status_code}",
            )

        return FetchResult(
            url=url, content=r.content, http_status=r.status_code,
            content_type=r.headers.get("content-type"),
            response_headers={k.lower(): v for k, v in r.headers.items()},
        )
