"""
Database access layer (scraper side).

Uses psycopg3 in sync mode. All writes to bastion_provenance happen
inside transactions. raw_artifacts insert is idempotent on
(source_id, content_sha256). fetch_log writes are append-only.
"""
from __future__ import annotations
import contextlib
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import get_config


@contextlib.contextmanager
def conn() -> Iterator[psycopg.Connection]:
    """Yield a Postgres connection with dict rows. Caller controls txn scope."""
    cfg = get_config()
    with psycopg.connect(cfg.db_dsn, row_factory=dict_row) as c:
        yield c


def fetch_source(source_id: str) -> dict[str, Any] | None:
    """Load a source row by source_id."""
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM bastion_provenance.sources WHERE source_id = %s",
            (source_id,),
        )
        return cur.fetchone()


def fetch_artifact(artifact_id: str) -> dict[str, Any] | None:
    """Load a raw_artifacts row by id."""
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM bastion_provenance.raw_artifacts WHERE artifact_id = %s::uuid",
            (artifact_id,),
        )
        return cur.fetchone()


def list_due_sources(limit: int = 50) -> list[dict[str, Any]]:
    """Pull the crawl queue view."""
    with conn() as c:
        cur = c.execute(
            "SELECT * FROM bastion_provenance.v_crawl_queue LIMIT %s",
            (limit,),
        )
        return cur.fetchall()


def insert_artifact(
    source_id: str,
    fetched_url: str,
    http_status: int | None,
    content_type: str | None,
    content_sha256: str,
    blob_path: str,
    size_bytes: int,
    response_headers: dict | None,
    fetch_duration_ms: int,
) -> str | None:
    """
    Insert raw_artifacts idempotently.
    Returns artifact_id (UUID str) on insert, or None if duplicate.
    """
    sql = """
    INSERT INTO bastion_provenance.raw_artifacts
        (source_id, fetched_url, http_status, content_type, content_sha256,
         blob_path, size_bytes, response_headers, fetch_duration_ms)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (source_id, content_sha256) DO NOTHING
    RETURNING artifact_id::text;
    """
    with conn() as c:
        cur = c.execute(sql, (
            source_id, fetched_url, http_status, content_type, content_sha256,
            blob_path, size_bytes, Jsonb(response_headers or {}), fetch_duration_ms,
        ))
        row = cur.fetchone()
        c.commit()
        return row["artifact_id"] if row else None


def write_fetch_log(
    source_id: str,
    target_url: str,
    outcome: str,
    http_status: int | None = None,
    error_detail: str | None = None,
    artifact_id: str | None = None,
) -> None:
    """Append a fetch_log row.
    Outcomes: success | http_error | timeout | blocked | parse_error | skipped_dup."""
    sql = """
    INSERT INTO bastion_provenance.fetch_log
        (source_id, target_url, outcome, http_status, error_detail, artifact_id)
    VALUES (%s, %s, %s, %s, %s, %s);
    """
    with conn() as c:
        c.execute(sql, (source_id, target_url, outcome, http_status, error_detail, artifact_id))
        c.commit()


def update_source_state(source_id: str, success: bool) -> None:
    """Update last_attempt_at and (on success) last_success_at + reset failures."""
    if success:
        sql = """
        UPDATE bastion_provenance.sources
        SET last_attempt_at = NOW(),
            last_success_at = NOW(),
            consecutive_failures = 0
        WHERE source_id = %s;
        """
    else:
        sql = """
        UPDATE bastion_provenance.sources
        SET last_attempt_at = NOW(),
            consecutive_failures = consecutive_failures + 1
        WHERE source_id = %s;
        """
    with conn() as c:
        c.execute(sql, (source_id,))
        c.commit()
