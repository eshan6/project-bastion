"""
Wednesday e2e test: scraper pipeline.

Stands up embedded Postgres, applies schema + catalogue, then exercises:
1. StaticScraper success path (PyPI JSON metadata — deterministic content)
2. Dedupe path (re-fetch identical URL → skipped_dup, no second artifact)
3. Failure path (404 → http_error + consecutive_failures++)
4. raw_artifacts, fetch_log, sources state are all written correctly

Run from repo root:
    python tests/wednesday_e2e_test.py
"""
from __future__ import annotations
import os
import re
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg
from psycopg.rows import dict_row

# Repo-relative imports — works from any clone
REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "bastion" / "sql"
sys.path.insert(0, str(REPO_ROOT))

print("=" * 72)
print("WEDNESDAY E2E TEST — Bastion scraper pipeline")
print("=" * 72)

work = tempfile.mkdtemp(prefix="bastion_wed_")
blob_root = Path(work) / "blobs"
blob_root.mkdir()

print("\n[1/7] starting embedded postgres...")
srv = pgserver.get_server(str(Path(work) / "pg"), cleanup_mode="stop")
dsn = srv.get_uri()
print(f"      dsn: {dsn}")

os.environ["BASTION_DB_DSN"] = dsn
os.environ["BASTION_BLOB_ROOT"] = str(blob_root)
os.environ["BASTION_DEFAULT_TIMEOUT"] = "20"

# Reset config singleton (in case earlier tests in same proc set it)
from bastion.core.config import reset_config_for_tests
reset_config_for_tests()

print("\n[2/7] applying schema (PostGIS-skipped for embedded)...")
schema_sql = (SQL_DIR / "01_sources_schema.sql").read_text()
catalogue_p1 = (SQL_DIR / "02_sources_catalogue.sql").read_text()
catalogue_p2 = (SQL_DIR / "03_sources_catalogue_part2_and_views.sql").read_text()

# Embedded build lacks postgis/pg_trgm/uuid-ossp; substitute gen_random_uuid
schema_sql = re.sub(r"CREATE EXTENSION IF NOT EXISTS postgis;", "-- skipped postgis", schema_sql)
schema_sql = re.sub(r"CREATE EXTENSION IF NOT EXISTS pg_trgm;.*?\n", "-- skipped pg_trgm\n", schema_sql)
schema_sql = re.sub(r'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";', "-- skipped uuid-ossp", schema_sql)
schema_sql = schema_sql.replace("uuid_generate_v4()", "gen_random_uuid()")

with psycopg.connect(dsn) as c:
    with c.cursor() as cur:
        cur.execute(schema_sql)
        cur.execute(catalogue_p1)
        cur.execute(catalogue_p2)
    c.commit()

with psycopg.connect(dsn, row_factory=dict_row) as c:
    n = c.execute("SELECT COUNT(*) AS n FROM bastion_provenance.sources").fetchone()["n"]
print(f"      {n} sources loaded")
assert n == 112, f"expected 112 sources, got {n}"

print("\n[3/7] verifying operational views...")
with psycopg.connect(dsn, row_factory=dict_row) as c:
    counts = c.execute("SELECT * FROM bastion_provenance.v_source_counts ORDER BY category").fetchall()
    for row in counts:
        print(f"      {row['category']:<22} total={row['total_sources']:>3}  P1-2={row['demo_critical']:>3}")

    queue = c.execute("SELECT source_id, priority FROM bastion_provenance.v_crawl_queue LIMIT 5").fetchall()
    print(f"      crawl queue top-5: {[r['source_id'] for r in queue]}")

# ------- StaticScraper success ---------------------------------------

print("\n[4/7] StaticScraper test...")
TEST_URL = "https://pypi.org/pypi/requests/json"

with psycopg.connect(dsn) as c:
    c.execute("""
        INSERT INTO bastion_provenance.sources
        (source_id, name, category, realism_tier, scrape_class, refresh_cadence,
         legal_posture, base_url, seed_urls, rate_limit_seconds, priority)
        VALUES
        ('test_static_pypi', 'Test (pypi.org)', 'geo_infra', 'tier_4_osint',
         'static_html', 'on_event', 'public_domain',
         'https://pypi.org', ARRAY['https://pypi.org/pypi/requests/json'], 0.5, 1)
        ON CONFLICT (source_id) DO UPDATE SET name = EXCLUDED.name;
    """)
    c.commit()

from bastion.core import db as bdb
from bastion.scrapers import StaticScraper

src = bdb.fetch_source("test_static_pypi")
scraper = StaticScraper(src)
outcome = scraper.ingest(TEST_URL)
print(f"      outcome: {outcome.outcome}, sha256={outcome.sha256[:12] if outcome.sha256 else None}, size={outcome.size_bytes}")
assert outcome.outcome == "success", f"expected success, got {outcome.outcome}"
assert outcome.size_bytes and outcome.size_bytes > 100

with psycopg.connect(dsn, row_factory=dict_row) as c:
    arts = c.execute("SELECT * FROM bastion_provenance.raw_artifacts WHERE source_id='test_static_pypi'").fetchall()
    logs = c.execute("SELECT * FROM bastion_provenance.fetch_log WHERE source_id='test_static_pypi'").fetchall()
    src_after = c.execute("SELECT last_attempt_at, last_success_at, consecutive_failures FROM bastion_provenance.sources WHERE source_id='test_static_pypi'").fetchone()

print(f"      raw_artifacts: {len(arts)} rows")
print(f"      fetch_log:     {len(logs)} rows ({[l['outcome'] for l in logs]})")
print(f"      sources state: last_success_at={src_after['last_success_at']}, fails={src_after['consecutive_failures']}")
assert len(arts) == 1
assert logs[0]["outcome"] == "success"
assert src_after["last_success_at"] is not None
assert src_after["consecutive_failures"] == 0

blob_file = blob_root / arts[0]["blob_path"]
assert blob_file.exists(), f"blob missing at {blob_file}"
print(f"      blob on disk:  {blob_file.relative_to(blob_root)} ({blob_file.stat().st_size} B)")

# ------- Dedupe -------------------------------------------------------

print("\n[5/7] dedupe test (re-fetch same URL)...")
outcome2 = scraper.ingest(TEST_URL)
print(f"      outcome: {outcome2.outcome}, sha256={outcome2.sha256[:12] if outcome2.sha256 else None}")
assert outcome2.outcome == "skipped_dup", f"expected skipped_dup, got {outcome2.outcome}"

with psycopg.connect(dsn, row_factory=dict_row) as c:
    arts2 = c.execute("SELECT COUNT(*) AS n FROM bastion_provenance.raw_artifacts WHERE source_id='test_static_pypi'").fetchone()["n"]
    logs2 = c.execute("SELECT outcome, COUNT(*) AS n FROM bastion_provenance.fetch_log WHERE source_id='test_static_pypi' GROUP BY outcome").fetchall()
print(f"      raw_artifacts still: {arts2} (expected 1)")
print(f"      fetch_log breakdown: {[(l['outcome'], l['n']) for l in logs2]}")
assert arts2 == 1
assert any(l["outcome"] == "skipped_dup" for l in logs2)

# ------- BulkScraper (network-dependent) -----------------------------

print("\n[6/7] BulkScraper test...")
src_overpass = bdb.fetch_source("osm_overpass_ladakh")
print(f"      catalogued source: {src_overpass['name']}")
from bastion.scrapers import BulkScraper
bulk = BulkScraper(src_overpass)
overpass_query = '[out:json][timeout:10];node(34.1526,77.5770,34.1527,77.5771);out;'
overpass_url = f"https://overpass-api.de/api/interpreter?data={overpass_query}"
try:
    outcome3 = bulk.ingest(overpass_url)
    print(f"      outcome: {outcome3.outcome}, size={outcome3.size_bytes}, duration_ms={outcome3.duration_ms}")
except Exception as e:
    print(f"      (network test skipped: {type(e).__name__})")

# ------- Failure path -------------------------------------------------

print("\n[7/7] failure path test (404)...")
outcome4 = scraper.ingest("https://pypi.org/pypi/this-package-definitely-does-not-exist-9876543210/json")
print(f"      outcome: {outcome4.outcome}")
assert outcome4.outcome == "http_error", f"expected http_error, got {outcome4.outcome}"

with psycopg.connect(dsn, row_factory=dict_row) as c:
    src_after = c.execute("SELECT consecutive_failures FROM bastion_provenance.sources WHERE source_id='test_static_pypi'").fetchone()
print(f"      consecutive_failures after 404: {src_after['consecutive_failures']}")
assert src_after["consecutive_failures"] == 1

print("\n" + "=" * 72)
print("ALL WEDNESDAY ASSERTIONS PASSED")
print("=" * 72)
