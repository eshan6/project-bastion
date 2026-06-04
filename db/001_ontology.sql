-- ============================================================================
-- Project Bastion — Stage 1 Substrate Migration  (001_ontology.sql)
-- ----------------------------------------------------------------------------
-- Target      : Supabase (PostgreSQL 15/16 + PostGIS 3.x). Idempotent.
-- Faithful to : the Stage 2 generator's ACTUAL output (seed 42, 2,350,274 rows,
--               2022-01-01..2024-12-31) and Stage 3 outputs (model stage3-v1.0,
--               snapshot 2024-12-15). Column names mirror the parquet exactly so
--               the loader is a 1:1 passthrough, not a translation layer.
--
-- Schemas
--   bastion_provenance : Source, RawArtifact, Claim, EvidenceLink  (v2-compatible)
--                        + ModelVersion, DataSnapshot               (v3 additions)
--   bastion            : domain objects + prediction objects + alerts
--
-- Provenance is structural: every anchorable domain object MUST cite a Source
-- or carry synthetic_inferred = TRUE. The CHECK makes an un-provenanced row
-- physically impossible to insert.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE SCHEMA IF NOT EXISTS bastion_provenance;
CREATE SCHEMA IF NOT EXISTS bastion;

-- ---------------------------------------------------------------------------
-- Enums (guarded)
-- ---------------------------------------------------------------------------
DO $$ BEGIN CREATE TYPE bastion_provenance.source_category AS ENUM
  ('geo_infra','weather_closures','orbat','scales_doctrine','vehicles_equipment','tempo_signals');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion_provenance.realism_tier AS ENUM
  ('tier_1_authoritative','tier_2_credible','tier_3_journalistic','tier_4_osint','tier_5_inferred');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion_provenance.model_kind AS ENUM
  ('demand_forecast','route_availability','vehicle_reliability','optimizer','risk_evaluator');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.provenance_grade AS ENUM ('A','B','C');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.supply_band AS ENUM ('forward','mid','depot');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.post_status AS ENUM ('ok','rationing','stockout');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.disruption_kind AS ENUM ('pass_closure','vehicle_deadline','weather');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.vehicle_status AS ENUM ('available','tasked','in_transit','deadline','maintenance');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.plan_objective AS ENUM ('min_cost','min_time','min_risk','balanced');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.alert_type AS ENUM ('stockout_risk','disruption','vehicle_deadline');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN CREATE TYPE bastion.alert_severity AS ENUM ('info','warning','critical');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ============================================================================
-- PROVENANCE BACKBONE
-- ============================================================================
CREATE TABLE IF NOT EXISTS bastion_provenance.sources (
    source_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    bastion_provenance.source_category NOT NULL,
    realism_tier bastion_provenance.realism_tier NOT NULL,
    base_url    TEXT, url_pattern TEXT, seed_urls TEXT[], notes TEXT,
    enabled     BOOLEAN NOT NULL DEFAULT TRUE,
    priority    SMALLINT NOT NULL DEFAULT 5,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bastion_provenance.raw_artifacts (
    artifact_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id   TEXT NOT NULL REFERENCES bastion_provenance.sources(source_id),
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    fetched_url TEXT NOT NULL, content_sha256 TEXT NOT NULL,
    blob_path TEXT, size_bytes BIGINT,
    UNIQUE (source_id, content_sha256)
);
CREATE TABLE IF NOT EXISTS bastion_provenance.claims (
    claim_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_type TEXT NOT NULL, claim_payload JSONB NOT NULL,
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extractor_version TEXT NOT NULL, confidence NUMERIC(4,3)
);
CREATE INDEX IF NOT EXISTS ix_claims_payload_gin ON bastion_provenance.claims USING GIN (claim_payload);
CREATE TABLE IF NOT EXISTS bastion_provenance.evidence_links (
    link_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    claim_id UUID NOT NULL REFERENCES bastion_provenance.claims(claim_id) ON DELETE CASCADE,
    artifact_id UUID NOT NULL REFERENCES bastion_provenance.raw_artifacts(artifact_id),
    relation TEXT NOT NULL CHECK (relation IN ('supports','contradicts','contextualizes')),
    UNIQUE (claim_id, artifact_id, relation)
);
-- data_snapshot: the frozen world a model run executed against (seed 42 canonical)
CREATE TABLE IF NOT EXISTS bastion_provenance.data_snapshot (
    snapshot_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    label TEXT NOT NULL, seed INTEGER NOT NULL, as_of_date DATE NOT NULL,
    generator_version TEXT NOT NULL, horizon_days INTEGER,
    row_counts JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), notes TEXT,
    UNIQUE (label, as_of_date)
);
-- model_version: every trained artifact, its params and held-out metrics
CREATE TABLE IF NOT EXISTS bastion_provenance.model_version (
    model_version_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind bastion_provenance.model_kind NOT NULL,
    name TEXT NOT NULL, algorithm TEXT NOT NULL,
    params JSONB, metrics JSONB,
    trained_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    trained_on_snapshot UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    git_sha TEXT, artifact_path TEXT, notes TEXT,
    UNIQUE (kind, name)
);

-- ============================================================================
-- DOMAIN OBJECTS
-- ============================================================================
-- stock_head: the six supply heads as generated (exact strings = codes)
CREATE TABLE IF NOT EXISTS bastion.stock_head (
    code TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT
);
-- sku: tier is the generator's integer (1/2/3); no per-SKU provenance in source,
-- so synthetic_inferred defaults TRUE and the CHECK is satisfied at load.
CREATE TABLE IF NOT EXISTS bastion.sku (
    sku_id TEXT PRIMARY KEY,
    head TEXT NOT NULL REFERENCES bastion.stock_head(code),
    name TEXT NOT NULL,
    base_per_soldier_day NUMERIC(12,4),
    shelf_life_days INTEGER,
    tier SMALLINT NOT NULL,
    weather_sensitivity TEXT,
    provenance_grade bastion.provenance_grade NOT NULL DEFAULT 'C',
    provenance_source_id TEXT REFERENCES bastion_provenance.sources(source_id),
    provenance_note TEXT,
    synthetic_inferred BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT sku_provenance_required
      CHECK (provenance_source_id IS NOT NULL OR synthetic_inferred = TRUE)
);
CREATE INDEX IF NOT EXISTS ix_sku_head ON bastion.sku(head);
-- depot: derived from the is_depot subset of nodes
CREATE TABLE IF NOT EXISTS bastion.depot (
    depot_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    location geometry(Point,4326) NOT NULL, elev_m INTEGER, axis TEXT,
    provenance_grade bastion.provenance_grade NOT NULL DEFAULT 'C',
    provenance_source_id TEXT REFERENCES bastion_provenance.sources(source_id),
    synthetic_inferred BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT depot_provenance_required
      CHECK (provenance_source_id IS NOT NULL OR synthetic_inferred = TRUE)
);
CREATE INDEX IF NOT EXISTS gx_depot_location ON bastion.depot USING GIST (location);
-- post: all 35 nodes. supply band {forward,mid,depot}; planning horizon topology-driven.
CREATE TABLE IF NOT EXISTS bastion.post (
    post_id TEXT PRIMARY KEY, name TEXT NOT NULL,
    band bastion.supply_band NOT NULL,
    axis TEXT, elev_m INTEGER, troops INTEGER,
    location geometry(Point,4326) NOT NULL,
    is_depot BOOLEAN NOT NULL DEFAULT FALSE,
    has_air_resupply BOOLEAN NOT NULL DEFAULT FALSE,
    served_by TEXT[],
    parent_depot_id TEXT REFERENCES bastion.depot(depot_id),
    provenance_grade bastion.provenance_grade NOT NULL DEFAULT 'C',
    provenance_source_id TEXT REFERENCES bastion_provenance.sources(source_id),
    provenance_note TEXT,
    synthetic_inferred BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT post_provenance_required
      CHECK (provenance_source_id IS NOT NULL OR synthetic_inferred = TRUE)
);
CREATE INDEX IF NOT EXISTS gx_post_location ON bastion.post USING GIST (location);
CREATE INDEX IF NOT EXISTS ix_post_depot ON bastion.post(parent_depot_id);
-- mountain pass (closure unit for the route model)
CREATE TABLE IF NOT EXISTS bastion.pass (
    pass_name TEXT PRIMARY KEY
);
-- route: origin/destination are post ids; passes_crossed kept as array + fanned to segments
CREATE TABLE IF NOT EXISTS bastion.route (
    route_id TEXT PRIMARY KEY,
    from_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    to_id   TEXT NOT NULL REFERENCES bastion.post(post_id),
    distance_km NUMERIC(8,2), elev_max_m INTEGER,
    route_type TEXT, axis TEXT, passes_crossed TEXT[],
    provenance_grade bastion.provenance_grade NOT NULL DEFAULT 'C',
    provenance_source_id TEXT REFERENCES bastion_provenance.sources(source_id),
    synthetic_inferred BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT route_provenance_required
      CHECK (provenance_source_id IS NOT NULL OR synthetic_inferred = TRUE)
);
CREATE TABLE IF NOT EXISTS bastion.route_segment (
    segment_id TEXT PRIMARY KEY,
    route_id TEXT NOT NULL REFERENCES bastion.route(route_id) ON DELETE CASCADE,
    seq SMALLINT NOT NULL,
    pass_name TEXT REFERENCES bastion.pass(pass_name),
    UNIQUE (route_id, seq)
);
-- vehicle_class + vehicle (Weibull params live per-vehicle in the generator)
CREATE TABLE IF NOT EXISTS bastion.vehicle_class (
    class_id TEXT PRIMARY KEY, payload_tons NUMERIC(8,2),
    provenance_grade bastion.provenance_grade NOT NULL DEFAULT 'C',
    provenance_source_id TEXT REFERENCES bastion_provenance.sources(source_id),
    synthetic_inferred BOOLEAN NOT NULL DEFAULT TRUE,
    CONSTRAINT vclass_provenance_required
      CHECK (provenance_source_id IS NOT NULL OR synthetic_inferred = TRUE)
);
CREATE TABLE IF NOT EXISTS bastion.vehicle (
    vehicle_id TEXT PRIMARY KEY,
    class_id TEXT NOT NULL REFERENCES bastion.vehicle_class(class_id),
    payload_tons NUMERIC(8,2),
    home_depot_id TEXT REFERENCES bastion.depot(depot_id),
    initial_age_days INTEGER,
    weibull_shape NUMERIC(8,4), weibull_scale_days INTEGER,
    status bastion.vehicle_status NOT NULL DEFAULT 'available',
    reliability_score NUMERIC(8,6), p_deadline NUMERIC(8,6)
);
CREATE INDEX IF NOT EXISTS ix_vehicle_class ON bastion.vehicle(class_id);
-- tempo (global daily operational tempo)
CREATE TABLE IF NOT EXISTS bastion.tempo_daily (
    date DATE PRIMARY KEY, tempo_level TEXT NOT NULL
);
-- western-disturbance episodes
CREATE TABLE IF NOT EXISTS bastion.wd_event (
    event_id TEXT PRIMARY KEY, start_date DATE NOT NULL,
    duration_days INTEGER, precip_mult NUMERIC(6,3), temp_drop_c NUMERIC(6,3), type TEXT
);
-- daily pass open/closed truth
CREATE TABLE IF NOT EXISTS bastion.pass_status_daily (
    pass_name TEXT NOT NULL REFERENCES bastion.pass(pass_name),
    date DATE NOT NULL, is_open BOOLEAN NOT NULL,
    PRIMARY KEY (pass_name, date)
);
-- weather (calibrated to IMD climatology; see data_snapshot.notes)
CREATE TABLE IF NOT EXISTS bastion.weather_observation (
    id BIGSERIAL PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    obs_date DATE NOT NULL,
    t_max_c NUMERIC(6,2), t_min_c NUMERIC(6,2), t_mean_c NUMERIC(6,2),
    precip_mm NUMERIC(7,2), is_snow BOOLEAN, is_wd_active BOOLEAN, anchor_name TEXT,
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    UNIQUE (post_id, obs_date)
);
CREATE INDEX IF NOT EXISTS ix_weather_post_date ON bastion.weather_observation(post_id, obs_date);
-- consumption (daily draw per post x sku)
CREATE TABLE IF NOT EXISTS bastion.consumption_event (
    id BIGSERIAL PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    sku_id TEXT NOT NULL REFERENCES bastion.sku(sku_id),
    event_date DATE NOT NULL,
    qty_consumed NUMERIC(14,3) NOT NULL,
    tempo TEXT, is_isolated BOOLEAN, t_mean_c NUMERIC(6,2),
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id)
);
CREATE INDEX IF NOT EXISTS ix_consump_post_sku_date ON bastion.consumption_event(post_id, sku_id, event_date);
-- stock ledger (the generator's full daily stock dynamics)
CREATE TABLE IF NOT EXISTS bastion.stock_level (
    id BIGSERIAL PRIMARY KEY,
    post_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    sku_id TEXT NOT NULL REFERENCES bastion.sku(sku_id),
    as_of_date DATE NOT NULL,
    opening_stock NUMERIC(16,3), aws_receipt NUMERIC(16,3), routine_receipt NUMERIC(16,3),
    nominal_consumption NUMERIC(16,3), consumption NUMERIC(16,3), spoilage NUMERIC(16,3),
    unmet_demand NUMERIC(16,3), closing_stock NUMERIC(16,3), days_of_cover NUMERIC(10,2),
    status bastion.post_status NOT NULL DEFAULT 'ok',
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    UNIQUE (post_id, sku_id, as_of_date)
);
CREATE INDEX IF NOT EXISTS ix_stocklvl_post_sku_date ON bastion.stock_level(post_id, sku_id, as_of_date);
CREATE INDEX IF NOT EXISTS ix_stocklvl_status ON bastion.stock_level(status) WHERE status <> 'ok';

-- ============================================================================
-- PREDICTION OBJECTS (first-class, lineage-bearing)
-- ============================================================================
-- demand_forecast: weekly XGBoost quantile output per (post, sku)
CREATE TABLE IF NOT EXISTS bastion.demand_forecast (
    forecast_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    post_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    sku_id TEXT NOT NULL REFERENCES bastion.sku(sku_id),
    target_week DATE NOT NULL, band bastion.supply_band, head TEXT,
    p10 NUMERIC(14,3) NOT NULL, p50 NUMERIC(14,3) NOT NULL, p90 NUMERIC(14,3) NOT NULL,
    model_version_id UUID NOT NULL REFERENCES bastion_provenance.model_version(model_version_id),
    snapshot_id UUID NOT NULL REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- NB: no monotonicity CHECK. Quantile crossing (p50>p90) is a real property
    -- of per-quantile calibrated regression; the crossing rate is reported in the
    -- validation report rather than enforced away (which would falsify model output).
    UNIQUE (post_id, sku_id, target_week, model_version_id)
);
CREATE INDEX IF NOT EXISTS ix_forecast_post_sku ON bastion.demand_forecast(post_id, sku_id, target_week);
-- stockout_risk: the headline prediction. Rich projection + tier-alert flags.
CREATE TABLE IF NOT EXISTS bastion.stockout_risk (
    risk_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    snapshot_date DATE NOT NULL,
    post_id TEXT NOT NULL REFERENCES bastion.post(post_id),
    sku_id TEXT NOT NULL REFERENCES bastion.sku(sku_id),
    head TEXT, tier SMALLINT, axis TEXT, band bastion.supply_band,
    horizon_days INTEGER NOT NULL,
    current_stock NUMERIC(16,3), current_days_of_cover NUMERIC(10,2), current_status bastion.post_status,
    p10 NUMERIC(14,3), p50 NUMERIC(14,3), p90 NUMERIC(14,3),
    projected_consumption_p50 NUMERIC(14,3), projected_consumption_p90 NUMERIC(14,3),
    projected_closing_stock_p50 NUMERIC(16,3), projected_closing_stock_p90 NUMERIC(16,3),
    projected_days_of_cover_p50 NUMERIC(12,4), projected_days_of_cover_p90 NUMERIC(12,4),
    predicted_status bastion.post_status, predicted_status_worstcase bastion.post_status,
    isolation_probability NUMERIC(8,6), isolation_route_horizon_used INTEGER,
    tier_alert_horizon INTEGER, tier_alert_fired BOOLEAN NOT NULL DEFAULT FALSE,
    model_version_id UUID NOT NULL REFERENCES bastion_provenance.model_version(model_version_id),
    snapshot_id UUID NOT NULL REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_risk_fired ON bastion.stockout_risk(tier_alert_fired) WHERE tier_alert_fired = TRUE;
CREATE INDEX IF NOT EXISTS ix_risk_post_sku ON bastion.stockout_risk(post_id, sku_id, horizon_days);
-- route_prediction: P(open) per pass per horizon
CREATE TABLE IF NOT EXISTS bastion.route_prediction (
    prediction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    pass_name TEXT NOT NULL REFERENCES bastion.pass(pass_name),
    target_date DATE NOT NULL, horizon_days INTEGER NOT NULL,
    p_open NUMERIC(8,6), p_closed NUMERIC(8,6),
    model_version_id UUID NOT NULL REFERENCES bastion_provenance.model_version(model_version_id),
    snapshot_id UUID NOT NULL REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pass_name, target_date, horizon_days, model_version_id)
);
-- vehicle_reliability: per-vehicle P(deadline) prediction
CREATE TABLE IF NOT EXISTS bastion.vehicle_reliability (
    prediction_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    vehicle_id TEXT NOT NULL REFERENCES bastion.vehicle(vehicle_id),
    snapshot_date DATE NOT NULL, horizon_days INTEGER NOT NULL,
    age_days_at_asof INTEGER, events_to_date INTEGER, frac_high_altitude NUMERIC(6,4),
    effective_age_days NUMERIC(12,2), reliability_score NUMERIC(10,8), p_deadline NUMERIC(10,8),
    scorer_kind TEXT,
    model_version_id UUID NOT NULL REFERENCES bastion_provenance.model_version(model_version_id),
    snapshot_id UUID NOT NULL REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (vehicle_id, snapshot_date, horizon_days, model_version_id)
);
-- disruption_event: ACTUAL observed disruptions (pass closures + vehicle deadlines)
CREATE TABLE IF NOT EXISTS bastion.disruption_event (
    event_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    kind bastion.disruption_kind NOT NULL,
    pass_name TEXT REFERENCES bastion.pass(pass_name),
    vehicle_id TEXT REFERENCES bastion.vehicle(vehicle_id),
    start_date DATE NOT NULL, end_date DATE, duration_days INTEGER,
    detail JSONB,
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id)
);
CREATE INDEX IF NOT EXISTS ix_disruption_pass ON bastion.disruption_event(pass_name, start_date);
-- resupply_plan (OR-Tools optimizer output; Stage 4 populates, table ready now)
CREATE TABLE IF NOT EXISTS bastion.resupply_plan (
    plan_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    objective bastion.plan_objective NOT NULL,
    total_cost NUMERIC(14,2), total_time_hours NUMERIC(10,2), aggregate_risk NUMERIC(8,4),
    model_version_id UUID REFERENCES bastion_provenance.model_version(model_version_id),
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS bastion.resupply_plan_leg (
    leg_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES bastion.resupply_plan(plan_id) ON DELETE CASCADE,
    seq SMALLINT NOT NULL, vehicle_id TEXT REFERENCES bastion.vehicle(vehicle_id),
    route_id TEXT REFERENCES bastion.route(route_id), sku_id TEXT REFERENCES bastion.sku(sku_id),
    qty NUMERIC(14,3), depart_date DATE, expected_cost NUMERIC(14,2), expected_risk NUMERIC(8,4),
    UNIQUE (plan_id, seq)
);

-- ============================================================================
-- ALERTS (each alert is an ontology row joined to its trigger)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bastion.alert (
    alert_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_type bastion.alert_type NOT NULL, severity bastion.alert_severity NOT NULL,
    message TEXT NOT NULL,
    post_id TEXT REFERENCES bastion.post(post_id), sku_id TEXT REFERENCES bastion.sku(sku_id),
    pass_name TEXT REFERENCES bastion.pass(pass_name), vehicle_id TEXT REFERENCES bastion.vehicle(vehicle_id),
    source_risk_id UUID REFERENCES bastion.stockout_risk(risk_id),
    source_route_prediction_id UUID REFERENCES bastion.route_prediction(prediction_id),
    snapshot_id UUID REFERENCES bastion_provenance.data_snapshot(snapshot_id),
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_alert_open ON bastion.alert(severity, created_at DESC) WHERE acknowledged = FALSE;

-- ============================================================================
-- LINEAGE VIEWS
-- ============================================================================
CREATE OR REPLACE VIEW bastion.v_object_provenance AS
  SELECT 'post' AS object_type, post_id AS object_id, name, provenance_grade,
         CASE WHEN synthetic_inferred THEN 'SYNTHETIC-INFERRED' ELSE provenance_source_id END AS provenance
  FROM bastion.post
  UNION ALL SELECT 'depot', depot_id, name, provenance_grade,
         CASE WHEN synthetic_inferred THEN 'SYNTHETIC-INFERRED' ELSE provenance_source_id END FROM bastion.depot
  UNION ALL SELECT 'sku', sku_id, name, provenance_grade,
         CASE WHEN synthetic_inferred THEN 'SYNTHETIC-INFERRED' ELSE provenance_source_id END FROM bastion.sku
  UNION ALL SELECT 'route', route_id, route_id, provenance_grade,
         CASE WHEN synthetic_inferred THEN 'SYNTHETIC-INFERRED' ELSE provenance_source_id END FROM bastion.route
  UNION ALL SELECT 'vehicle_class', class_id, class_id, provenance_grade,
         CASE WHEN synthetic_inferred THEN 'SYNTHETIC-INFERRED' ELSE provenance_source_id END FROM bastion.vehicle_class;

-- alert -> stockout_risk -> model + snapshot, one row. The Palantir-shaped chain.
CREATE OR REPLACE VIEW bastion.v_prediction_lineage AS
  SELECT a.alert_id, a.alert_type, a.severity, a.message,
         r.risk_id, r.post_id, r.sku_id, r.head, r.horizon_days,
         r.current_days_of_cover, r.projected_days_of_cover_p50, r.predicted_status,
         r.isolation_probability, r.tier_alert_horizon, r.tier_alert_fired,
         mv.model_version_id, mv.name AS model_name, mv.algorithm AS model_algorithm, mv.metrics AS model_metrics,
         ds.snapshot_id, ds.label AS snapshot_label, ds.seed AS snapshot_seed, ds.as_of_date AS snapshot_as_of
  FROM bastion.alert a
  LEFT JOIN bastion.stockout_risk r ON a.source_risk_id = r.risk_id
  LEFT JOIN bastion_provenance.model_version mv ON r.model_version_id = mv.model_version_id
  LEFT JOIN bastion_provenance.data_snapshot ds ON r.snapshot_id = ds.snapshot_id;

-- ============================================================================
-- SEED — six stock heads (exact generator vocabulary)
-- ============================================================================
INSERT INTO bastion.stock_head (code, name, description) VALUES
  ('Rations',   'Rations',    'Rations and fresh/dry provisions'),
  ('Ammunition','Ammunition', 'Small arms, support weapon and pyrotechnic natures'),
  ('POL',       'POL',        'Petroleum, oil, lubricants; diesel, SKO/kerosene'),
  ('Medical',   'Medical',    'Medical stores, oxygen, HAPE/HACE consumables'),
  ('Clothing',  'Clothing',   'ECC clothing and snow equipment'),
  ('Engineer',  'Engineer',   'Engineer and general stores')
ON CONFLICT (code) DO NOTHING;
-- END
