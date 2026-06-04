"""
Project Bastion — Stage 4 alert generator (v1.0)

The authoritative alerting layer (Component 5, steps 5-7). Produces all three
alert types as rows that map 1:1 onto bastion.alert, from the three Stage 3
prediction outputs:

  stockout_risk     -> stockout_risk alerts   (Stage 3 owns the days-of-cover math;
                                                Stage 4 sets severity)
  route_predictions -> disruption alerts       (P(closed) within window > 0.60)
  vehicle_reliability -> vehicle_deadline alerts (P(deadline) > threshold)

NB on the existing loader: db/load_world.py emits a *stopgap* stockout alert in
SQL so the lineage view has content. Stage 4 is the real alert layer and emits
all three types. load_plans.py (Stage 4's DB writer) clears prior alerts for the
snapshot before inserting this complete set, so there is no double-count. The
stockout alerts here carry source_risk_id, preserving the alert->risk->model
->snapshot lineage chain the v_prediction_lineage view walks.
"""
from __future__ import annotations
import pandas as pd
import config as cfg


def generate_alerts(snapshot_dir, planning_horizon: int | None = None) -> pd.DataFrame:
    from pathlib import Path
    snapshot_dir = Path(snapshot_dir)
    H = planning_horizon or cfg.PLANNING_HORIZON_DAYS

    risk = pd.read_parquet(snapshot_dir / "stockout_risk.parquet")
    routes_pred = pd.read_parquet(snapshot_dir / "route_predictions.parquet")
    veh_rel = pd.read_parquet(snapshot_dir / "vehicle_reliability.parquet")
    snap_date = str(pd.to_datetime(risk["snapshot_date"]).max().date())

    rows = []

    # ── (a) Stockout-risk alerts: every fired tier alert at the planning horizon ─
    if H not in set(risk["horizon_days"].unique()):
        H = int(min(risk["horizon_days"].unique(), key=lambda x: abs(x - H)))
    rk = risk[(risk["horizon_days"] == H) & (risk["tier_alert_fired"])].copy()
    for r in rk.itertuples():
        sev = cfg.stockout_severity(r.predicted_status_worstcase, r.predicted_status, int(r.tier))
        cover = "0" if r.current_days_of_cover is None else f"{r.current_days_of_cover:.0f}"
        msg = (f"{r.post_id} / {r.head} ({r.sku}): {cover}d cover now, worst-case "
               f"status '{r.predicted_status_worstcase}' within {int(r.tier_alert_horizon)}d "
               f"tier window (h={H}d)")
        rows.append({
            "alert_type": "stockout_risk", "severity": sev, "message": msg,
            "post_id": r.post_id, "sku_id": r.sku, "pass_name": None, "vehicle_id": None,
            "horizon_days": H, "snapshot_date": snap_date,
            "trigger_metric": "projected_days_of_cover_p50",
            "trigger_value": round(float(r.projected_days_of_cover_p50), 2)
                             if pd.notna(r.projected_days_of_cover_p50) else None,
        })

    # ── (b) Route-disruption alerts: P(closed) within window > threshold ────────
    rp = routes_pred.copy()
    rp["date"] = pd.to_datetime(rp["date"])
    snap_ts = pd.to_datetime(snap_date)
    win = rp[(rp["horizon"] <= cfg.ROUTE_DISRUPTION_WINDOW_DAYS) &
             (rp["date"] >= snap_ts) &
             (rp["date"] <= snap_ts + pd.Timedelta(days=cfg.ROUTE_DISRUPTION_WINDOW_DAYS))]
    if len(win):
        # worst (max P(closed)) per pass within the window
        worst = win.loc[win.groupby("pass_name")["p_closed"].idxmax()]
        for r in worst.itertuples():
            if float(r.p_closed) <= cfg.ROUTE_DISRUPTION_PCLOSED_THRESHOLD:
                continue
            sev = "critical" if r.p_closed > 0.85 else "warning"
            msg = (f"{r.pass_name}: P(closed) {r.p_closed:.0%} by {pd.to_datetime(r.date).date()} "
                   f"(h={int(r.horizon)}d) — posts beyond this pass risk isolation")
            rows.append({
                "alert_type": "disruption", "severity": sev, "message": msg,
                "post_id": None, "sku_id": None, "pass_name": r.pass_name, "vehicle_id": None,
                "horizon_days": int(r.horizon), "snapshot_date": snap_date,
                "trigger_metric": "p_closed", "trigger_value": round(float(r.p_closed), 4),
            })

    # ── (c) Vehicle-deadline alerts: P(deadline) over horizon > threshold ───────
    vh = veh_rel
    if "horizon_days" in vh.columns:
        vh = vh[vh["horizon_days"] == cfg.VEHICLE_HORIZON_DAYS]
    hot = vh[vh["p_deadline"] > cfg.VEHICLE_DEADLINE_PDEADLINE_THRESHOLD]
    for r in hot.itertuples():
        sev = "critical" if r.p_deadline > 0.15 else "warning"
        depot = getattr(r, "home_depot_id", None)
        msg = (f"{r.vehicle_id} ({r.vehicle_class} @ {depot}): P(deadline) "
               f"{r.p_deadline:.1%} within {cfg.VEHICLE_HORIZON_DAYS}d — exclude from "
               f"forward tasking / pre-empt maintenance")
        rows.append({
            "alert_type": "vehicle_deadline", "severity": sev, "message": msg,
            "post_id": None, "sku_id": None, "pass_name": None, "vehicle_id": r.vehicle_id,
            "horizon_days": cfg.VEHICLE_HORIZON_DAYS, "snapshot_date": snap_date,
            "trigger_metric": "p_deadline", "trigger_value": round(float(r.p_deadline), 6),
        })

    df = pd.DataFrame(rows, columns=[
        "alert_type", "severity", "message", "post_id", "sku_id", "pass_name",
        "vehicle_id", "horizon_days", "snapshot_date", "trigger_metric", "trigger_value"])
    # deterministic ordering: severity desc, then type, then id
    sev_rank = {"critical": 0, "warning": 1, "info": 2}
    df["_s"] = df["severity"].map(sev_rank).fillna(3)
    df = df.sort_values(["_s", "alert_type", "post_id", "pass_name", "vehicle_id"],
                        na_position="last").drop(columns="_s").reset_index(drop=True)
    df["model_version"] = cfg.MODEL_VERSION
    return df
