"""
Project Bastion — Stage 3 prediction service (v1.0)

Daily-tick orchestrator. Given a snapshot date, produces:

  demand_forecasts.parquet       (one row per post, sku, week ahead)
  route_predictions.parquet      (one row per pass, date, horizon)
  vehicle_reliability.parquet    (one row per vehicle)
  stockout_risk.parquet          (one row per post, sku, horizon)

Each output carries lineage columns:
  model_version, snapshot_date, generated_at, data_snapshot_seed

Stage 4's optimizer reads stockout_risk.parquet + route_predictions.parquet +
vehicle_reliability.parquet. Nothing else from Stage 3.
"""

import json
import time
import pandas as pd
from pathlib import Path
from datetime import datetime
import config as cfg
import features as feat
import demand_forecast as demand
import route_classifier as route
import vehicle_reliability as vehicle
import risk_scorer as risk


def run_snapshot(snapshot_date: str | pd.Timestamp,
                  out_dir: Path | None = None) -> dict:
    """
    Generate all Stage 3 prediction outputs as of `snapshot_date`.
    Returns a dict of {table_name: path} for downstream consumers.
    """
    snap = pd.Timestamp(snapshot_date)
    out_dir = out_dir or (cfg.OUTPUT_DIR / f"snapshot_{snap.date()}")
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n══ Prediction snapshot: {snap.date()} ══")
    t0 = time.time()

    # ── Load Stage 2 ─────────────────────────────────────────────────────────
    data = feat.load_all()

    generated_at = datetime.utcnow().isoformat()
    lineage = {
        "model_version": cfg.MODEL_VERSION,
        "snapshot_date": str(snap.date()),
        "generated_at": generated_at,
        "data_snapshot_seed": cfg.DATA_SNAPSHOT_SEED,
    }

    # ── Demand forecasts ─────────────────────────────────────────────────────
    print("\n[1/4] Demand forecasts...")
    demand_models = demand.load()
    panel = feat.build_demand_features(data)
    # Restrict to weeks at and after snapshot
    panel_future = panel[panel["week"] >= snap].copy()
    df_forecasts = demand.predict(panel_future, demand_models)
    for k, v in lineage.items():
        df_forecasts[k] = v
    p_forecast = out_dir / "demand_forecasts.parquet"
    df_forecasts.to_parquet(p_forecast, index=False)
    print(f"    {len(df_forecasts):,} forecast rows → {p_forecast.name}")

    # ── Route predictions ────────────────────────────────────────────────────
    print("\n[2/4] Route disruption predictions...")
    route_models = route.load()
    route_panel = feat.build_route_features(data)
    route_panel = feat.add_doy_baserate(route_panel, cfg.TRAIN_END_DATE)
    # Predict only for dates within (snap - 14, snap + 14) so the snapshot
    # is meaningful and storage is bounded
    route_panel = route_panel[(route_panel["date"] >= snap - pd.Timedelta(days=14)) &
                              (route_panel["date"] <= snap + pd.Timedelta(days=14))]
    df_routes = route.predict(route_panel, route_models)
    for k, v in lineage.items():
        df_routes[k] = v
    p_route = out_dir / "route_predictions.parquet"
    df_routes.to_parquet(p_route, index=False)
    print(f"    {len(df_routes):,} route prediction rows → {p_route.name}")

    # ── Vehicle reliability ──────────────────────────────────────────────────
    print("\n[3/4] Vehicle reliability scores...")
    veh_features = feat.build_vehicle_features(data, snap)
    df_vehicles = vehicle.score(veh_features, data["posts"])
    for k, v in lineage.items():
        df_vehicles[k] = v
    p_veh = out_dir / "vehicle_reliability.parquet"
    df_vehicles.to_parquet(p_veh, index=False)
    print(f"    {len(df_vehicles):,} vehicle scores → {p_veh.name}")

    # ── Stockout risk (composed) ─────────────────────────────────────────────
    print("\n[4/4] Stockout risk composition...")
    # Find the most recent stock row at or before snap
    stock = data["stock_daily"].copy()
    stock["date"] = pd.to_datetime(stock["date"])
    stock_atdate = stock[stock["date"] == snap]
    if len(stock_atdate) == 0:
        latest = stock[stock["date"] <= snap]["date"].max()
        stock_atdate = stock[stock["date"] == latest]
        print(f"    note: no stock at {snap.date()}, using latest available {latest.date()}")
    df_risk = risk.compute(snap, stock_atdate, df_forecasts, df_routes,
                            data["posts"], data["skus"])
    for k, v in lineage.items():
        df_risk[k] = v
    # Date column → string for parquet stability
    df_risk["snapshot_date"] = df_risk["snapshot_date"].astype(str)
    p_risk = out_dir / "stockout_risk.parquet"
    df_risk.to_parquet(p_risk, index=False)
    print(f"    {len(df_risk):,} risk rows → {p_risk.name}")

    # Lineage manifest
    manifest_path = out_dir / "lineage.json"
    manifest_path.write_text(json.dumps({**lineage,
                                          "outputs": {
                                              "demand_forecasts": str(p_forecast.name),
                                              "route_predictions": str(p_route.name),
                                              "vehicle_reliability": str(p_veh.name),
                                              "stockout_risk": str(p_risk.name),
                                          },
                                          "row_counts": {
                                              "demand_forecasts": len(df_forecasts),
                                              "route_predictions": len(df_routes),
                                              "vehicle_reliability": len(df_vehicles),
                                              "stockout_risk": len(df_risk),
                                          }}, indent=2))

    print(f"\n✓ Snapshot complete in {time.time()-t0:.1f}s")
    return {"out_dir": out_dir, **lineage}


if __name__ == "__main__":
    import sys
    snap = sys.argv[1] if len(sys.argv) > 1 else cfg.TEST_END_DATE
    run_snapshot(snap)
