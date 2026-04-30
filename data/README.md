# `data/` — Project Bastion data assets

This directory contains the static data assets for Project Bastion. Two subdirectories:

## `data/catalogue/` — Ingestion source catalogue

Reference documents describing the public-data ingestion plan for Block A. These define *where data would come from* if/when the bulk-pull pipeline is run.

- **`sources.yaml`** — 90 catalogued sources across 8 families (geo_infra, weather, news, orbat, scales_budget, vehicles, tempo, imagery). Single source of truth for the bulk-pull driver. Each source has license, robots-txt status, and provenance metadata.
- **`meta_sources.sql`** — Postgres DDL for `meta.sources` and `meta.aoi`, plus the EOD audit view `meta.v_pull_status` and a sync-job spec at the bottom.

These are reference artifacts under the current Path C scope (no live ingestion). They document the architecture for advisors and for when a technical operator joins.

## `data/fsp/` — Forward Stockout Predictor demo content

The locked, hand-curated, version-controlled data the FSP demo runs on. This is *not* scraped data — it's illustrative content with explicit provenance grading. See `data/fsp/methodology.md` (when added) for the full provenance story.

- **`posts.json`** — 15 forward posts + 4 depots + 3 LoC axes, scoped to XIV Corps AOI (Eastern Ladakh). AOI bbox: 76.0–79.5°E, 32.5–35.5°N.
- **`routes.json`** — Hybrid route model: 16 segmented strategic LoCs + 13 simple tactical edges, plus 3 air-resupply edges. 22 logical edges in total used by the optimizer.
- **`skus.json`** — 30 SKUs across 6 stock heads (Rations, POL, Ammo, Medical, Clothing, General) with terrain-class consumption multipliers (Plains, HA, SHA, ECC).
- **`vehicles.json`** — 9 vehicle classes (trucks, mules, porters, helos) with payload, altitude derate curves, surface compatibility, reliability priors, and cost per tonne-km.

### Provenance discipline

Every entity carries a `provenance_grade` field:
- **A** — Publicly documented (Wikipedia, news, MoD/CAG/Lok Sabha sources, manufacturer specs).
- **B** — Real area/concept publicly known; specific instance is illustrative.
- **C** — Generic designator for demo purposes; clearly synthetic.

Numerical figures (consumption rates, reliability priors, costs) are **illustrative central estimates consistent with publicly reported patterns**. Real Army scales of issue are restricted; this demo does not claim to reproduce them.

### Cross-references

The four FSP files are designed to join cleanly:
- `posts.json` posts reference `routes.json` segments via `primary_route_segments_outbound`.
- `routes.json` edges reference `posts.json` nodes via `from_node` / `to_node`.
- `skus.json` POL entries reference `vehicles.json` IDs via fuel-burn keys (`Stallion_loaded`, `Mi-17_typical_sortie`, etc.).
- `vehicles.json` surface compatibility maps to `routes.json` segment surface types.

Adding scenarios and methodology files completes the demo's data layer.
