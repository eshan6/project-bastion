"""
Project Bastion — Stage 3 risk scorer (v1.1)

Composes the three model outputs into actionable risk objects.

Inputs:
  - current stock balance (from stock_daily, as-of snapshot date)
  - demand forecast (p10/p50/p90 weekly, per post+sku)
  - route disruption probability per (pass, horizon)

Outputs (per post+sku):
  - projected_days_of_cover (steady-state, at the expected burn rate) using
    P50 and P90 demand
  - predicted_status (ok / rationing / stockout) at horizon
  - isolation_risk: P(post becomes isolated within horizon), derived from
                    pass closure probabilities and posts.served_by
  - tier_alert_fired: bool, per masterplan tier thresholds (Tier 1=14d, 2=7d, 3=3d)

The point of this module: collapse three model outputs into one
StockoutRisk row per (post, sku, snapshot_date, horizon). That row is what
the Stage 4 optimizer consumes.

──────────────────────────────────────────────────────────────────────────────
v1.1 CORRECTNESS NOTES (read before changing the cover math)
──────────────────────────────────────────────────────────────────────────────
Two bugs in v1.0 are fixed here. Both fed the Stage 4 optimizer and the alert
loop, so the corrections propagate downstream.

1. DENOMINATOR MISMATCH.
   v1.0 computed `projected_days_of_cover` against the forecaster's daily P50/P90
   rate, while the Stage 2 stock ledger computed `current_days_of_cover`
   (COVER NOW) against `winter_daily_rate_mean` — a static planning rate from the
   AWS plan table. Two different denominators on the same numerator (stock). The
   dashboard placed them side by side, producing the "runway grows by sitting
   still" artifact whenever the planning rate exceeded the model rate.

   FIX: the forecaster's expected (P50) daily rate is now the single estimator of
   expected burn. We RECOMPUTE current_days_of_cover here from that rate so
   COVER NOW and PROJ P50 share one ruler. The ledger's planning-rate cover is
   retained, unmodified, as `current_days_of_cover_planning` for audit / lineage,
   but it is NOT what the cover columns or alerts key off.

   Consequence (accepted deliberately): cover now MOVES as forecasts update tick
   to tick, where the planning-rate version was stable. That is correct — our
   expectation of burn genuinely changes with weather/tempo forecasts.

2. HORIZON WAS A NO-OP FOR COVER.
   v1.0 computed `projected_days_of_cover_p50/p90` ONCE in `base`, before the
   horizon loop, then broadcast the same value to every horizon. Toggling
   7/14/30/90 changed nothing in the cover columns.

   FIX (per founder decision): days-of-cover is STEADY-STATE — stock ÷ expected
   daily rate — and is therefore legitimately horizon-invariant. The forecaster
   predicts a rate, not a depletion path; projecting that rate flat is the only
   honest reading. So cover is computed once and is identical across horizons by
   design. The horizon toggle is dropped from the cover columns upstream (it was
   lying). Horizon is NOT removed from the module — it still drives the things
   that genuinely depend on it: projected_closing_stock, predicted_status
   (stockout/rationing AT horizon), and tier_alert_fired.
──────────────────────────────────────────────────────────────────────────────
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

    NOTE: this returns ONE value per (post, horizon). It is a post-level property
    — the route either opens or it doesn't, independent of SKU. The dashboard
    surfaces it on the post header, not per-SKU, to avoid implying granularity
    that does not exist.
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

    Math (v1.1):
      daily_p50 = forecast_p50_weekly / 7         # expected daily burn
      daily_p90 = forecast_p90_weekly / 7         # worst-case daily burn

      # Steady-state cover — single estimator of expected burn, horizon-invariant.
      current_days_of_cover         = current_stock / daily_p50   # recomputed; this is COVER NOW
      projected_days_of_cover_p50   = current_stock / daily_p50   # == COVER NOW by construction
      projected_days_of_cover_p90   = current_stock / daily_p90

      # Horizon-dependent quantities — these DO scale with h.
      projected_consumption_h    = daily_rate × horizon_days
      projected_closing_stock_h  = current_stock − projected_consumption_h

      predicted_status (at horizon, on P50):
        if projected_closing_stock_p50 <= 0:                 "stockout"
        elif projected_days_of_cover_p50 < rationing_thresh: "rationing"
        else:                                                "ok"

    Tier alerts: fire if projected_days_of_cover_p50 < tier-specific threshold.
    (Steady-state cover, so the alert condition is the same across horizons — by
     design. Horizon-sensitivity for alerts lives in predicted_status, which
     flips to "stockout" once projected_closing_stock crosses zero at that h.)
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

    # Keep the Stage 2 planning-rate cover under a renamed audit column — it is NOT
    # the live cover denominator anymore (see v1.1 note 1), but we retain it for
    # lineage / reconciliation against the ledger.
    s = stock_today[["post_id", "sku", "closing_stock", "days_of_cover", "status"]].copy()
    s = s.rename(columns={"closing_stock": "current_stock",
                          "days_of_cover": "current_days_of_cover_planning",
                          "status": "current_status"})

    base = s.merge(f_snap[["post_id", "sku", "p10", "p50", "p90"]], on=["post_id", "sku"], how="inner") \
            .merge(posts_keep, on="post_id", how="left") \
            .merge(skus_keep,  on="sku",     how="left")

    # Daily-rate equivalents from weekly forecasts — the single estimator of burn.
    base["daily_p10"] = base["p10"] / 7.0
    base["daily_p50"] = base["p50"] / 7.0
    base["daily_p90"] = base["p90"] / 7.0

    # ── Steady-state days-of-cover (horizon-invariant) ───────────────────────
    # COVER NOW is recomputed from the SAME expected (P50) rate the projection
    # uses, so the two columns are one ruler. current_days_of_cover and
    # projected_days_of_cover_p50 are therefore identical by construction; both
    # are emitted so downstream joins/UI keep their column names, and so the
    # reconciliation (planning vs expected) is visible in one row.
    base["current_days_of_cover"] = np.where(
        base["daily_p50"] > 1e-6,
        base["current_stock"] / base["daily_p50"],
        np.inf,
    )
    base["projected_days_of_cover_p50"] = base["current_days_of_cover"]
    base["projected_days_of_cover_p90"] = np.where(
        base["daily_p90"] > 1e-6,
        base["current_stock"] / base["daily_p90"],
        np.inf,
    )

    # Divergence between the planning-rate cover (ledger) and the expected-rate
    # cover (forecaster). Surfaced so an evaluator can see *why* a post's cover
    # differs from the Stage 2 ledger — it's the rate choice, not a data error.
    base["cover_rate_divergence_days"] = (
        base["current_days_of_cover"] - base["current_days_of_cover_planning"]
    )

    # ── Per-horizon snapshots (horizon drives status + closing stock, NOT cover)
    out_rows = []
    rationing_thresh = cfg.RISK_STATUS_THRESHOLDS["rationing_days_of_cover"]
    stockout_thresh  = cfg.RISK_STATUS_THRESHOLDS["stockout_days_of_cover"]

    for h in horizon_days_list:
        chunk = base.copy()
        chunk["horizon_days"] = h

        # Horizon-dependent consumption + closing stock (these legitimately scale)
        chunk["projected_consumption_p50"]   = chunk["daily_p50"] * h
        chunk["projected_consumption_p90"]   = chunk["daily_p90"] * h
        chunk["projected_closing_stock_p50"] = chunk["current_stock"] - chunk["projected_consumption_p50"]
        chunk["projected_closing_stock_p90"] = chunk["current_stock"] - chunk["projected_consumption_p90"]

        # Predicted status at horizon — uses P50 (median) by default.
        # Vectorised; horizon-sensitive via projected_closing_stock_p50.
        chunk["predicted_status"] = np.select(
            [
                chunk["projected_closing_stock_p50"] <= stockout_thresh,
                chunk["projected_days_of_cover_p50"] < rationing_thresh,
            ],
            ["stockout", "rationing"],
            default="ok",
        )

        # Worst-case (P90 demand) status — what the optimizer should plan for.
        chunk["predicted_status_worstcase"] = np.select(
            [
                chunk["projected_closing_stock_p90"] <= 0,
                chunk["projected_days_of_cover_p90"] < rationing_thresh,
            ],
            ["stockout", "rationing"],
            default="ok",
        )

        # Isolation probability per post (one value per post per horizon),
        # broadcast to every sku row at that post. It is a POST-LEVEL property;
        # the UI shows it on the post header, not per-SKU.
        # Passes are predicted at 1/3/7/14; for forecast horizons of 7/14/30/90
        # we use 14 for 30 and 90 (the longest route horizon we trained).
        route_h_to_use = min(cfg.ROUTE_HORIZONS_DAYS, key=lambda x: abs(x - h)) if h <= 14 else max(cfg.ROUTE_HORIZONS_DAYS)
        iso_cache = {}
        def _iso_for_post(post_row, _cache=iso_cache, _rh=route_h_to_use):
            pid = post_row["post_id"]
            if pid not in _cache:
                _cache[pid] = _isolation_probability(post_row, r_snap, _rh)
            return _cache[pid]
        chunk["isolation_probability"] = chunk.apply(_iso_for_post, axis=1)
        chunk["isolation_route_horizon_used"] = route_h_to_use

        # Tier alert: fire if steady-state projected_days_of_cover_p50 < tier
        # threshold. Steady-state, so this condition is horizon-invariant by
        # design (note 2); horizon-sensitivity for alerting lives in
        # predicted_status flipping to "stockout" at that h.
        chunk["tier_alert_horizon"] = chunk["tier"].map(cfg.ALERT_HORIZONS).fillna(7)
        chunk["tier_alert_fired"] = chunk["projected_days_of_cover_p50"] < chunk["tier_alert_horizon"]

        # Snapshot id + lineage
        chunk["snapshot_date"] = snap
        chunk["model_version"] = cfg.MODEL_VERSION

        out_rows.append(chunk)

    out = pd.concat(out_rows, ignore_index=True)

    keep = ["snapshot_date", "post_id", "sku", "head", "tier", "axis", "band",
            "horizon_days",
            "current_stock",
            "current_days_of_cover",              # expected-rate cover (live ruler)
            "current_days_of_cover_planning",     # ledger planning-rate cover (audit)
            "cover_rate_divergence_days",         # expected − planning (why they differ)
            "current_status",
            "p10", "p50", "p90",
            "projected_consumption_p50", "projected_consumption_p90",
            "projected_closing_stock_p50", "projected_closing_stock_p90",
            "projected_days_of_cover_p50", "projected_days_of_cover_p90",
            "predicted_status", "predicted_status_worstcase",
            "isolation_probability", "isolation_route_horizon_used",
            "tier_alert_horizon", "tier_alert_fired",
            "model_version"]
    return out[keep]
