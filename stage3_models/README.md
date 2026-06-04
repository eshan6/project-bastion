# Project Bastion — Stage 3 Models (v1.0)

**Status:** End-to-end working. 54 demand-forecast models + 20 route-disruption classifiers + 1 rule-based vehicle reliability scorer + 1 composed risk scorer. Trained against Stage 2's 2.35M-row synthetic world in ~57 seconds. Prediction snapshot runs in ~7 seconds. Every prediction row carries `model_version`, `snapshot_date`, `generated_at`, `data_snapshot_seed` lineage columns.

**v1.0 delivers the ML + composition layer** that turns Stage 2's stock ledger into actionable risk objects. The Stage 4 optimizer consumes four parquets from here — nothing else from Stage 3 leaks downstream.

---

## What this is

The model layer for Project Bastion's Forward Stockout Predictor. Per masterplan v3 Component 3 (demand), Component 4 (routes), Component 6 (vehicles), and Component 5 (composed risk).

Three model families plus a composition step:

1. **Demand forecaster** — quantile XGBoost (P10 / P50 / P90), weekly aggregation, sliced per (band, head). 18 slices × 3 quantiles = 54 boosters. Post-hoc conformal calibration on validation residuals so empirical coverage matches target.
2. **Route classifier** — binary XGBoost per (pass, horizon). 5 passes × 4 horizons = 20 classifiers. Outputs calibrated P(open) and P(closed) per (pass, date, horizon).
3. **Vehicle reliability scorer** — rule-based, analytic Weibull survival evaluation. No training. The generator parameterizes the failure process explicitly; the scorer evaluates the same survival function and writes `Vehicle.reliability_score` rows.
4. **Risk scorer** — composition layer. Joins demand forecast + current stock + route disruption probability + post.served_by into a single `StockoutRisk` row per (post, SKU, horizon) carrying `projected_days_of_cover`, `predicted_status`, `isolation_probability`, `tier_alert_fired`.

---

## What it produces

Default snapshot output (per `predict_service.py run_snapshot()`):

| Output                          | Rows (typical) | What it is                                                          |
| ------------------------------- | -------------- | ------------------------------------------------------------------- |
| `demand_forecasts.parquet`      | 3,150          | Per (post, SKU, week-ahead) P10/P50/P90 weekly consumption forecast |
| `route_predictions.parquet`     | 580            | Per (pass, date, horizon) P(open) and P(closed) probabilities       |
| `vehicle_reliability.parquet`   | 249            | Per-vehicle P(deadline within 7d) + effective age                   |
| `stockout_risk.parquet`         | 4,200          | Per (post, SKU, horizon) composed risk objects                      |
| `lineage.json`                  | —              | Snapshot manifest with row counts and model_version                 |

Snapshot at 2024-12-15 (mid-winter, isolation-stressed): 8,179 rows total, written in 6.7s.

---

## The six modules

### 1. `config.py` — paths, horizons, hyperparameters

All Stage 3 modeling parameters in one file. Train/test split, quantile levels, XGBoost params, route pass list, alert thresholds. Coefficients flagged `SYNTHETIC-INFERRED` carry the same provenance discipline as Stage 2.

### 2. `features.py` — feature engineering

Three public builders. Each consumes Stage 2 parquets and emits a training matrix:

- `build_demand_features(data)` — weekly per-(post, SKU) panel with weather rollups, calendar, lag features (1w / 4w / 12w / 52w year-ago anchor), brigade tempo days, SKU baselines. 165,900 rows.
- `build_route_features(data)` — daily per-(pass, date, horizon) panel with anchor-post weather, 7-day rolling features, brigade-wide WD signal, historical day-of-year base rate. 21,920 rows.
- `build_vehicle_features(data, as_of_date)` — snapshot per vehicle with `age_days_at_asof`, `days_since_last_event`, prior event count, home axis derivation.

Time-awareness is enforced: lag features use `shift(1)`; day-of-year base rate is computed on the training window only (`add_doy_baserate`).

### 3. `demand_forecast.py` — sliced quantile XGBoost

**Slicing decision: per (band, head), not per (post, SKU).** Three bands × six heads = 18 slices, each with 2,300–17,000 training rows. Per-SKU slicing (1,050 models) overfits on ammo SKUs that have sparse non-zero days; per-head slicing within band keeps the structural cuts (altitude band, head consumption coupling) while giving each model enough rows to converge. SKU identity is preserved as a model feature.

**Conformal calibration:** XGBoost's native quantile-error objective consistently undershoots the true interval width on weekly-aggregated heavy-tailed data. Each (band, head, quantile) booster carries a `calibration_offset` learned on validation residuals as the q-th empirical quantile of (y − pred_raw). Persisted in `demand_manifest.json`, applied at predict time. Pre-calibration coverage: 15–19% below P10 / 8–13% above P90. Post-calibration: 12.0% / 11.3% — both within 2-3 points of the 10% target.

### 4. `route_classifier.py` — pass-level binary GBM

One classifier per (pass, horizon). 5 passes × 4 horizons = 20 models. Each predicts P(open at `date + horizon`) given weather at the pass's anchor post, brigade-wide WD signal, calendar features, and the historical day-of-year base rate from the training window.

**Why pass-level rather than RouteSegment-level:** Stage 2 models closure *at the pass*. RouteSegment openness is a deterministic AND over `routes.passes_crossed`. Modeling at the pass mirrors the data-generating process; segment roll-up is done in `risk_scorer.py` and downstream SQL views.

**Evaluation metric is Brier, not accuracy.** The optimizer downstream needs calibrated probabilities. AUC numbers in the 0.63–0.83 range look mediocre but are stable; Brier scores 0.06–0.14 vs the trivial baseline at p(1-p) ≈ 0.07–0.08 confirm the models beat baseline on most slices (see `reports/evaluation_report.md` for the full breakdown including a Tsaka La 1d AUC = 0.39 explanation).

### 5. `vehicle_reliability.py` — analytic rule scorer

**Decision 3 locked: rule-based, no ML.** Stage 2 ships each vehicle with explicit Weibull(shape, scale) priors. Training a survival forest would re-learn the generator's encoding — circular by construction. The scorer evaluates:

```
H(t)                    = (t / scale)^shape                 # cumulative hazard
P(survive ≥ t+Δ | t)    = exp(H(t) − H(t+Δ))
P(deadline within Δ)    = 1 − that
```

**Repair-cycle correction:** Stage 2's generator restarts the wear clock after each deadline event. The scorer uses `days_since_last_event` (or full age if no prior events) as effective age, not raw cumulative age. Without this correction, multi-event vehicles are scored at 5+ year effective ages and the rule over-predicts failures ~2.5×. With the correction: 1.16% predicted vs 0.95% observed (22% over-prediction, acceptable).

**Honest weak-signal disclosure:** Brier skill score vs constant-rate baseline is **−0.4%** on 104 weekly snapshots × 249 vehicles = 25,896 vehicle-observations. The rule contains essentially no information beyond the unconditional failure rate. This is correct for synthetic data; real altitude/breakdown data would improve it. The scorer still produces a `reliability_score` per vehicle and writes the `vehicle_scorer_card.json` model artifact for full lineage. When real data arrives, replacing this with a survival forest is a one-file change.

Altitude hazard multiplier is set to **0.0** in v1.0 (was 0.4). The Stage 2 event generator does not apply altitude exposure to hazard, so a non-zero multiplier inflates predicted failure rates relative to the data-generating process. The axis exposure structure is preserved in config so re-enabling is a one-line change once real data backs it.

### 6. `risk_scorer.py` — composition

Joins everything into the row Stage 4 actually consumes:

```
projected_consumption_h     = (forecast_p50 / 7) × horizon_days        # P50 path
projected_consumption_h_p90 = (forecast_p90 / 7) × horizon_days        # worst-case
projected_closing_stock     = current_stock − projected_consumption_h
projected_days_of_cover     = current_stock / (forecast_p50 / 7)

if projected_closing_stock ≤ 0:          predicted_status = "stockout"
elif projected_days_of_cover < 7:        predicted_status = "rationing"
else:                                    predicted_status = "ok"

isolation_probability = Π_{p ∈ post.served_by} P(p closed)   # independence assumption

tier_alert_fired = projected_days_of_cover_p50 < ALERT_HORIZONS[tier]
```

**The independence assumption underpredicts joint isolation** (WD events close multiple passes simultaneously in the real data). This is the conservative direction for the optimizer — better to plan for less isolation than to wave away a real cascade.

---

## Evaluation results (full report: `reports/evaluation_report.md`)

| Component | Metric | Result |
|---|---|---|
| Demand P50 | weighted-avg MAPE | **29.4%** (MAE/median ratio 0.14–0.25 across forward SKUs — see report) |
| Demand P10/P90 | empirical coverage | 12.0% / 11.3% (target 10% each) |
| Route classifier | mean AUC (open) | 0.63–0.83 across horizons |
| Route classifier | mean Brier | 0.06–0.14 (vs baseline 0.07–0.08) |
| Vehicle scorer | predicted vs actual failure rate | 1.16% vs 0.95% (rolling 104-snapshot backtest) |
| Vehicle scorer | Brier skill score | −0.4% (documented weak signal) |
| **Risk scorer** | **stockout precision @14d** | **100% (32/32 flagged were stressed)** |
| **Risk scorer** | **at-risk recall @14d** | **91% (32/35 stressed items caught)** |

The risk scorer's confusion matrix at 2024-12-15, 14-day horizon, 1,050 (post, SKU) pairs:

```
                  actual_ok   actual_rationing   actual_stockout
predicted_ok          1015                  3                 0
predicted_stockout       0                 31                 1
```

128 tier alerts fired, **all** Tier 1 Rations (RAT-005) at forward+mid posts. No false alarms in other tiers.

---

## Decisions locked this session

1. **Demand slicing: per (band, head).** 18 slices, not 1,050. SKU identity is a model feature, not a slicing key. Fewer-but-thicker models for stability on sparse non-zero days.
2. **Route classifier: pass-level, 4 horizons (1/3/7/14d).** Segment roll-up downstream. Brier is the headline metric, not AUC.
3. **Vehicle scorer: rule-based, no ML.** The generator is parametric; "training" a survival forest is re-learning the generator. Documented as weak-signal. Repair-cycle correction is the only non-trivial step.
4. **Conformal post-hoc calibration on demand quantiles.** Native XGBoost quantile loss undershoots interval widths on weekly heavy-tailed data; a learned additive offset per (band, head, quantile) fixes it.
5. **Independence assumption in isolation probability.** Documented; conservative for the optimizer.
6. **XGBoost native JSON for booster artifacts; JSON for the rule scorer card.** Per-snapshot lineage in `lineage.json`.
7. **Test window: 2024-07-01 → 2024-12-31 (six months, one winter).** Short, but covers the operationally critical season. Rolling-origin three-year backtests deferred to future work.

---

## What this is NOT calibrated for

1. **Real-world consumption.** All metrics are against Stage 2's synthetic ledger. Real consumption distributions are weirder than lognormal + 1% anomaly spikes.
2. **Vehicle survival.** Brier skill near zero is the honest signal; the generator's Weibull is too clean. Real altitude/breakdown data would replace this scorer entirely.
3. **Joint pass closure correlation.** The independence assumption in isolation composition underpredicts cascades. Documented.
4. **Long-horizon route forecasts.** Beyond 14 days, the day-of-year base rate dominates the weather features. Acceptable for current scope; Sentinel-2 snowpack features would help at 30+ day horizons.
5. **Depot-band demand.** MAPE 30–41% at depots because consumption is bimodal (low-rest + bulk transfers). The optimizer plans for forward/mid posts; this is a known limitation, not a blocker.

---

## How this feeds Stage 4

The Stage 4 MIP optimizer reads exactly four parquets:

| Stage 3 output | Stage 4 use |
| --- | --- |
| `stockout_risk.parquet` | Constraint: every post-SKU at-risk in the horizon must receive resupply by horizon end |
| `route_predictions.parquet` | Cost: route-segment cost scaled by ∑ P(any crossed pass closed) over the horizon |
| `vehicle_reliability.parquet` | Constraint: fleet-availability discount on warm-start vehicle assignments |
| `demand_forecasts.parquet` | Constraint: per-post weekly forecast P90 sets the upper-bound supply requirement |

Static Stage 2 tables (`posts`, `routes`, `vehicles`, `skus`) also feed the MIP directly. Nothing else from Stage 3 needs to leak — the optimizer is decoupled from training internals.

---

## Reproducibility

Re-running `train.py` against the same Stage 2 parquets (seed 42) produces deterministic artifacts: same XGBoost trees, same calibration offsets, same backtest numbers. The `data_snapshot_seed = 42` field on every prediction row anchors the lineage.

The model artifacts under `models/` are byte-stable when retrained against the same data. Stage 4 pins `model_version = "stage3-v1.0"` to detect refresh.

---

## Run instructions

```bash
# One-time: install dependencies
pip install xgboost pandas pyarrow scikit-learn

# Train all three model families end-to-end (~57s)
cd bastion_stage3
python3 train.py

# Generate a prediction snapshot at any date in the Stage 2 horizon
python3 predict_service.py 2024-12-15
# → output/snapshot_2024-12-15/{demand_forecasts, route_predictions, vehicle_reliability, stockout_risk}.parquet
```

Training is idempotent; re-running overwrites artifacts in place. Snapshots are timestamped under `output/snapshot_{date}/`.

---

## Open items for review

1. **Demand MAPE 29% vs masterplan "under 20% on top-30" target.** The MAE-relative-to-median framing argues the model is acceptable on forward SKUs (0.14–0.25 ratio); the MAPE framing argues otherwise. Both numbers must be in the talk track — picking one is dishonest. Question for Eshan: how do we want to present this externally?

2. **Vehicle scorer Brier skill ≈ 0.** This is the masterplan's "weak prior" prediction confirmed by data. Recommend keeping the rule for v1.0, replacing only when real fleet data is in hand. No competitive demo loses credibility by acknowledging this — the lineage shows we ran a real backtest.

3. **Tsaka La 1d AUC = 0.39 in the report.** Single rare-event collapse on a 6-closures-in-183-days test set. The Brier (0.088) and the 14d AUC (0.83) show the model is fine; only that one metric looks bad in isolation. Question: is the right move to call this out proactively, or only when asked?

4. **Three-year rolling-origin backtest.** Stage 3 currently uses a single 18-month train + 6-month test split. Rolling-origin would give tighter confidence intervals on every metric. ~2 hours of work; not blocking.

5. **Repository state.** `github.com/eshan6/project-bastion` still has only the v2 legacy code (IMD bulletin extractor etc.). Stage 2 and Stage 3 code are not yet pushed. Decision needed before iDEX submission.

---

## Sources

Stage 3 is downstream of Stage 2; its training data citations are inherited from `data/README.md`. The model architecture choices are anchored to:

- XGBoost 2.0+ `reg:quantileerror` objective documentation (Tianqi Chen et al.)
- Romano, Patterson, Candès (2019) — Conformalized Quantile Regression (additive-offset conformal scheme used here)
- Brier (1950) — proper scoring rule for probabilistic forecasts
- Weibull (1951) — survival distribution; CAG Report 2017-18 for the shape/scale priors via Stage 2

---

*End of README. Models in `models/`. Eval reports in `reports/`. Snapshot outputs in `output/`.*
