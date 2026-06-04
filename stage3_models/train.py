"""
Project Bastion — Stage 3 training orchestrator (v1.0)

Run this to train all Stage 3 models end-to-end against Stage 2 parquets.
Outputs:
  - models/demand_*.json + demand_manifest.json
  - models/route_*.json  + route_manifest.json
  - models/vehicle_scorer_card.json
  - reports/evaluation_demand.json
  - reports/evaluation_route.json
  - reports/evaluation_vehicle.json  (backtest at end of training window)

Idempotent: re-running overwrites artifacts in place.
"""

import json
import time
import pandas as pd
from pathlib import Path
import config as cfg
import features as feat
import demand_forecast as demand
import route_classifier as route
import vehicle_reliability as vehicle


def main():
    t0 = time.time()
    print("Stage 3 training pipeline")
    print(f"  data dir:    {cfg.DATA_DIR}")
    print(f"  models dir:  {cfg.MODELS_DIR}")
    print(f"  reports dir: {cfg.REPORT_DIR}")
    print(f"  train end:   {cfg.TRAIN_END_DATE}")
    print(f"  test window: {cfg.TEST_START_DATE} → {cfg.TEST_END_DATE}")
    print()

    # ── Load Stage 2 ─────────────────────────────────────────────────────────
    print("[1/4] Loading Stage 2 parquets...")
    data = feat.load_all()
    for t, df in data.items():
        print(f"    {t}: {len(df):,} rows")

    # ── Demand forecasters ───────────────────────────────────────────────────
    print("\n[2/4] Building demand features...")
    panel = feat.build_demand_features(data)
    print(f"    demand panel: {len(panel):,} weekly (post, sku) rows")
    print(f"    weeks: {panel['week'].min().date()} → {panel['week'].max().date()}")

    print("\n  Training demand forecasters...")
    demand_models = demand.train(panel)
    demand.save(demand_models)

    # ── Route classifiers ────────────────────────────────────────────────────
    print("\n[3/4] Building route features...")
    route_panel = feat.build_route_features(data)
    route_panel = feat.add_doy_baserate(route_panel, cfg.TRAIN_END_DATE)
    print(f"    route panel: {len(route_panel):,} (pass, date, horizon) rows")

    print("\n  Training route classifiers...")
    route_models = route.train(route_panel)
    route.save(route_models)

    # ── Vehicle reliability ──────────────────────────────────────────────────
    print("\n[4/4] Vehicle reliability scorer (rule-based, no training)")
    vehicle.save_scorer_card()

    # Rolling backtest: every Monday across two years (excluding the very last
    # horizon_days, since we can't observe the future beyond Stage 2's end_date).
    print("  Running rolling backtest (this takes ~30s)...")
    veh_eval = vehicle.evaluate_rolling(data,
                                          start_date="2023-01-02",
                                          end_date="2024-12-24",
                                          step_days=7)
    eval_path = cfg.REPORT_DIR / "evaluation_vehicle.json"
    eval_path.write_text(json.dumps({"model_version": cfg.MODEL_VERSION,
                                      "scorer_kind": "rule_weibull_altitude_v1",
                                      **veh_eval}, indent=2, default=str))
    print(f"  rolling backtest ({veh_eval['n_snapshots']} snapshots, "
          f"{veh_eval['n_observations']:,} vehicle-observations):")
    print(f"    actual failure rate:    {veh_eval['actual_failure_rate']:.5f}")
    print(f"    predicted failure rate: {veh_eval['predicted_failure_rate_mean']:.5f}")
    print(f"    Brier:                  {veh_eval['brier']}")
    print(f"    Brier skill vs baseline: {veh_eval['brier_skill_score_vs_baseline']:+.3f}")

    elapsed = time.time() - t0
    print(f"\n✓ Stage 3 training complete in {elapsed:.1f}s")


if __name__ == "__main__":
    main()
