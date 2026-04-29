# project-bastion

Predictive military sustainment platform for high-altitude Indian Army formations. Built by Silverpot Defence Technologies.

This repository is the **ingestion + extraction pipeline** for Project Bastion: scrapers that pull from public sources (IMD, BRO, Wikipedia, CAG, RTI, Bhuvan, etc.) and per-source extractors that emit structured claims with full lineage back to the raw artifact and source.

> For full context — execution plan, ontology, model specs, working-style rules — read [`CLAUDE.md`](./CLAUDE.md). It is the master briefing for this project.

## Repository structure

```
project-bastion/
├── CLAUDE.md                      # master briefing — read this first
├── README.md
├── pyproject.toml
├── .env.example                   # copy to .env and fill in
├── .gitignore
├── bastion/
│   ├── __init__.py
│   ├── cli.py                     # bastion CLI: fetch, queue, run-due, extract
│   ├── sql/
│   │   ├── 01_sources_schema.sql
│   │   ├── 02_sources_catalogue.sql
│   │   └── 03_sources_catalogue_part2_and_views.sql
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py              # env-driven Config dataclass
│   │   ├── db.py                  # scraper-side DB helpers
│   │   ├── db_extras.py           # idempotent claim + evidence_link writers
│   │   ├── blob.py                # content-addressed local storage
│   │   ├── ratelimit.py           # per-source token bucket
│   │   ├── scraper_base.py        # abstract Scraper + provenance lifecycle
│   │   └── extractor_base.py      # abstract Extractor + ExtractedClaim
│   ├── scrapers/
│   │   ├── __init__.py            # get_scraper_class() registry
│   │   ├── static_scraper.py      # httpx + tenacity
│   │   ├── dynamic_scraper.py     # Playwright headless
│   │   └── bulk_scraper.py        # streaming downloads
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── pdf.py                 # PdfExtractor (pdfplumber + OCR fallback)
│   │   └── html.py                # HtmlExtractor (BeautifulSoup + lxml)
│   └── sources/
│       ├── __init__.py            # EXTRACTOR_BY_SOURCE registry
│       ├── imd_daily_bulletin.py  # IMD weather bulletin parser
│       └── wikipedia_orbat.py     # Wikipedia Indian Army formation parser
└── tests/
    ├── __init__.py
    ├── wednesday_e2e_test.py      # scraper pipeline (embedded Postgres)
    └── thursday_e2e_test.py       # extractor pipeline (embedded Postgres)
```

## Provenance contract

Every fact in the system traces back to the artifact, source, and extractor version that produced it. The contract is enforced structurally:

- All scrapers inherit from `bastion.core.scraper_base.Scraper`. `ingest()` writes raw_artifacts + fetch_log + sources state in one inescapable code path.
- All extractors inherit from `bastion.core.extractor_base.Extractor`. Claims are written via `bastion.core.db_extras.insert_claim_with_evidence`, which produces deterministic UUID5 claim IDs keyed on `(extractor_name, version, claim_type, payload_hash)`.
- Re-running a scraper or extractor against the same input produces zero new rows. Verified in `tests/wednesday_e2e_test.py` and `tests/thursday_e2e_test.py`.

The lineage view `bastion_provenance.v_claim_lineage` joins claim → evidence → artifact → source in a single query. The Provenance UI in the demo reads from this view.

## Quickstart

```bash
# 1. Install dependencies
pip install -e ".[test]"

# 2. Copy env template
cp .env.example .env
# edit .env with your Postgres DSN

# 3. Apply schema (against your real Postgres)
psql "$BASTION_DB_DSN" -f bastion/sql/01_sources_schema.sql
psql "$BASTION_DB_DSN" -f bastion/sql/02_sources_catalogue.sql
psql "$BASTION_DB_DSN" -f bastion/sql/03_sources_catalogue_part2_and_views.sql

# 4. Run the e2e tests (uses embedded Postgres, no real DB needed)
python tests/wednesday_e2e_test.py
python tests/thursday_e2e_test.py
```

## Status

Phase 1 of 5. Wedge product: Forward Stockout Predictor for a Brigade in Eastern Ladakh (XIV Corps area), built on synthetic + public data. See `CLAUDE.md` §3 for the 12-week block plan.

**Block A Week 5: complete.** Source catalogue (112 sources), scraper stack (Static/Dynamic/Bulk), extractor stack (PDF/HTML), provenance schema with deterministic UUID5 idempotency, end-to-end tests passing.

**Next: Block A Week 6.** Bulk extraction against real public sources, Sentinel-2 snow time-series for strategic passes, geocoding.
