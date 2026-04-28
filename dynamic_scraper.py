"""
DynamicScraper — Playwright headless Chromium for JS-rendered pages.

Used by:
- BRO press releases (JS-rendered list)
- Bhuvan WMS viewer endpoints
- Some news archive search endpoints

Properties:
- Single shared browser context per scraper instance (fast for multi-URL)
- Waits for networkidle (most reliable for content-loaded-by-fetch sites)
- Captures the FULL rendered HTML (post-JS) as the artifact
- Falls back to printed status if page returned an HTTP error

Operational note:
- Playwright needs `playwright install chromium` once after pip install.
- On a fresh laptop: ~150MB browser download. One time.
"""
from __future__ import annotations
import structlog

from ..core.scraper_base import Scraper, FetchResult
from ..core.config import get_config

log = structlog.get_logger(__name__)

# Optional import — Playwright is heavy. We delay import until use
# so that the package can be inspected without it installed.
_PW_IMPORT_ERROR: Exception | None = None
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError as e:
    _PW_IMPORT_ERROR = e


class DynamicScraper(Scraper):
    SCRAPE_CLASS = "dynamic_js"

    def _fetch_one(self, url: str) -> FetchResult:
        if _PW_IMPORT_ERROR is not None:
            return FetchResult(
                url=url, error_kind="parse_error",
                error_detail=f"playwright not installed: {_PW_IMPORT_ERROR}",
            )

        cfg = get_config()
        timeout_ms = int(cfg.default_timeout * 1000)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(user_agent=self.user_agent)
            page = context.new_page()
            try:
                resp = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                status = resp.status if resp else None
                if status and status >= 400:
                    return FetchResult(
                        url=url, http_status=status,
                        error_kind="blocked" if status in (401, 403, 451) else "http_error",
                        error_detail=f"HTTP {status}",
                    )
                html = page.content().encode("utf-8")
                return FetchResult(
                    url=url, content=html, http_status=status,
                    content_type="text/html; charset=utf-8",
                    response_headers={k.lower(): v for k, v in (resp.headers if resp else {}).items()},
                )
            except PWTimeout as e:
                return FetchResult(url=url, error_kind="timeout", error_detail=str(e))
            except Exception as e:
                return FetchResult(
                    url=url, error_kind="parse_error",
                    error_detail=f"{type(e).__name__}: {e}",
                )
            finally:
                context.close()
                browser.close()
