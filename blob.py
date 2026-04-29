"""
Blob storage for raw artifacts.

Content-addressed: blob_path is derived from sha256, so two fetches that
produce identical bytes share one file on disk.

Layout:
    {BLOB_ROOT}/{source_id}/{sha256[0:2]}/{sha256[2:4]}/{sha256}.{ext}

Phase 1 is laptop-local. Add nightly rsync to an external drive. Migrate
to S3-compatible (Cloudflare R2 free tier or MinIO) when pilot demands it.
"""
from __future__ import annotations
import hashlib
import mimetypes
from pathlib import Path

from .config import get_config


_EXT_OVERRIDES = {
    "text/html": ".html",
    "application/xhtml+xml": ".html",
    "application/pdf": ".pdf",
    "application/json": ".json",
    "application/geo+json": ".geojson",
    "application/xml": ".xml",
    "text/xml": ".xml",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "application/octet-stream": ".bin",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _ext_for(content_type: str | None) -> str:
    if not content_type:
        return ".bin"
    base = content_type.split(";", 1)[0].strip().lower()
    if base in _EXT_OVERRIDES:
        return _EXT_OVERRIDES[base]
    guess = mimetypes.guess_extension(base)
    return guess or ".bin"


def write_blob(source_id: str, content: bytes, content_type: str | None) -> tuple[str, str, int]:
    """
    Write content to the blob store.
    Returns (blob_path_relative, sha256_hex, size_bytes).
    Idempotent: if the blob already exists at the destination, no rewrite.
    """
    cfg = get_config()
    digest = sha256_bytes(content)
    ext = _ext_for(content_type)
    rel = Path(source_id) / digest[0:2] / digest[2:4] / f"{digest}{ext}"
    abs_path = cfg.blob_root / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    if not abs_path.exists():
        abs_path.write_bytes(content)
    return str(rel), digest, len(content)


def read_blob(blob_path: str) -> bytes:
    """Read a blob by its relative path."""
    cfg = get_config()
    return (cfg.blob_root / blob_path).read_bytes()
