-- ============================================================
-- Project Bastion — meta.sources table
-- Block A, Wk6
--
-- Purpose:
--   Single source of truth for the bulk-pull driver. Mirrors sources.yaml
--   in the repo. Sync job (see bottom of this file) reads YAML and upserts
--   into this table; pull driver reads from this table and writes status
--   back via UPDATE.
--
-- Foreign-key target:
--   Every row in raw.* tables carries a `source_id TEXT` column referencing
--   meta.sources(source_id). This is the provenance chain.
-- ============================================================

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.sources (
    source_id           TEXT        PRIMARY KEY,
    source_name         TEXT        NOT NULL,
    family              TEXT        NOT NULL CHECK (family IN (
                            'geo_infra', 'weather', 'news', 'orbat',
                            'scales_budget', 'vehicles', 'tempo', 'imagery'
                        )),
    tier                TEXT        NOT NULL CHECK (tier IN (
                            'primary', 'secondary', 'deferred'
                        )),
    url_or_endpoint     TEXT        NOT NULL,
    extractor_module    TEXT        NOT NULL,
    extractor_config    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    raw_table           TEXT        NOT NULL,
    pull_frequency      TEXT        NOT NULL CHECK (pull_frequency IN (
                            'once', 'daily', 'weekly'
                        )),
    license_or_terms    TEXT        NOT NULL CHECK (license_or_terms IN (
                            'gov_open', 'cc_by_sa', 'cc_by',
                            'public_domain', 'proprietary_public_web'
                        )),
    robots_txt_status   TEXT        NOT NULL CHECK (robots_txt_status IN (
                            'respected', 'ignored', 'n_a'
                        )),
    notes               TEXT,

    -- Pull-status columns, written by the pull driver, not by sync.
    last_pull_at        TIMESTAMPTZ,
    last_pull_status    TEXT        CHECK (last_pull_status IN (
                            'success', 'partial', 'fail', 'deferred', 'pending'
                        )),
    last_row_count      INTEGER,
    last_error          TEXT,

    -- Catalogue audit columns.
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    catalogue_version   TEXT        NOT NULL DEFAULT 'wk6_seed_v1'
);

CREATE INDEX IF NOT EXISTS idx_sources_family_tier ON meta.sources (family, tier);
CREATE INDEX IF NOT EXISTS idx_sources_pull_status ON meta.sources (last_pull_status);
CREATE INDEX IF NOT EXISTS idx_sources_freq          ON meta.sources (pull_frequency);

-- ============================================================
-- AOI table — single AOI row for Wk6, joinable by name.
-- Extractors that need bbox read meta.aoi WHERE name = 'eastern_ladakh_xiv_corps'.
-- ============================================================

CREATE TABLE IF NOT EXISTS meta.aoi (
    aoi_name            TEXT        PRIMARY KEY,
    bbox_west           NUMERIC     NOT NULL,
    bbox_south          NUMERIC     NOT NULL,
    bbox_east           NUMERIC     NOT NULL,
    bbox_north          NUMERIC     NOT NULL,
    crs                 TEXT        NOT NULL DEFAULT 'EPSG:4326',
    notes               TEXT
);

INSERT INTO meta.aoi (aoi_name, bbox_west, bbox_south, bbox_east, bbox_north, notes)
VALUES (
    'eastern_ladakh_xiv_corps',
    76.0, 32.5, 79.5, 35.5,
    'XIV Corps AOI for Wk6. Covers Leh, Kargil, Drass, Pangong, DBO, Nubra.'
)
ON CONFLICT (aoi_name) DO NOTHING;

-- ============================================================
-- EOD audit view — one row per source, joining catalogue to raw counts.
-- Wk6 daily standup runs `SELECT * FROM meta.v_pull_status WHERE family = 'X'`.
-- ============================================================

CREATE OR REPLACE VIEW meta.v_pull_status AS
SELECT
    s.source_id,
    s.family,
    s.tier,
    s.raw_table,
    s.last_pull_status,
    s.last_pull_at,
    s.last_row_count,
    CASE
        WHEN s.last_pull_status IS NULL                              THEN 'never_pulled'
        WHEN s.last_pull_status = 'fail'                             THEN 'broken'
        WHEN s.last_pull_status = 'deferred'                         THEN 'deferred'
        WHEN s.last_pull_at < NOW() - INTERVAL '7 days'
             AND s.pull_frequency IN ('daily', 'weekly')             THEN 'stale'
        ELSE                                                              'ok'
    END AS health,
    s.last_error
FROM meta.sources s;

-- ============================================================
-- Sync job spec (for whoever implements it — ~1-2 hours of work)
-- ============================================================
--
-- INPUT:  /repo/sources.yaml
-- OUTPUT: meta.sources upserted; meta.aoi upserted; diff printed to stdout
--
-- Pseudocode:
--
--   1. Load YAML. Validate against the column constraints above
--      (family enum, tier enum, license enum, robots enum).
--      Fail loud on any violation — do not silently coerce.
--
--   2. For each source row:
--        INSERT INTO meta.sources (...) VALUES (...)
--        ON CONFLICT (source_id) DO UPDATE SET
--            source_name      = EXCLUDED.source_name,
--            family           = EXCLUDED.family,
--            tier             = EXCLUDED.tier,
--            url_or_endpoint  = EXCLUDED.url_or_endpoint,
--            extractor_module = EXCLUDED.extractor_module,
--            extractor_config = EXCLUDED.extractor_config,
--            raw_table        = EXCLUDED.raw_table,
--            pull_frequency   = EXCLUDED.pull_frequency,
--            license_or_terms = EXCLUDED.license_or_terms,
--            robots_txt_status= EXCLUDED.robots_txt_status,
--            notes            = EXCLUDED.notes,
--            updated_at       = NOW()
--            -- DELIBERATELY NOT updating last_pull_* — those are owned by pull driver.
--
--   3. For source_ids in DB but missing from YAML:
--        Print a warning. Do not auto-delete.
--        Manual decision: was this an intentional removal, or a YAML edit mistake?
--
--   4. Print diff:
--        N_added, N_updated, N_unchanged, N_in_db_not_in_yaml.
--
--   5. Exit non-zero on any validation failure or DB error.
--
-- WHERE TO CALL FROM:
--   Add to repo as `cli (1).py` subcommand, e.g. `python cli.py sync-catalogue`.
--   Or as standalone script `sync_catalogue.py` invoked from a Makefile target.
--
-- ============================================================
