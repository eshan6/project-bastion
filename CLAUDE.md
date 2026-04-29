# CLAUDE.md — Project Bastion Briefing

> This file is the cold-start briefing for any Claude Code session opened against this repository. Read it top-to-bottom before touching code. It carries the settled architectural context, the execution plan, and the working-style rules.

---

## 1. What this repo is

**Project Bastion** is a predictive military sustainment platform built by **Silverpot Defence Technologies**. It forecasts forward-post stockouts, route closures, and vehicle deadlines for high-altitude Indian Army formations (Eastern Ladakh, Arunachal, Sikkim, Siachen). The wedge product is the **Forward Stockout Predictor (FSP)** — a 12-week founder-led demo built entirely on synthetic + public data, scoped to a single Brigade in Eastern Ladakh (XIV Corps area).

This repository contains the **ingestion + extraction pipeline** that feeds the platform: scrapers that pull from public sources, a provenance database (`bastion_provenance` schema in Postgres + PostGIS), and per-source extractors that emit structured `claims` with `evidence_links` back to the raw artifacts they came from.

**Provenance is the differentiator.** Every fact in the system traces back to the artifact, source, and extractor version that produced it. This is non-negotiable — it is the credibility moat for the demo.

---

## 2. Project status

- **Pre-incorporation, Phase 1 build.**
- **Lighthouse** (the sister product, a Palantir Gotham-style ISR platform) is on pause. Bastion builds from scratch — no shared infra is assumed for Phase 1.
- **Advisor review is out of scope for Phase 1.** Public data is the realism oracle.
- **Extraction boundaries:** legality only. Scrape everything public. Paid subscriptions (Janes) are acceptable if they raise the realism floor.
- **No classified data, no offensive cyber, no offensive autonomy.** Bastion is sustainment — administrative, defensive, dual-use.

---

## 3. The 12-week execution plan (Weeks 5–16)

Phase 1 is structured as four blocks. Each block ends with a working artifact.

### Block A — Public data + ontology (Weeks 5–7)

- **Week 5:** Catalogue ~80–120 public sources. Stand up scraping stack (Playwright for JS-heavy pages, scrapy for crawls, BeautifulSoup4 for one-off parsing). Raw → curated layer in Postgres.
- **Week 6:** Bulk extract. PDF parsing via `pdfplumber` primary + Nougat for math/tables fallback. Geocode locations. Resolve entities (units, places, vehicles). Pull Sentinel-2 snow time-series for strategic passes (Zoji La, Sela, Khardung La, etc.).
- **Week 7:** Lock the ontology in Postgres + PostGIS. Build the curated layer via reproducible SQL.

**Source categories to cover in Block A:**
- *Geo / infrastructure:* Bhuvan, OpenStreetMap, SRTM/ASTER DEM, Sentinel-2, BRO bulletins, Project Vartak / Himank / Beacon / Deepak / Udayak / Setuk pages.
- *Weather + closures:* IMD daily bulletins, news archives (The Hindu, Indian Express, Times of India, Hindustan Times, Tribune, Greater Kashmir, Kashmir Observer).
- *ORBAT:* Janes, IISS, Globalsecurity, FAS, OrBat, Damien Symon's OSINT, Wikipedia.
- *Scales / consumption:* RTI/CIC archives, CAG reports, PRS + Lok Sabha Defence Committee reports, IDR / Force / SP's / DNI, DPP / DAP.
- *Vehicles:* Tata, Ashok Leyland, CAG audits, MoD annual reports.
- *Operational tempo:* PIB releases.

### Block B — Generator fitting (Weeks 8–9)

The synthetic data generator is **fitted to Block A public data, not assumed**. Every parameter has provenance.

- **Week 8:** Fit SKU consumption distributions per altitude band from CAG/RTI evidence. Fit logistic closure models per pass on 10–15 years of news + weather data. Fit vehicle survival priors from CAG audits.
- **Week 9:** `generator(sector, brigade, time, seed)` produces daily history for ~15 Eastern Ladakh posts, anchored to **real IMD weather** (only the consumption response is synthesized, not the weather itself). Every generated row carries a `provenance_id`. The generator is **deterministic** — same seed, same output.

### Block C — Models (Weeks 10–12)

- **Week 10:** Demand model. **XGBoost** per `(post, SKU)` with quantile confidence intervals (P10 / P50 / P90). Features: altitude, formation, season, holidays, weather, convoy frequency (as a tempo proxy). Train on 10 months, validate on 2. **MLflow** for versioning. Target: MAPE < 20% on top-30 SKUs, reported honestly.
- **Week 11:** Route + vehicle models. Gradient-boosted classifier on weather → P(pass open), trained on 10–15 years of real closure history. Altitude + season fallback for feeder roads. Random survival forest for vehicle reliability (acknowledge weak signal — survival data is sparse).
- **Week 12:** Optimization. **OR-Tools MIP** for resupply planning. Warm-start re-plan in < 5 seconds when a disruption hits. Lineage chain enforced: forecast → risk → optimizer output, all traceable.

### Block D — Demo UI + polish (Weeks 13–16)

- **Week 13:** React + Mapbox/MapLibre. Hex-binned posts colored by stockout risk. Per-SKU drill-down. 90-day timeline scrubber. SKU table sorted by days-to-stockout.
- **Week 14:** Provenance UI — model version + parameters + source citations (CAG, RTI, IMD) visible on every claim. **This is the Palantir-grade differentiator.** Resupply options shown with cost/time/risk tradeoffs.
- **Week 15:** Three scripted scenarios (normal ops, Zoji La closure, vehicle deadline cascade) plus an unscripted what-if mode (editable disruptions, live re-plan). SITREP markdown export.
- **Week 16:** Polish. Recorded Loom walkthrough. Pitch deck.

---

## 4. Ontology — settled object types

Built on Postgres + PostGIS. First-class objects:

- **Post** — forward operating base, picket, observation post.
- **Depot** — Central Ordnance Depot, Field Ammunition Depot, Supply Depot.
- **Route** — road segment, helipad-to-helipad air leg, foot track.
- **Vehicle** — Stallion, Topaz, ALS, mules, helicopters.
- **Convoy** — planned, in-transit, completed.
- **DemandForecast** — model output with confidence interval.
- **StockoutRisk** — per Post per SKU per time window.
- **DisruptionEvent** — predicted or actual road closure, weather event, vehicle deadline.
- **Requisition** — request from Post → Depot.
- **ResupplyPlan** — optimizer output: which vehicles, which routes, which loads.

**Provenance objects (already implemented in this repo's schema):**

- **Source** — a catalogue row per data source (IMD, CAG, Wikipedia, etc.).
- **RawArtifact** — one immutable blob per fetch, content-addressed by SHA-256.
- **Claim** — one extracted fact, with deterministic UUID5 id keyed on `(extractor_name, version, claim_type, payload_hash)`.
- **EvidenceLink** — joins a Claim to the RawArtifact(s) that support it.

Lineage view: `bastion_provenance.v_claim_lineage` joins claim → evidence → artifact → source in one query. This is what the Provenance UI in Week 14 reads from.

---

## 5. ML model specs

Three workhorse models. Kept deliberately simple. **No LLMs in the critical path** — LLMs only for natural-language SITREP summary generation.

| Model | Algorithm | Output | Target metric |
|---|---|---|---|
| Demand forecast | XGBoost per (post, SKU) | 7/30/90-day quantile forecast | MAPE < 20% on top-30 SKUs |
| Route availability | Gradient-boosted classifier | P(open) per route per day, 14d horizon | AUC + calibration on holdout |
| Vehicle reliability | Random survival forest (Cox fallback) | P(deadline within next mission) | Concordance index |

Optimization: **OR-Tools MIP**, stateful planner with checkpoint/restart for live re-plan.

---

## 6. Stack — settled decisions

- **Language:** Python 3.11+ for everything backend. TypeScript + React for the demo UI.
- **DB:** PostgreSQL 16 + PostGIS (geospatial) + pg_trgm (fuzzy match). One instance, two schemas (`bastion_provenance` and `bastion_curated`).
- **Scraping:** `httpx` for plain HTTP, `Playwright` for JS-rendered pages, `scrapy` for spiders. `BeautifulSoup4` + `lxml` for one-off HTML parsing.
- **PDF:** `pdfplumber` primary, `pytesseract` + `pdf2image` as OCR fallback for scanned docs.
- **ML:** `xgboost`, `scikit-learn`, `lifelines` (for survival), `MLflow` (self-hosted) for tracking.
- **Optimization:** `ortools`.
- **Logging:** `structlog` (JSON in prod, pretty in dev).
- **Config:** environment variables via a `Config` dataclass loaded by `bastion.core.config.get_config()`.
- **CLI:** `click`.
- **Testing:** `pytest` for unit tests; `pgserver` (embedded Postgres) for end-to-end tests so CI doesn't need a running DB.

---

## 7. Repository structure

```
project-bastion/
├── CLAUDE.md                      # this file
├── README.md
├── bastion/
│   ├── __init__.py
│   ├── cli.py                     # click CLI: fetch, queue, run-due, extract
│   ├── core/
│   │   ├── __init__.py
│   │   ├── extractor_base.py      # abstract Extractor + ExtractedClaim dataclass
│   │   └── db_extras.py           # idempotent claim+evidence_link writers
│   ├── extractors/
│   │   ├── __init__.py
│   │   ├── pdf.py                 # PdfExtractor (pdfplumber + OCR fallback)
│   │   └── html.py                # HtmlExtractor (BeautifulSoup+lxml)
│   └── sources/
│       ├── __init__.py            # EXTRACTOR_BY_SOURCE registry
│       ├── imd_daily_bulletin.py  # IMD weather bulletin parser
│       └── wikipedia_orbat.py     # Wikipedia Indian Army formation parser
└── tests/
    ├── __init__.py
    └── thursday_e2e_test.py       # end-to-end pipeline test with embedded PG
```

**Modules expected but not yet in this repo (build them when needed, do not invent paths):**

- `bastion/core/db.py` — scraper-side DB helpers (`fetch_source`, `list_due_sources`, `fetch_artifact`).
- `bastion/core/config.py` — `get_config()` returning DSN, blob root, etc.
- `bastion/core/blob.py` — `read_blob(path)` content-addressed storage reader.
- `bastion/scrapers/` — `get_scraper_class(name)` registry; HTTP/Playwright scraper classes.
- `bastion/sql/` — `01_sources_schema.sql`, `02_sources_catalogue.sql`, `03_sources_catalogue_part2_and_views.sql`.

When you build any of these, place them where the imports already point — do not relocate.

---

## 8. Working-style rules — non-negotiable

These are the operating principles for any Claude session on this project.

1. **No patchwork fixes.** Always full, complete, self-contained files. When something breaks, rewrite clean — do not paper over it.
2. **The user is non-technical.** Do not give shell commands to execute. Produce files. Label every file with its exact destination path.
3. **Justify before proceeding.** Justify claims and approach before building. Healthy skepticism is welcomed; suggestions land better *after* a working MVP than as upfront clarifying questions.
4. **Realism over generic.** Reject generic solutions. Domain-grounded, behaviorally accurate, specific.
5. **Foundry data engineer mindset for any data work.** Interrogate the data, do not describe it. Pipelines, ontologies, object relationships. Surface non-obvious patterns. Prioritize insights that change a decision.
6. **Architectural philosophy:** build toward Palantir parity, right-sized for the current stage. Map every feature back to the Block plan in §3.
7. **Right-sized over over-engineered.** No full RDF graph databases when Postgres + recursive CTEs work. No infinite abstraction.
8. **Provenance is structurally inescapable.** Extractors inherit from `bastion.core.extractor_base.Extractor` and write claims via `db_extras.insert_claim_with_evidence`. Do not bypass these. Idempotency is a property of the system, not a discipline.
9. **Notebook organization** (when notebooks are used): latest cell at top (descending order); execution order top-to-bottom; re-run safe.

---

## 9. Settled context — do not re-debate

These are decisions already made in prior planning. Treat as fixed unless the user explicitly reopens them.

- Bastion is the lead product for first revenue and iDEX traction; Lighthouse is paused.
- Wedge demo: Forward Stockout Predictor for one Brigade in Eastern Ladakh (XIV Corps area).
- Synthetic + public data only for Phase 1. No classified data.
- Architecture mirrors the Palantir ontology pattern, right-sized.
- Procurement lanes: iDEX Open Challenge AND direct Army outreach via QMG/MGS branches, run in parallel.
- 18-month budget envelope: ₹1.25–1.70 Cr.

---

## 10. Where to start in a fresh session

1. Read this file end-to-end.
2. Skim `bastion/core/extractor_base.py` and `bastion/core/db_extras.py` — they define the contract every extractor honors.
3. Skim `bastion/extractors/pdf.py` and `bastion/extractors/html.py` — content-type base classes.
4. Look at `bastion/sources/imd_daily_bulletin.py` and `bastion/sources/wikipedia_orbat.py` as reference implementations.
5. Run `tests/thursday_e2e_test.py` mentally — it shows the full pipeline in one file (embedded Postgres → schema apply → synthetic artifacts → extractor runs → lineage verification → idempotency check).

Anything you build should look like the existing code. Anything that does not should be justified before being written.
