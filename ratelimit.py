"""
Per-source rate limiter.

Each source carries its own rate_limit_seconds (min interval between
requests to that source). The limiter is process-local for now;
multi-process safe variant goes to Redis later if needed.

Why per-source not per-domain:
- Several sources share a domain (PIB, MoD subpages on mod.gov.in).
- We want explicit, auditable throttling — not implicit.
"""
from __future__ import annotations
import threading
import time
from collections import defaultdict


class RateLimiter:
    """In-process per-source minimum-interval limiter."""

    def __init__(self) -> None:
        self._last_call: dict[str, float] = defaultdict(lambda: 0.0)
        self._locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
        self._global_lock = threading.Lock()

    def _lock_for(self, source_id: str) -> threading.Lock:
        with self._global_lock:
            return self._locks[source_id]

    def wait(self, source_id: str, min_interval_seconds: float) -> float:
        """
        Block until the source is permitted to fire again.
        Returns the actual wait duration (for telemetry).
        """
        lock = self._lock_for(source_id)
        with lock:
            now = time.monotonic()
            elapsed = now - self._last_call[source_id]
            if elapsed < min_interval_seconds:
                sleep_for = min_interval_seconds - elapsed
                time.sleep(sleep_for)
                self._last_call[source_id] = time.monotonic()
                return sleep_for
            self._last_call[source_id] = now
            return 0.0


# Module-level singleton — most callers want this.
LIMITER = RateLimiter()
