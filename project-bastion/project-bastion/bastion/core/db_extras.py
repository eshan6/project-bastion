"""
DB helpers for extractors. Kept separate from db.py to avoid cluttering
the scraper-side code with extractor-only concerns.

Idempotency strategy for claims:
- A claim is uniquely identified by (extractor_name, extractor_version,
  claim_type, payload_hash). Two extractor runs against the same artifact
  produce identical claim_ids (deterministic UUID5).
- evidence_links are inserted with ON CONFLICT DO NOTHING so re-running an
  extractor against the same artifact never duplicates.
"""
from __future__ import annotations
import hashlib
import json
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .config import get_config


# A fixed namespace UUID for deterministic claim_id generation.
# Using uuid5 means: same extractor + version + claim_type + payload always
# produces the same claim_id. Re-running the extractor is a no-op.
_CLAIM_NS = uuid.UUID("a1b2c3d4-0001-4000-8000-ba571055cd01")


def _conn():
    cfg = get_config()
    return psycopg.connect(cfg.db_dsn)


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    """Stable JSON serialization for hashing — sort keys, no whitespace."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _claim_id(extractor_name: str, extractor_version: str, claim_type: str, payload: dict) -> uuid.UUID:
    """Deterministic claim_id so re-runs are idempotent."""
    key = f"{extractor_name}|{extractor_version}|{claim_type}|{_stable_payload_hash(payload)}"
    return uuid.uuid5(_CLAIM_NS, key)


def fetch_artifact_with_source(artifact_id: str) -> dict[str, Any] | None:
    """Load an artifact joined with its source row."""
    sql = """
    SELECT
        ra.artifact_id::text AS artifact_id,
        ra.source_id,
        ra.fetched_url,
        ra.fetched_at,
        ra.content_type,
        ra.blob_path,
        ra.size_bytes,
        s.name        AS source_name,
        s.category::text AS category,
        s.realism_tier::text AS realism_tier
    FROM bastion_provenance.raw_artifacts ra
    JOIN bastion_provenance.sources s ON s.source_id = ra.source_id
    WHERE ra.artifact_id = %s::uuid;
    """
    with _conn() as c:
        cur = c.execute(sql, (artifact_id,))
        row = cur.fetchone()
        if row is None:
            return None
        cols = [d.name for d in cur.description]
        return dict(zip(cols, row))


def insert_claim_with_evidence(
    claim_type: str,
    payload: dict[str, Any],
    confidence: float,
    valid_from: str | None,
    valid_to: str | None,
    extractor_name: str,
    extractor_version: str,
    artifact_id: str,
    locator: dict[str, Any],
) -> bool:
    """
    Idempotent insert of one claim + its evidence_link to the source artifact.
    Returns True if a new claim was written, False if it already existed.
    """
    cid = _claim_id(extractor_name, extractor_version, claim_type, payload)

    with _conn() as c:
        # Insert claim — ON CONFLICT means re-run produces no new row.
        existing = c.execute(
            "SELECT 1 FROM bastion_provenance.claims WHERE claim_id = %s",
            (str(cid),),
        ).fetchone()

        is_new = existing is None
        if is_new:
            c.execute(
                """
                INSERT INTO bastion_provenance.claims
                    (claim_id, claim_type, claim_payload, extractor_version,
                     confidence, valid_from, valid_to)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s);
                """,
                (
                    str(cid), claim_type, Jsonb(payload),
                    f"{extractor_name}@{extractor_version}",
                    confidence, valid_from, valid_to,
                ),
            )

        # Always link evidence (ON CONFLICT keeps idempotent).
        c.execute(
            """
            INSERT INTO bastion_provenance.evidence_links
                (claim_id, artifact_id, relation, locator)
            VALUES (%s::uuid, %s::uuid, 'supports', %s)
            ON CONFLICT (claim_id, artifact_id, relation) DO NOTHING;
            """,
            (str(cid), artifact_id, Jsonb(locator)),
        )
        c.commit()
        return is_new
