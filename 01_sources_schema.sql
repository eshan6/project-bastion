-- ============================================================
-- Bastion Block A — Source Registry & Provenance Schema
-- Postgres 16 + PostGIS 3.4
-- Schema: bastion_raw         (landing zone, append-only)
--         bastion_provenance  (source registry, lineage)
--         bastion_curated     (Week 7 ontology lives here)
-- ============================================================

CREATE SCHEMA IF NOT EXISTS bastion_raw;
CREATE SCHEMA IF NOT EXISTS bastion_provenance;
CREATE SCHEMA IF NOT EXISTS bastion_curated;

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ------------------------------------------------------------
-- Enums — controlled vocabularies, kept narrow on purpose.
-- ------------------------------------------------------------

CREATE TYPE bastion_provenance.source_category AS ENUM (
    'geo_infra',
    'weather_closures',
    'orbat',
    'scales_doctrine',
    'vehicles_equipment',
    'tempo_signals'
);

CREATE TYPE bastion_provenance.scrape_class AS ENUM (
    'static_html',
    'dynamic_js',
    'bulk_crawl',
    'pdf_document',
    'api_json',
    'tile_raster',
    'rss_atom',
    'manual_download'
);

CREATE TYPE bastion_provenance.refresh_cadence AS ENUM (
    'once', 'daily', 'weekly', 'monthly', 'quarterly', 'on_event'
);

CREATE TYPE bastion_provenance.realism_tier AS ENUM (
    'tier_1_authoritative',
    'tier_2_credible',
    'tier_3_journalistic',
    'tier_4_osint',
    'tier_5_inferred'
);

CREATE TYPE bastion_provenance.legal_posture AS ENUM (
    'public_domain', 'gov_open_data', 'cc_licensed',
    'fair_use_research', 'tos_restrictive', 'gray_area'
);

-- ------------------------------------------------------------
-- sources — the catalogue.
-- ------------------------------------------------------------

CREATE TABLE bastion_provenance.sources (
    source_id           TEXT PRIMARY KEY,
    name                TEXT NOT NULL,
    category            bastion_provenance.source_category NOT NULL,
    realism_tier        bastion_provenance.realism_tier NOT NULL,
    scrape_class        bastion_provenance.scrape_class NOT NULL,
    refresh_cadence     bastion_provenance.refresh_cadence NOT NULL,
    legal_posture       bastion_provenance.legal_posture NOT NULL,

    base_url            TEXT NOT NULL,
    url_pattern         TEXT,
    seed_urls           TEXT[],
    notes               TEXT,

    rate_limit_seconds  NUMERIC(6,2) DEFAULT 3.0,
    user_agent          TEXT DEFAULT 'BastionResearchBot/0.1 (+contact: ops@silverpot.in)',
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    priority            SMALLINT NOT NULL DEFAULT 5,

    added_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_attempt_at     TIMESTAMPTZ,
    last_success_at     TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX ix_sources_category    ON bastion_provenance.sources(category);
CREATE INDEX ix_sources_enabled     ON bastion_provenance.sources(enabled) WHERE enabled = TRUE;
CREATE INDEX ix_sources_priority    ON bastion_provenance.sources(priority);

-- ------------------------------------------------------------
-- raw_artifacts — append-only landing zone.
-- ------------------------------------------------------------

CREATE TABLE bastion_provenance.raw_artifacts (
    artifact_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           TEXT NOT NULL REFERENCES bastion_provenance.sources(source_id),
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_url         TEXT NOT NULL,
    http_status         INTEGER,
    content_type        TEXT,
    content_sha256      TEXT NOT NULL,
    blob_path           TEXT NOT NULL,
    size_bytes          BIGINT,
    response_headers    JSONB,
    fetch_duration_ms   INTEGER,
    UNIQUE (source_id, content_sha256)
);

CREATE INDEX ix_raw_artifacts_source_time
    ON bastion_provenance.raw_artifacts(source_id, fetched_at DESC);

-- ------------------------------------------------------------
-- claims — atomic facts extracted from artifacts.
-- ------------------------------------------------------------

CREATE TABLE bastion_provenance.claims (
    claim_id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_type          TEXT NOT NULL,
    claim_payload       JSONB NOT NULL,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extractor_version   TEXT NOT NULL,
    confidence          NUMERIC(4,3),
    valid_from          DATE,
    valid_to            DATE,
    superseded_by       UUID REFERENCES bastion_provenance.claims(claim_id)
);

CREATE INDEX ix_claims_type        ON bastion_provenance.claims(claim_type);
CREATE INDEX ix_claims_payload_gin ON bastion_provenance.claims USING GIN (claim_payload);

-- ------------------------------------------------------------
-- evidence_links — many-to-many: claim <-> artifact.
-- ------------------------------------------------------------

CREATE TABLE bastion_provenance.evidence_links (
    link_id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id            UUID NOT NULL REFERENCES bastion_provenance.claims(claim_id) ON DELETE CASCADE,
    artifact_id         UUID NOT NULL REFERENCES bastion_provenance.raw_artifacts(artifact_id),
    relation            TEXT NOT NULL CHECK (relation IN ('supports','contradicts','contextualizes')),
    locator             JSONB,
    UNIQUE (claim_id, artifact_id, relation)
);

CREATE INDEX ix_evidence_claim    ON bastion_provenance.evidence_links(claim_id);
CREATE INDEX ix_evidence_artifact ON bastion_provenance.evidence_links(artifact_id);

-- ------------------------------------------------------------
-- fetch_log — every attempt, success or fail.
-- ------------------------------------------------------------

CREATE TABLE bastion_provenance.fetch_log (
    log_id              BIGSERIAL PRIMARY KEY,
    source_id           TEXT NOT NULL REFERENCES bastion_provenance.sources(source_id),
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    target_url          TEXT NOT NULL,
    outcome             TEXT NOT NULL CHECK (outcome IN ('success','http_error','timeout','blocked','parse_error','skipped_dup')),
    http_status         INTEGER,
    error_detail        TEXT,
    artifact_id         UUID REFERENCES bastion_provenance.raw_artifacts(artifact_id)
);

CREATE INDEX ix_fetch_log_source_time ON bastion_provenance.fetch_log(source_id, attempted_at DESC);
