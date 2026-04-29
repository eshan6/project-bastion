"""
Thursday e2e test: extractor pipeline.

1. Embedded Postgres + schema + catalogue.
2. Synthetic IMD bulletin PDF (reportlab) and Wikipedia HTML fixture.
3. Insert as raw_artifacts directly (skipping fetch — proven Wednesday).
4. Run extractors.
5. Verify claims + evidence_links + v_claim_lineage.
6. Re-run → 0 new claims (idempotency).

Run from repo root:
    python tests/thursday_e2e_test.py
"""
from __future__ import annotations
import hashlib
import os
import re
import sys
import tempfile
from pathlib import Path

import pgserver
import psycopg
from psycopg.rows import dict_row

# Repo-relative imports
REPO_ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = REPO_ROOT / "bastion" / "sql"
sys.path.insert(0, str(REPO_ROOT))

print("=" * 72)
print("THURSDAY E2E TEST — Bastion extractor pipeline")
print("=" * 72)

work = tempfile.mkdtemp(prefix="bastion_thu_")
blob_root = Path(work) / "blobs"
blob_root.mkdir()

print("\n[1/8] starting embedded postgres...")
srv = pgserver.get_server(str(Path(work) / "pg"), cleanup_mode="stop")
dsn = srv.get_uri()
os.environ["BASTION_DB_DSN"] = dsn
os.environ["BASTION_BLOB_ROOT"] = str(blob_root)

from bastion.core.config import reset_config_for_tests
reset_config_for_tests()

print("\n[2/8] applying schema + catalogue...")
schema_sql = (SQL_DIR / "01_sources_schema.sql").read_text()
catalogue_p1 = (SQL_DIR / "02_sources_catalogue.sql").read_text()
catalogue_p2 = (SQL_DIR / "03_sources_catalogue_part2_and_views.sql").read_text()

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

print("\n[3/8] building synthetic IMD bulletin PDF...")
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

pdf_path = Path(work) / "imd_synthetic.pdf"
c_pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
W, H = A4
c_pdf.setFont("Helvetica-Bold", 14)
c_pdf.drawString(72, H - 72, "INDIA METEOROLOGICAL DEPARTMENT")
c_pdf.setFont("Helvetica", 11)
c_pdf.drawString(72, H - 92, "All India Weather Summary and Forecast Bulletin")
c_pdf.drawString(72, H - 110, "Dated 15 January 2026 (1730 hrs IST)")
y = H - 150
for line in [
    "SYNOPTIC FEATURES:",
    "A western disturbance is seen as a trough in middle and upper",
    "tropospheric westerlies over Jammu & Kashmir and adjoining",
    "Ladakh. Light to moderate snowfall is likely over higher",
    "reaches of Ladakh during next 48 hours. Zoji La pass is",
    "experiencing heavy snowfall; closure expected.",
]:
    c_pdf.drawString(72, y, line)
    y -= 16
c_pdf.showPage()
c_pdf.setFont("Helvetica-Bold", 12)
c_pdf.drawString(72, H - 72, "Station-wise observations (24h ending 0830 IST 15-Jan-2026)")
c_pdf.setFont("Helvetica", 10)
c_pdf.drawString(72, H - 100, "Station          Tmax(C)   Tmin(C)   RF(mm)")
c_pdf.drawString(72, H - 116, "----------------------------------------------")
y = H - 132
for name, tmax, tmin, rain in [
    ("LEH",     -8.5,  -15.2,  0.0),
    ("KARGIL",  -5.0,  -13.0,  2.5),
    ("DRASS",  -10.0,  -22.0,  1.0),
    ("SRINAGAR", 4.0,  -3.5,   0.0),  # not in gazetteer — should be filtered
]:
    c_pdf.drawString(72, y, f"{name:<16} {tmax:>6.1f}    {tmin:>6.1f}    {rain:>5.1f}")
    y -= 16
c_pdf.save()
pdf_bytes = pdf_path.read_bytes()
print(f"      synthetic PDF: {len(pdf_bytes)} bytes")

print("\n[4/8] building synthetic Wikipedia HTML fixture...")
wiki_html = """<!DOCTYPE html>
<html lang="en">
<head><title>XIV Corps (India) - Wikipedia</title></head>
<body>
  <h1 id="firstHeading">XIV Corps (India)</h1>
  <div id="mw-content-text">
    <table class="infobox vcard">
      <tr><th>Active</th><td>1999 – present</td></tr>
      <tr><th>Country</th><td>India</td></tr>
      <tr><th>Type</th><td>Corps</td></tr>
      <tr><th>Part of</th><td>Northern Command</td></tr>
      <tr><th>Headquarters</th><td>Leh, Ladakh</td></tr>
      <tr><th>Nickname(s)</th><td>Fire and Fury Corps</td></tr>
    </table>
    <p>The <b>XIV Corps</b>, also known as the Fire and Fury Corps, is a corps
       of the Indian Army based at Leh in Ladakh. It was raised in September 1999
       in response to the Kargil War. The corps is responsible for the area
       between Zoji La and the Karakoram Pass.</p>
    <p>It comprises the 3rd Infantry Division based at Karu and the
       8th Mountain Division based at Khumbathang. The corps also has
       under its command the 102nd Infantry Brigade at Siachen.</p>
    <p>The 70 Infantry Brigade and 114 Infantry Brigade also fall under
       this Corps for operational purposes.</p>
  </div>
</body>
</html>"""
wiki_bytes = wiki_html.encode("utf-8")

print("\n[5/8] inserting synthetic artifacts as raw_artifacts rows...")

def insert_synthetic(source_id, content, content_type, url):
    sha = hashlib.sha256(content).hexdigest()
    blob_rel = f"{source_id}/{sha[0:2]}/{sha[2:4]}/{sha}.bin"
    abs_blob = blob_root / blob_rel
    abs_blob.parent.mkdir(parents=True, exist_ok=True)
    abs_blob.write_bytes(content)
    with psycopg.connect(dsn) as c:
        cur = c.execute(
            """
            INSERT INTO bastion_provenance.raw_artifacts
                (source_id, fetched_url, http_status, content_type, content_sha256,
                 blob_path, size_bytes, response_headers, fetch_duration_ms)
            VALUES (%s, %s, 200, %s, %s, %s, %s, %s, 0)
            RETURNING artifact_id::text;
            """,
            (source_id, url, content_type, sha, blob_rel, len(content),
             psycopg.types.json.Jsonb({})),
        )
        aid = cur.fetchone()[0]
        c.commit()
    return aid

imd_artifact = insert_synthetic(
    "imd_daily_bulletin", pdf_bytes, "application/pdf",
    "https://mausam.imd.gov.in/Forecast/marquee_data/20260115_dailyweather.pdf",
)
wiki_artifact = insert_synthetic(
    "wikipedia_indianarmy", wiki_bytes, "text/html; charset=utf-8",
    "https://en.wikipedia.org/wiki/XIV_Corps_(India)",
)
print(f"      imd_artifact:  {imd_artifact}")
print(f"      wiki_artifact: {wiki_artifact}")

print("\n[6/8] running extractors...")
from bastion.sources import EXTRACTOR_BY_SOURCE

n_imd = EXTRACTOR_BY_SOURCE["imd_daily_bulletin"]().extract(imd_artifact)
print(f"      imd extractor wrote {n_imd} new claims")
assert n_imd >= 4

n_wiki = EXTRACTOR_BY_SOURCE["wikipedia_indianarmy"]().extract(wiki_artifact)
print(f"      wiki extractor wrote {n_wiki} new claims")
assert n_wiki >= 1

print("\n[7/8] verifying claims + evidence + lineage...")
with psycopg.connect(dsn, row_factory=dict_row) as c:
    imd_claims = c.execute("""
        SELECT claim_type, claim_payload, confidence FROM bastion_provenance.claims
        WHERE claim_payload->>'source_url' LIKE '%imd.gov.in%'
           OR claim_payload->>'station' IS NOT NULL
        ORDER BY claim_type, claim_payload->>'station' NULLS FIRST;
    """).fetchall()
    print(f"\n      IMD claims ({len(imd_claims)}):")
    for cr in imd_claims:
        ct = cr["claim_type"]; p = cr["claim_payload"]
        if ct == "imd_synoptic_summary":
            print(f"        {ct}  date={p.get('date')}  summary[:80]={p.get('summary_text','')[:80]!r}")
        else:
            print(f"        {ct}  station={p['station']:<8} date={p['date']}  tmax={p['tmax_c']}  tmin={p['tmin_c']}  rain={p.get('rain_mm_24h')}")

    wiki_claims = c.execute("""
        SELECT claim_type, claim_payload, confidence FROM bastion_provenance.claims
        WHERE claim_payload->>'source_url' LIKE '%wikipedia%'
        ORDER BY claim_type;
    """).fetchall()
    print(f"\n      Wiki claims ({len(wiki_claims)}):")
    for cr in wiki_claims:
        ct = cr["claim_type"]; p = cr["claim_payload"]
        if ct == "orbat_formation":
            print(f"        {ct}  name={p['name']!r} type={p.get('formation_type')} hq={p.get('headquarters')!r} parent={p.get('parent_formation')!r}")
        else:
            print(f"        {ct}  parent={p.get('parent')!r} -> sub={p.get('subordinate')!r} conf={cr['confidence']}")

    n_lineage_rows = c.execute("SELECT COUNT(*) AS n FROM bastion_provenance.v_claim_lineage").fetchone()["n"]
    print(f"\n      v_claim_lineage rows: {n_lineage_rows}")
    assert n_lineage_rows >= n_imd + n_wiki

    sample = c.execute("""
        SELECT claim_type, source_id, source_name, realism_tier, fetched_url
        FROM bastion_provenance.v_claim_lineage WHERE claim_type = 'imd_station_obs' LIMIT 1;
    """).fetchone()
    print(f"      sample lineage: {sample['claim_type']} <- {sample['source_id']} ({sample['realism_tier']}) <- {sample['fetched_url']}")

print("\n[8/8] idempotency test (re-run extractors)...")
n_imd_2 = EXTRACTOR_BY_SOURCE["imd_daily_bulletin"]().extract(imd_artifact)
n_wiki_2 = EXTRACTOR_BY_SOURCE["wikipedia_indianarmy"]().extract(wiki_artifact)
print(f"      imd re-run wrote {n_imd_2} new claims (expected 0)")
print(f"      wiki re-run wrote {n_wiki_2} new claims (expected 0)")
assert n_imd_2 == 0
assert n_wiki_2 == 0

print("\n" + "=" * 72)
print("ALL THURSDAY ASSERTIONS PASSED")
print("=" * 72)
