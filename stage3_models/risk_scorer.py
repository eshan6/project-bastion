"""
Project Bastion — Stage 3 risk scorer (v1.0)

Composes the three model outputs into actionable risk objects.

Inputs:
  - current stock balance (from stock_daily, as-of snapshot date)
  - demand forecast (p10/p50/p90 weekly, per post+sku)
  - route disruption probability per (pass, horizon)

Outputs (per post+sku):
  - projected_days_of_cover at horizon, using P50 and P90 demand
  - predicted_status (ok / rationing / stockout) at horizon
  - isolation_risk: P(post becomes isolated within horizon), derived from
                    pass closure probabilities and posts.served_by
  - tier_alert_fired: bool, per masterplan tier thresholds (Tier 1=14d, 2=7d, 3=3d)

The point of this module: collapse three model outputs into one
StockoutRisk row per (post, sku, snapshot_date, horizon). That row is what
the Stage 4 optimizer consumes.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import config as cfg


def _isolation_probability(post_row, route_probs_today: pd.DataFrame,
                            horizon_days: int) -> float:
    """
    Probability that this post is isolated at horizon, given route disruption
    probabilities. Post is isolated iff ALL its served_by passes are closed.

    Independence assumption: pass closures are treated as independent. This
    *underestimates* joint-isolation in reality (a single WD often closes
    multiple passes), but it's the conservative direction for the optimizer —
    we'd rather under-predict isolation than over-predict it.
    """
    served = post_row["served_by"]
    if isinstance(served, np.ndarray):
        served = served.tolist()
    if not served or (isinstance(served, list) and len(served) == 0):
        return 0.0

    p_closed_each = []
    for pass_name in served:
        sub = route_probs_today[(route_probs_today["pass_name"] == pass_name) &
                                (route_probs_today["horizon"] == horizon_days)]
        if len(sub) == 0:
            # No prediction — treat as base-rate closed (conservative)
            p_closed_each.append(0.05)
        else:
            p_closed_each.append(float(sub["p_closed"].iloc[0]))

    # P(all closed) under independence
    p_iso = float(np.prod(p_closed_each))
    return p_iso


def compute(snapshot_date: str | pd.Timestamp,
            stock_today: pd.DataFrame,
            demand_forecasts: pd.DataFrame,
            route_predictions: pd.DataFrame,
            posts: pd.DataFrame,
            skus: pd.DataFrame,
            horizon_days_list: list = None) -> pd.DataFrame:
    """
    Compose risk rows per (post, sku, horizon).

    Math:
      projected_consumption_h = (forecast_p50_weekly / 7) × horizon_days
      projected_closing_stock = current_stock − projected_consumption_h
      projected_days_of_cover_at_h = current_stock / (forecast_p50_weekly / 7)
      worst_case_days_of_cover    = current_stock / (forecast_p90_weekly / 7)

      predicted_status:
        if projected_closing_stock <= 0:           "stockout"
        elif projected_days_of_cover_at_h < 7:     "rationing"
        else:                                      "ok"

    Tier alerts: fire if days_of_cover < tier-specific threshold.
    """
    if horizon_days_list is None:
        horizon_days_list = cfg.FORECAST_HORIZONS_DAYS

    snap = pd.Timestamp(snapshot_date)

    # Reduce forecasts to the row at the snapshot week (or first week ≥ snap)
    f = demand_forecasts.copy()
    f["week"] = pd.to_datetime(f["week"])
    f_snap = f[f["week"] >= snap].sort_values(["post_id", "sku", "week"]) \
                                  .groupby(["post_id", "sku"], as_index=False).first()

    # Route probs at snapshot date (one row per pass × horizon)
    r = route_predictions.copy()
    r["date"] = pd.to_datetime(r["date"])
    r_snap = r[r["date"] == snap]
    if len(r_snap) == 0:
        # Fallback to the latest available date <= snap
        latest = r[r["date"] <= snap]["date"].max()
        r_snap = r[r["date"] == latest]

    # Joins
    posts_keep = posts[["id", "served_by", "axis", "band", "troops", "elev_m"]].rename(columns={"id": "post_id"})
    skus_keep  = skus[["sku", "head", "tier"]]

    s = stock_today[["post_id", "sku", "closing_stock", "days_of_cover", "status"]].copy()
    s = s.rename(columns={"closing_stock": "current_stock",
                          "days_of_cover": "current_days_of_cover",
                          "status": "current_status"})

    base = s.merge(f_snap[["post_id", "sku", "p10", "p50", "p90"]], on=["post_id", "sku"], how="inner") \
            .merge(posts_keep, on="post_id", how="left") \
            .merge(skus_keep,  on="sku",     how="left")

    # Daily-rate equivalents from weekly forecasts
    base["daily_p10"] = base["p10"] / 7.0
    base["daily_p50"] = base["p50"] / 7.0
    base["daily_p90"] = base["p90"] / 7.0

    # Projected days_of_cover with median forecast — directly comparable to
    # current_days_of_cover from stock_daily
    base["projected_days_of_cover_p50"] = np.where(
        base["daily_p50"] > 1e-6,
        base["current_stock"] / base["daily_p50"],
        np.inf
    )
    base["projected_days_of_cover_p90"] = np.where(
        base["daily_p90"] > 1e-6,
        base["current_stock"] / base["daily_p90"],
        np.inf
    )

    # Per-horizon snapshots
    out_rows = []
    for h in horizon_days_list:
        chunk = base.copy()
        chunk["horizon_days"] = h
        chunk["projected_consumption_p50"] = chunk["daily_p50"] * h
        chunk["projected_consumption_p90"] = chunk["daily_p90"] * h
        chunk["projected_closing_stock_p50"] = chunk["current_stock"] - chunk["projected_consumption_p50"]
        chunk["projected_closing_stock_p90"] = chunk["current_stock"] - chunk["projected_consumption_p90"]

        # Predicted status — uses P50 (median) by default
        def _pred_status(row):
            if row["projected_closing_stock_p50"] <= cfg.RISK_STATUS_THRESHOLDS["stockout_days_of_cover"]:
                return "stockout"
            if row["projected_days_of_cover_p50"] < cfg.RISK_STATUS_THRESHOLDS["rationing_days_of_cover"]:
                return "rationing"
            return "ok"
        chunk["predicted_status"] = chunk.apply(_pred_status, axis=1)

        # Worst-case (P90 demand) status — what the optimizer should plan for
        def _pred_status_worst(row):
            if row["projected_closing_stock_p90"] <= 0:
                return "stockout"
            if row["projected_days_of_cover_p90"] < cfg.RISK_STATUS_THRESHOLDS["rationing_days_of_cover"]:
                return "rationing"
            return "ok"
        chunk["predicted_status_worstcase"] = chunk.apply(_pred_status_worst, axis=1)

        # Isolation probability per post (one value per post per horizon, but
        # we broadcast to every sku row at that post)
        # Use the closest available route-horizon to h (passes are predicted at
        # 1/3/7/14; for forecast horizons of 7/14/30/90 we use 14 for 30 and 90).
        route_h_to_use = min(cfg.ROUTE_HORIZONS_DAYS, key=lambda x: abs(x - h)) if h <= 14 else max(cfg.ROUTE_HORIZONS_DAYS)
        iso_cache = {}
        def _iso_for_post(post_row):
            pid = post_row["post_id"]
            if pid not in iso_cache:
                # Build minimal post_row for the helper
                iso_cache[pid] = _isolation_probability(post_row, r_snap, route_h_to_use)
            return iso_cache[pid]
        chunk["isolation_probability"] = chunk.apply(_iso_for_post, axis=1)
        chunk["isolation_route_horizon_used"] = route_h_to_use

        # Tier alert: fire if projected_days_of_cover_p50 < tier threshold
        chunk["tier_alert_horizon"] = chunk["tier"].map(cfg.ALERT_HORIZONS).fillna(7)
        chunk["tier_alert_fired"] = chunk["projected_days_of_cover_p50"] < chunk["tier_alert_horizon"]

        # Snapshot id + lineage
        chunk["snapshot_date"] = snap
        chunk["model_version"] = cfg.MODEL_VERSION

        out_rows.append(chunk)

    out = pd.concat(out_rows, ignore_index=True)

    keep = ["snapshot_date", "post_id", "sku", "head", "tier", "axis", "band",
            "horizon_days",
            "current_stock", "current_days_of_cover", "current_status",
            "p10", "p50", "p90",
            "projected_consumption_p50", "projected_consumption_p90",
            "projected_closing_stock_p50", "projected_closing_stock_p90",
            "projected_days_of_cover_p50", "projected_days_of_cover_p90",
            "predicted_status", "predicted_status_worstcase",
            "isolation_probability", "isolation_route_horizon_used",
            "tier_alert_horizon", "tier_alert_fired",
            "model_version"]
    return out[keep]
