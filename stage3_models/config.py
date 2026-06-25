"""
Project Bastion — Stage 3 config (v1.0)

All Stage 3 modeling parameters live here. Same discipline as Stage 2 config:
every numeric choice is either anchored to data or explicitly flagged.

Stage 3 architecture (locked):
  - Demand forecaster:    per (band, head)  quantile XGBoost, weekly aggregation
  - Route classifier:     per (pass, horizon)  binary GBM
  - Vehicle reliability:  rule-based scorer (no ML — generator already parametric)
  - Risk scorer:          composes (demand_forecast, current_stock) -> projected days_of_cover -> status

Slicing decision (per session lock-in):
  Decision 1: Per (post_type, SKU) — we model per (band, head) which is a cleaner
              cut: 3 bands × 6 heads = 18 forecasters, each seeing ~2,000–80,000
              weekly rows depending on band size. Per-SKU within a head is handled
              as a model feature, not a model identity. This deviates slightly from
              "per (band, SKU) = 90 models" toward fewer-but-thicker models because
              SKUs within a head share consumption-coupling structure (all ammo SKUs
              respond to tempo; all rations SKUs respond to troops; all POL SKUs
              respond to cold). Keeps training stable for the 5 ammo SKUs that have
              sparse non-zero days individually.

  Decision 2: Pass-level route classifiers (5 passes), 14-day horizon. RouteSegment
              openness is derived from pass openness via a SQL view (or pandas join).

  Decision 3: Rule-based vehicle reliability — see vehicle_reliability.py docstring.

  Decision 4: GitHub Actions runner + XGBoost native JSON artifact format. Models
              persist as .json (XGBoost) and .pkl (rule scorers) under models/.
"""

from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
ROOT       = Path(__file__).parent
# Stage 3 reads Stage 2's parquets from the sibling stage2_world/data directory.
# Override DATA_DIR via the BASTION_DATA_DIR env var to point at a different
# Stage 2 snapshot (e.g., a freshly regenerated world).
import os as _os
DATA_DIR   = Path(_os.environ.get("BASTION_DATA_DIR",
                                   ROOT.parent / "stage2_world" / "data"))
MODELS_DIR = ROOT / "models"        # Trained model artifacts
OUTPUT_DIR = ROOT / "output"        # Prediction parquets
REPORT_DIR = ROOT / "reports"       # Evaluation reports

for d in (MODELS_DIR, OUTPUT_DIR, REPORT_DIR):
    d.mkdir(exist_ok=True, parents=True)


# ─────────────────────────────────────────────────────────────────────────────
# Temporal setup
# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 horizon: 2022-01-01 → 2024-12-31 (1,096 days)
# Hold-out: last 6 months (2024-07-01 → 2024-12-31) — covers one winter cycle
TRAIN_END_DATE = "2024-06-30"
TEST_START_DATE = "2024-07-01"
TEST_END_DATE   = "2024-12-31"

# Forecast horizons (days ahead) — supports both ops cadence and Stage 4 optimizer
FORECAST_HORIZONS_DAYS = [7, 14, 30, 90]

# Route classifier horizons
ROUTE_HORIZONS_DAYS = [1, 3, 7, 14]


# ─────────────────────────────────────────────────────────────────────────────
# Demand forecaster
# ─────────────────────────────────────────────────────────────────────────────
# Aggregation: weekly. Daily is too noisy (per-SKU lognormal σ=0.18, 1% anomalies)
# and the Army actually plans on weekly issue cycles.
DEMAND_AGGREGATION = "W"   # pandas freq

# Quantile levels for the prediction-interval pipeline
QUANTILES = [0.10, 0.50, 0.90]

# XGBoost hyperparameters — tuned conservatively for stability on sub-thick slices.
# Per Stage 2 README, ammo SKUs have rare non-zero days; over-deep trees overfit.
XGB_QUANTILE_PARAMS = {
    "objective": "reg:quantileerror",   # native quantile loss (XGBoost 2.0+)
    "tree_method": "hist",
    "max_depth": 6,
    "learning_rate": 0.05,
    "n_estimators": 400,
    "min_child_weight": 5,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "verbosity": 0,
}

# Early stopping on time-aware holdout (last 10% of training window)
DEMAND_EARLY_STOPPING_ROUNDS = 30

# Categorical encoders — these columns will be one-hot. Keep small cardinality.
DEMAND_CATEGORICAL_COLS = [
    "post_id",          # 35 unique
    "sku",              # 30 unique  (5 per head, but we slice on head — so within-slice ~5)
    "tempo_level",      # 4 unique
    "axis",             # 6 unique
    "weather_sensitivity",  # 5 unique
]

DEMAND_NUMERIC_COLS = [
    # Post-level
    "elev_m", "troops",
    # Calendar
    "week_of_year", "month", "is_winter", "is_summer",
    # Weather (current week, rolled)
    "t_min_c_mean", "t_min_c_min",
    "t_max_c_mean",
    "precip_mm_sum",
    "is_snow_days", "is_wd_days",
    # Isolation
    "isolated_days",
    # Tempo intensity (one-hot for level, plus continuous count of crisis-days)
    "crisis_days_in_week", "high_days_in_week",
    # Lag features (computed per (post, sku))
    "qty_lag_1w", "qty_lag_4w_mean", "qty_lag_12w_mean",
    "qty_lag_52w_mean",   # year-ago seasonal anchor
    # SKU baseline
    "base_per_soldier_day",
    "tier",
    "shelf_life_days",
]


# ─────────────────────────────────────────────────────────────────────────────
# Route classifier
# ─────────────────────────────────────────────────────────────────────────────
# One binary classifier per (pass, horizon). 5 passes × 4 horizons = 20 models.
# This is overkill for storage but the per-horizon labels differ — a 14-day
# prediction is not the same problem as a 1-day prediction.
ROUTE_PASSES = ["Zoji La", "Khardung La", "Chang La", "Tsaka La", "Marsimik La"]

XGB_BINARY_PARAMS = {
    "objective": "binary:logistic",
    "tree_method": "hist",
    "max_depth": 5,
    "learning_rate": 0.05,
    "n_estimators": 300,
    "min_child_weight": 5,
    "subsample": 0.85,
    "colsample_bytree": 0.85,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "verbosity": 0,
    "eval_metric": "logloss",
}

ROUTE_EARLY_STOPPING_ROUNDS = 20

# Feature engineering for route classifier — these are computed per (pass, date)
# against weather at the *representative post* near the pass.
# Zoji La's representative anchor is Drass; we'll use weather of the highest
# post on each pass's served axis as the local weather signal.
ROUTE_PASS_TO_ANCHOR_POST_AXIS = {
    "Zoji La":     "Rear",       # Leh/Karu axis — Zoji La is the western entry
    "Khardung La": "DBO",        # serves Sub Sector North
    "Chang La":    "Pangong",    # serves Pangong axis
    "Tsaka La":    "Chushul",
    "Marsimik La": "Hot_Springs",
}

ROUTE_NUMERIC_COLS = [
    # Current weather at anchor
    "precip_mm_today", "t_min_c_today", "t_max_c_today",
    "is_snow_today", "is_wd_today",
    # Rolling weather (1-week lookback at anchor)
    "precip_mm_7d_sum", "t_min_c_7d_min", "snow_days_7d", "wd_days_7d",
    # Brigade-wide WD signal (since WD is AOR-wide)
    "wd_active_brigade_today", "wd_days_brigade_7d",
    # Calendar
    "month", "is_winter", "day_of_winter",
    # Historical base rate for this pass at this day-of-year
    "pass_open_rate_doy_historical",
    # Pass-class indicator (one-hot via DataFrame join)
]

ROUTE_CATEGORICAL_COLS = ["pass_name"]


# ─────────────────────────────────────────────────────────────────────────────
# Vehicle reliability (rule-based)
# ─────────────────────────────────────────────────────────────────────────────
# Generator already parameterizes Weibull(shape, scale) per vehicle class.
# Stage 3 scorer just evaluates the survival function with documented coefficients.
# No training, but we still write ModelVersion rows for lineage.
VEHICLE_HORIZON_DAYS = 7        # P(deadline within next 7 days)

# Class-level baseline daily failure rate adjustment (from CAG-anchored Stage 2 priors).
# These match Stage 2 generator's defaults — read at runtime from vehicles.parquet.
# Listed here only so the rule scorer is self-documenting.
VEHICLE_CLASS_PRIORS_NOTE = """
Per Stage 2 (config.py), vehicles ship with weibull_shape and weibull_scale_days.
Shape > 1 means failure rate increases with age (wear-out). Stage 3 reads these
directly and computes:

    H(t)        = (t / scale)^shape                # cumulative hazard at age t
    P(fail in Δ | survived t) = 1 - exp(H(t) - H(t+Δ))

Altitude exposure adjustment: vehicles operating off forward axes spend more days
above 4500m, which Stage 2 doesn't differentiate per-event. Stage 3 applies a
documented multiplier on hazard for the assumed days-at-altitude in the horizon:

    hazard_adj = base_hazard * (1 + 0.4 * frac_days_above_4500)   # SYNTHETIC-INFERRED

The 0.4 is a placeholder. Real altitude/breakdown data would replace it.
"""

VEHICLE_ALTITUDE_HAZARD_MULTIPLIER = 0.0   # SYNTHETIC-INFERRED — see note below.

# Rationale for setting to 0 in v1.0:
# Stage 2's event generator does NOT apply an altitude multiplier — vehicles fail
# per their per-class Weibull regardless of home depot or axis. Applying any
# nonzero multiplier here inflates predicted failure rates relative to the
# data-generating process. Backtest at multiplier=0.4 confirmed this: predicted
# rate ~2.15% vs actual ~0.95% (~2.25× over-prediction, Brier skill -1.7%).
#
# When real altitude/breakdown data arrives, this coefficient should be fit
# against that data, not assumed. The altitude exposure structure is preserved
# in the config so re-enabling is a one-line change.


# ─────────────────────────────────────────────────────────────────────────────
# Risk scorer
# ─────────────────────────────────────────────────────────────────────────────
# Composes demand forecast P50/P90 with current stock to project days_of_cover
# and predicted status (ok / rationing / stockout) at the forecast horizon.
# Thresholds mirror Stage 2's stock.py status rules.
RISK_STATUS_THRESHOLDS = {
    "stockout_days_of_cover": 0.0,   # closing_stock <= 0
    "rationing_days_of_cover": 7.0,  # < 7 days reserve triggers rationing flag
}

# Tier-specific alert horizons (days_of_cover thresholds at which to fire alerts)
ALERT_HORIZONS = {
    1: 14,   # Tier 1 SKUs: 14 days alert horizon
    2: 7,    # Tier 2: 7 days
    3: 3,    # Tier 3: 3 days
}


# ─────────────────────────────────────────────────────────────────────────────
# Model versioning
# ─────────────────────────────────────────────────────────────────────────────
MODEL_VERSION = "stage3-v1.2"   # v1.1 vehicle scorer v2; v1.2 wear-GLM scorer + spares-demand forecaster (PDS 5)
DATA_SNAPSHOT_SEED = 42   # Stage 2 seed used to generate the training data


# ─────────────────────────────────────────────────────────────────────────────
# v1.2 (Phase 2) — SPARES-DEMAND FORECASTER (PDS 5: "Demand Forecast of Spares")
# ─────────────────────────────────────────────────────────────────────────────
# Horizons (days) for spare-part demand forecasts, per depot.
SPARES_FORECAST_HORIZONS = [30, 60, 90]
# Monte-Carlo trials for the P10/P50/P90 spares-demand quantiles. Each trial
# samples, per vehicle homed at the depot, whether it fails in the horizon
# (Bernoulli at the scorer's p_deadline scaled to the horizon), then samples the
# parts consumed per failure from the empirical per-subsystem parts distribution
# learned from spares_consumption. Deterministic via a fixed seed.
SPARES_MC_TRIALS = 400
SPARES_MC_SEED = 42
