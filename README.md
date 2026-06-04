# Project Bastion

**Forward Stockout Predictor (FSP) for Indian Army logistics in high-altitude AORs.** Decision-support intelligence layer that forecasts which forward posts will run out of which supplies, when, and what resupply plan keeps them stocked under realistic weather, route, and vehicle disruptions.

This repository contains the **build-the-system** phase: a real ontology, real ML models, real optimization, evaluated against thick synthetic data we generate ourselves. It is not a procurement demo. It is the working substrate of the eventual production system.

> **Status:** Stage 2 (world generator) and Stage 3 (model layer + risk composition) are complete and runnable end-to-end. Stage 4 (MIP optimizer) and Stage 5 (lineage views + UI) are in design.

---

## What this is

The Indian Army's forward sustainment problem in Ladakh, Arunachal Pradesh, Sikkim, and Siachen is a four-variable optimization run today by experienced JCOs with whiteboards, radio voice traffic, and intuition. The four variables:

- **Demand** — what each post will consume in the next 7/30/90 days, by SKU
- **Supply** — what's in which depot, in what condition, with what shelf life
- **Transport** — which roads/passes/helipads are open, with what capacity, under what weather
- **Disruption** — when Zoji La closes, when the next storm hits Tawang, when a vehicle deadline cascades into a stockout

There is no system that combines these into a single answer for a Brigadier (Logistics) at a Corps HQ. Bastion is that system — eventually, in production. This repository builds it against synthetic data first, against a thick-synthetic Eastern Ladakh world calibrated to public sources (CAG audits, RTI returns, IMD climatology, news archives, BRO documentation).

For full context, see **[`docs/masterplan_v3.md`](docs/masterplan_v3.md)**.

---

## Architecture

The system has six components per the masterplan. Two are in this repository today:

```
                      ┌─────────────────────────────────┐
                      │ Component 1: Ontology           │
                      │ (Postgres + PostGIS — TBD)      │
                      └─────────────────────────────────┘
                                       │
                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ stage2_world/   Component 2: Synthetic data generator        │
   │   parametric, seedable, deterministic                       │
   │   2.35M rows / 35 posts / 30 SKUs / 3 years                 │
   │   → 12 parquet files in data/                               │
   └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
   ┌─────────────────────────────────────────────────────────────┐
   │ stage3_models/  Component 3 (demand), 4 (routes), 6 (vehicles),│
   │                  + 5 (risk composition)                      │
   │   54 quantile XGBoost demand forecasters (band × head × q)   │
   │   20 binary XGBoost route classifiers (pass × horizon)       │
   │    1 rule-based Weibull vehicle reliability scorer           │
   │    1 risk scorer composing the above with current stock      │
   │   → 4 prediction parquets per snapshot                       │
   └─────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                      ┌─────────────────────────────────┐
                      │ Component 4: Optimizer          │
                      │ (OR-Tools MIP — TBD, Stage 4)   │
                      └─────────────────────────────────┘
                                       │
                                       ▼
                      ┌─────────────────────────────────┐
                      │ Component 5/6: Lineage + UI     │
                      │ (TBD, Stage 5)                  │
                      └─────────────────────────────────┘
```

---

## Repository layout

```
project-bastion/
├── README.md                       # You are here
├── docs/
│   └── masterplan_v3.md            # Strategic context, decisions, build sequence
│
├── stage2_world/                   # Synthetic world generator (Stage 2)
│   ├── README.md                   # ← full Stage 2 docs (sources, fitting, validation)
│   ├── config.py                   # All parameters; SYNTHETIC-INFERRED flags
│   ├── generate.py                 # Top-level driver
│   ├── world.py                    # Posts, routes, vehicles, SKUs
│   ├── weather.py                  # IMD-anchored daily weather + WD events
│   ├── disruption.py               # Pass closure model
│   ├── consumption.py              # Coupled consumption to weather/tempo/isolation
│   ├── vehicles.py                 # Weibull-based deadline event generator
│   ├── stock.py                    # Stock dynamics, AWS pre-positioning, spoilage
│   ├── validation_report.json      # Distributional checks vs targets
│   └── data/                       # 12 generated parquet files (2.35M rows total)
│
└── stage3_models/                  # ML models + risk composition (Stage 3)
    ├── README.md                   # ← full Stage 3 docs (slicing, calibration, eval)
    ├── config.py                   # Hyperparams, horizons, alert thresholds
    ├── features.py                 # Feature engineering (panels, lags, rollups)
    ├── demand_forecast.py          # Quantile XGBoost + conformal calibration
    ├── route_classifier.py         # Binary GBM per (pass, horizon)
    ├── vehicle_reliability.py      # Analytic Weibull scorer + rolling backtest
    ├── risk_scorer.py              # Composition into StockoutRisk rows
    ├── train.py                    # Training orchestrator (~57s end-to-end)
    ├── predict_service.py          # Snapshot orchestrator (~7s per snapshot)
    ├── models/                     # 77 model artifacts + manifests
    ├── reports/
    │   ├── evaluation_report.md    # ← honest accuracy assessment
    │   ├── evaluation_demand.json
    │   ├── evaluation_route.json
    │   └── evaluation_vehicle.json
    └── output/
        └── snapshot_2024-12-15/    # Sample snapshot (4 parquets + lineage.json)
```

---

## How to run it

### Prerequisites

```bash
pip install pandas pyarrow numpy xgboost scikit-learn
```

Python 3.10+. XGBoost 2.0+ (for native `reg:quantileerror` objective).

### Stage 2 — regenerate the synthetic world

```bash
cd stage2_world
python3 generate.py
# → writes 12 parquets to data/ in ~2 minutes
# → seed-controlled; same seed produces byte-identical output
```

The repository ships with a pre-generated snapshot at seed 42 already in `stage2_world/data/`. You don't need to regenerate unless you want to.

### Stage 3 — train all models

```bash
cd stage3_models
python3 train.py
# → 54 demand boosters + 20 route classifiers + 1 vehicle scorer card
# → writes to models/ and reports/
# → runs in ~57 seconds
```

The repository ships with trained models already in `stage3_models/models/`. You don't need to retrain unless Stage 2 changes.

### Stage 3 — generate a prediction snapshot

```bash
cd stage3_models
python3 predict_service.py 2024-12-15
# → 4 parquets written to output/snapshot_2024-12-15/
# → runs in ~7 seconds
```

The repository ships with the `2024-12-15` snapshot already produced. Try any date between `2022-01-01` and `2024-12-31`.

---

## Headline results

From [`stage3_models/reports/evaluation_report.md`](stage3_models/reports/evaluation_report.md):

| Component | Metric | Result |
|---|---|---|
| Demand forecaster (P50) | weighted-avg MAPE | 29.4% (MAE/median ratio 0.14–0.25 across forward SKUs) |
| Demand forecaster (P10/P90) | empirical coverage | 12.0% / 11.3% (target 10% each) |
| Route classifier | mean AUC across horizons | 0.63–0.83 |
| Route classifier | mean Brier | 0.06–0.14 (vs baseline 0.07–0.08) |
| Vehicle scorer | rolling-backtest predicted vs actual rate | 1.16% vs 0.95% |
| Vehicle scorer | Brier skill score | −0.4% (documented weak signal) |
| **Risk scorer @ 14d horizon** | **stockout precision** | **100% (32/32 flagged were stressed)** |
| **Risk scorer @ 14d horizon** | **at-risk recall** | **91% (32/35 stressed items caught)** |

Confusion matrix, 14-day horizon, 1,050 (post, SKU) pairs at the 2024-12-15 snapshot:

```
                  actual_ok   actual_rationing   actual_stockout
predicted_ok          1015                  3                 0
predicted_stockout       0                 31                 1
```

128 tier alerts fired — all Tier 1 Rations (RAT-005) at forward+mid posts. No false alarms in other tiers.

---

## Honest framing

These metrics are computed on **synthetic data** generated by Stage 2. They are a proof of *functionality* — that the pipeline trains, calibrates, predicts, and produces internally consistent risk objects that compose into actionable signals. They are **not** a proof of real-world accuracy.

Some metrics will get better when real data arrives (real signal is often stronger than thick-synthetic priors). Some will get worse (real anomalies are weirder than lognormal noise + 1% spikes). The system is built so that swapping the data substrate doesn't require rewriting the modeling layer.

See `stage3_models/reports/evaluation_report.md` for the full breakdown including the four documented limitations.

---

## What's next

**Stage 4: MIP optimizer.** OR-Tools formulation that consumes the four Stage 3 output parquets plus the static Stage 2 tables, emits `ResupplyPlan` rows ranking 3–5 alternatives per (post, day) by cost/time/risk. Warm-start under 5 seconds for what-if replans.

**Stage 5: lineage + visibility.** SQL views joining alerts → risks → forecasts → models → snapshots so any prediction is traceable to its inputs. Internal-only for the build phase; customer-facing UI decided in v4 of the masterplan.

---

## License

TBD — Silverpot Defence Technologies, all rights reserved pending license decision.

---

## Authorship

Strategic direction: **Eshan Ghose**, Silverpot Defence Technologies.
Implementation: Claude (Anthropic), executing under founder direction.

This codebase was built to demonstrate the system at the iDEX submission stage. Public data sourcing, generator calibration anchors, model architecture decisions, and evaluation framing are documented inline.
