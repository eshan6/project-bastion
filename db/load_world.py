#!/usr/bin/env python3
"""
Project Bastion — Stage 1 loader.
Loads the Stage 2 synthetic world (parquet) and Stage 3 predictions into the
Postgres ontology defined by 001_ontology.sql, with full lineage.

Run by CI (GitHub Actions) against Supabase. Reads:
  DATABASE_URL   — Postgres connection string (Supabase pooler URL)
  BASTION_ROOT   — repo root containing stage2_world/ and stage3_models/
Idempotent at the snapshot grain: a re-run for the same snapshot label is a
no-op (it detects the existing snapshot and exits).
"""
import os, io, json, sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = os.environ.get("BASTION_ROOT", ".")
S2 = os.path.join(ROOT, "stage2_world", "data")
S3 = os.path.join(ROOT, "stage3_models")
SNAP_OUT = os.path.join(S3, "output", "snapshot_2024-12-15")
SNAPSHOT_LABEL = "canonical_seed42"
SNAPSHOT_DATE = "2024-12-15"
# Optional: only load dated rows on/after this ISO date into the live DB.
# Full 3-year parquet remains the regeneration source + training record.
# The trailing window keeps the live DB inside the Supabase free-tier 500MB cap.
LOAD_FROM = os.environ.get("BASTION_LOAD_FROM")  # e.g. "2024-01-01"

def window(df, col):
    return df[df[col].astype(str) >= LOAD_FROM] if LOAD_FROM else df

def pq(d, f): return pd.read_parquet(os.path.join(d, f))

def arr(v):
    if v is None or (isinstance(v, float) and pd.isna(v)): return "{}"
    return "{" + ",".join('"%s"' % str(x).replace('"', '\\"') for x in list(v)) + "}"

def copy_df(cur, table, df, columns):
    buf = io.StringIO()
    df[columns].to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)
    cur.copy_expert(
        "COPY %s (%s) FROM STDIN WITH (FORMAT csv, NULL '')" % (table, ",".join(columns)),
        buf,
    )

def main():
    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn); conn.autocommit = False
    cur = conn.cursor()

    # ---- idempotency guard -------------------------------------------------
    cur.execute("SELECT snapshot_id FROM bastion_provenance.data_snapshot WHERE label=%s AND as_of_date=%s",
                (SNAPSHOT_LABEL, SNAPSHOT_DATE))
    if cur.fetchone():
        print("snapshot already loaded; nothing to do."); conn.close(); return

    # ---- anchor sources (catalogue; domain rows stay synthetic_inferred) ---
    sources = [
        ("imd_climatology", "IMD daily climatology priors", "weather_closures", "tier_1_authoritative"),
        ("cag_audits", "CAG audit reports (consumption/vehicle priors)", "scales_doctrine", "tier_1_authoritative"),
        ("news_pass_closures", "News archive pass-closure patterns", "weather_closures", "tier_3_journalistic"),
    ]
    execute_values(cur,
        "INSERT INTO bastion_provenance.sources (source_id,name,category,realism_tier) VALUES %s "
        "ON CONFLICT (source_id) DO NOTHING", sources)

    # ---- data_snapshot -----------------------------------------------------
    vr = json.load(open(os.path.join(ROOT, "stage2_world", "validation_report.json")))
    lin = json.load(open(os.path.join(SNAP_OUT, "lineage.json")))
    row_counts = {"stage2_total": vr.get("rows_total"), **lin.get("row_counts", {})}
    cur.execute(
        "INSERT INTO bastion_provenance.data_snapshot (label,seed,as_of_date,generator_version,horizon_days,row_counts,notes) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING snapshot_id",
        (SNAPSHOT_LABEL, int(vr.get("seed", 42)), SNAPSHOT_DATE, "stage2_world", int(vr.get("horizon_days", 1096)),
         json.dumps(row_counts),
         "Seed-42 canonical world, 2022-01-01..2024-12-31. Weather calibrated to IMD priors; "
         "closures to news/weather patterns; vehicle survival to CAG-style priors. "
         "Domain rows are synthetic_inferred (calibration is parameter-level, not row-level)."))
    snap = cur.fetchone()[0]

    # ---- model_version (3) from honest eval metrics ------------------------
    ed = json.load(open(os.path.join(S3, "reports", "evaluation_demand.json")))
    er = json.load(open(os.path.join(S3, "reports", "evaluation_route.json")))
    ev = json.load(open(os.path.join(S3, "reports", "evaluation_vehicle.json")))
    def mv(kind, name, algo, params, metrics, notes):
        cur.execute(
            "INSERT INTO bastion_provenance.model_version (kind,name,algorithm,params,metrics,trained_on_snapshot,notes) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING model_version_id",
            (kind, name, algo, json.dumps(params), json.dumps(metrics), snap, notes))
        return cur.fetchone()[0]
    mv_demand = mv("demand_forecast", "stage3-v1.0", "XGBoost quantile (18 band×head slices)",
                   {"n_slices": ed.get("n_slices_trained"), "train_end": ed.get("train_end")},
                   {"test_window": ed.get("test_window"), "n_slices": ed.get("n_slices_trained")},
                   "Per-slice MAPE/pinball/calibration offsets in evaluation_demand.json")
    mv_route = mv("route_availability", "stage3-v1.0", "Gradient-boosted classifier per pass×horizon",
                  {"n_models": er.get("n_models_trained"), "train_end": er.get("train_end")},
                  {"test_window": er.get("test_window"), "n_models": er.get("n_models_trained")},
                  "Per-pass AUC/Brier in evaluation_route.json")
    mv_veh = mv("vehicle_reliability", "stage3-v1.0", ev.get("scorer_kind", "rule_weibull_altitude_v1"),
                {"horizon_days": ev.get("horizon_days"), "step_days": ev.get("step_days")},
                {"brier": ev.get("brier"), "brier_skill_score_vs_baseline": ev.get("brier_skill_score_vs_baseline"),
                 "actual_failure_rate": ev.get("actual_failure_rate"),
                 "predicted_failure_rate_mean": ev.get("predicted_failure_rate_mean")},
                "Rule-based Weibull scorer; weak signal vs constant baseline, reported honestly.")

    # ---- SKUs --------------------------------------------------------------
    sku = pq(S2, "skus.parquet").rename(columns={"sku": "sku_id"})
    sku["provenance_grade"] = "C"; sku["synthetic_inferred"] = True
    sku["provenance_note"] = "Stage 2 generated; calibrated to CAG/RTI consumption priors at parameter level."
    copy_df(cur, "bastion.sku", sku,
            ["sku_id","head","name","base_per_soldier_day","shelf_life_days","tier",
             "weather_sensitivity","provenance_grade","synthetic_inferred","provenance_note"])

    # ---- depots (is_depot subset) then posts (all nodes) -------------------
    posts = pq(S2, "posts.parquet").rename(columns={"id": "post_id"})
    posts["wkt"] = "SRID=4326;POINT(" + posts["lon"].astype(str) + " " + posts["lat"].astype(str) + ")"
    dep = posts[posts["is_depot"]].copy()
    dep["provenance_grade"] = "C"; dep["synthetic_inferred"] = True
    execute_values(cur,
        "INSERT INTO bastion.depot (depot_id,name,location,elev_m,axis,provenance_grade,synthetic_inferred) VALUES %s",
        list(dep[["post_id","name","wkt","elev_m","axis","provenance_grade","synthetic_inferred"]].itertuples(index=False, name=None)))
    posts["served_by_pg"] = posts["served_by"].apply(arr)
    posts["provenance_grade"] = "C"; posts["synthetic_inferred"] = True
    posts["provenance_note"] = "Stage 2 generated node; AOR publicly documented, position illustrative."
    execute_values(cur,
        "INSERT INTO bastion.post (post_id,name,band,axis,elev_m,troops,location,is_depot,has_air_resupply,"
        "served_by,parent_depot_id,provenance_grade,synthetic_inferred,provenance_note) VALUES %s",
        list(posts[["post_id","name","band","axis","elev_m","troops","wkt","is_depot","has_air_resupply",
                    "served_by_pg","serving_depot_id","provenance_grade","synthetic_inferred","provenance_note"]]
             .itertuples(index=False, name=None)))

    # ---- passes ------------------------------------------------------------
    psd = pq(S2, "pass_status_daily.parquet")
    passes = sorted(psd["pass_name"].unique())
    execute_values(cur, "INSERT INTO bastion.pass (pass_name) VALUES %s ON CONFLICT DO NOTHING",
                   [(p,) for p in passes])

    # ---- routes + segments -------------------------------------------------
    routes = pq(S2, "routes.parquet").rename(columns={"origin_id": "from_id", "destination_id": "to_id"})
    routes["passes_pg"] = routes["passes_crossed"].apply(arr)
    routes["provenance_grade"] = "C"; routes["synthetic_inferred"] = True
    execute_values(cur,
        "INSERT INTO bastion.route (route_id,from_id,to_id,distance_km,elev_max_m,route_type,axis,"
        "passes_crossed,provenance_grade,synthetic_inferred) VALUES %s",
        list(routes[["route_id","from_id","to_id","distance_km","elev_max_m","route_type","axis",
                     "passes_pg","provenance_grade","synthetic_inferred"]].itertuples(index=False, name=None)))
    segs = []
    for _, r in routes.iterrows():
        for i, pn in enumerate(list(r["passes_crossed"]) if r["passes_crossed"] is not None else []):
            segs.append((f"{r['route_id']}-S{i}", r["route_id"], i, pn))
    if segs:
        execute_values(cur,
            "INSERT INTO bastion.route_segment (segment_id,route_id,seq,pass_name) VALUES %s", segs)

    # ---- vehicle classes + vehicles ---------------------------------------
    veh = pq(S2, "vehicles.parquet")
    vclass = veh.groupby("vehicle_class")["payload_tons"].first().reset_index()
    execute_values(cur,
        "INSERT INTO bastion.vehicle_class (class_id,payload_tons,provenance_grade,synthetic_inferred) VALUES %s",
        [(c, float(p), "C", True) for c, p in vclass.itertuples(index=False, name=None)])
    copy_df(cur, "bastion.vehicle",
            veh.rename(columns={"vehicle_class": "class_id"}),
            ["vehicle_id","class_id","payload_tons","home_depot_id","initial_age_days","weibull_shape","weibull_scale_days"])

    # ---- tempo, wd events, pass status daily -------------------------------
    copy_df(cur, "bastion.tempo_daily", window(pq(S2, "tempo_daily.parquet"),"date"), ["date","tempo_level"])
    copy_df(cur, "bastion.wd_event", pq(S2, "wd_events.parquet"),
            ["event_id","start_date","duration_days","precip_mult","temp_drop_c","type"])
    copy_df(cur, "bastion.pass_status_daily", window(psd,"date"), ["pass_name","date","is_open"])

    # ---- weather, consumption, stock (the big ones) ------------------------
    w = pq(S2, "weather_daily.parquet").rename(columns={"date": "obs_date"}); w = window(w,"obs_date"); w["snapshot_id"] = snap
    copy_df(cur, "bastion.weather_observation", w,
            ["post_id","obs_date","t_max_c","t_min_c","t_mean_c","precip_mm","is_snow","is_wd_active","anchor_name","snapshot_id"])
    c = pq(S2, "consumption_daily.parquet").rename(columns={"sku": "sku_id", "date": "event_date"}); c = window(c,"event_date"); c["snapshot_id"] = snap
    copy_df(cur, "bastion.consumption_event", c,
            ["post_id","sku_id","event_date","qty_consumed","tempo","is_isolated","t_mean_c","snapshot_id"])
    s = pq(S2, "stock_daily.parquet").rename(columns={"sku": "sku_id", "date": "as_of_date"}); s = window(s,"as_of_date"); s["snapshot_id"] = snap
    copy_df(cur, "bastion.stock_level", s,
            ["post_id","sku_id","as_of_date","opening_stock","aws_receipt","routine_receipt","nominal_consumption",
             "consumption","spoilage","unmet_demand","closing_stock","days_of_cover","status","snapshot_id"])

    # ---- predictions: demand, route, vehicle, stockout_risk ----------------
    df = pq(SNAP_OUT, "demand_forecasts.parquet").rename(columns={"sku": "sku_id", "week": "target_week"})
    df["model_version_id"] = mv_demand; df["snapshot_id"] = snap
    cross = int(((df["p10"] > df["p50"]) | (df["p50"] > df["p90"])).sum())
    copy_df(cur, "bastion.demand_forecast", df,
            ["post_id","sku_id","target_week","band","head","p10","p50","p90","model_version_id","snapshot_id"])

    rp = pq(SNAP_OUT, "route_predictions.parquet").rename(columns={"date": "target_date", "horizon": "horizon_days"})
    rp["model_version_id"] = mv_route; rp["snapshot_id"] = snap
    copy_df(cur, "bastion.route_prediction", rp,
            ["pass_name","target_date","horizon_days","p_open","p_closed","model_version_id","snapshot_id"])

    vr3 = pq(SNAP_OUT, "vehicle_reliability.parquet")
    vr3["model_version_id"] = mv_veh; vr3["snapshot_id"] = snap
    copy_df(cur, "bastion.vehicle_reliability", vr3,
            ["vehicle_id","snapshot_date","horizon_days","age_days_at_asof","events_to_date","frac_high_altitude",
             "effective_age_days","reliability_score","p_deadline","scorer_kind","model_version_id","snapshot_id"])
    execute_values(cur,
        "UPDATE bastion.vehicle AS v SET reliability_score=d.rs, p_deadline=d.pd "
        "FROM (VALUES %s) AS d(vid,rs,pd) WHERE v.vehicle_id=d.vid",
        list(vr3[vr3["horizon_days"] == 7][["vehicle_id","reliability_score","p_deadline"]].itertuples(index=False, name=None)))

    sr = pq(SNAP_OUT, "stockout_risk.parquet").rename(columns={"sku": "sku_id"})
    sr["model_version_id"] = mv_demand; sr["snapshot_id"] = snap
    sr_cols = ["snapshot_date","post_id","sku_id","head","tier","axis","band","horizon_days","current_stock",
               "current_days_of_cover","current_status","p10","p50","p90","projected_consumption_p50",
               "projected_consumption_p90","projected_closing_stock_p50","projected_closing_stock_p90",
               "projected_days_of_cover_p50","projected_days_of_cover_p90","predicted_status",
               "predicted_status_worstcase","isolation_probability","isolation_route_horizon_used",
               "tier_alert_horizon","tier_alert_fired","model_version_id","snapshot_id"]
    copy_df(cur, "bastion.stockout_risk", sr, sr_cols)

    # ---- disruption_event: ACTUAL closures + vehicle deadlines -------------
    pc = pq(S2, "pass_closures.parquet")
    execute_values(cur,
        "INSERT INTO bastion.disruption_event (kind,pass_name,start_date,end_date,duration_days,detail,snapshot_id) VALUES %s",
        [("pass_closure", r.pass_name, r.start_date, r.end_date, int(r.duration_days),
          json.dumps({"closure_type": (None if pd.isna(r.closure_type) else r.closure_type),
                      "winter_season": (None if pd.isna(r.winter_season) else r.winter_season)}), snap)
         for r in pc.itertuples()])
    ve = pq(S2, "vehicle_events.parquet")
    execute_values(cur,
        "INSERT INTO bastion.disruption_event (kind,vehicle_id,start_date,end_date,duration_days,detail,snapshot_id) VALUES %s",
        [("vehicle_deadline", r.vehicle_id, r.deadline_date, r.return_date, int(r.repair_days),
          json.dumps({"repair_location": (None if pd.isna(r.repair_location) else r.repair_location),
                      "winter_flag": bool(r.winter_flag)}), snap)
         for r in ve.itertuples()])

    # ---- alerts from fired tier risks (so lineage view has content) --------
    cur.execute("""
        INSERT INTO bastion.alert (alert_type,severity,message,post_id,sku_id,source_risk_id,snapshot_id)
        SELECT 'stockout_risk'::bastion.alert_type,
               (CASE WHEN r.predicted_status_worstcase='stockout' THEN 'critical'
                    WHEN r.predicted_status='rationing' THEN 'warning' ELSE 'info' END)::bastion.alert_severity,
               r.post_id||' / '||r.head||' ('||r.sku_id||'): cover '||
               ROUND(r.current_days_of_cover)::text||'d, projected status '||r.predicted_status||
               ' within '||r.tier_alert_horizon::text||'d tier window',
               r.post_id, r.sku_id, r.risk_id, r.snapshot_id
        FROM bastion.stockout_risk r
        WHERE r.tier_alert_fired = TRUE AND r.snapshot_id = %s
    """, (snap,))
    n_alerts = cur.rowcount

    conn.commit()
    print(f"LOAD OK  snapshot={snap}  alerts={n_alerts}  demand_quantile_crossings={cross}")
    conn.close()

if __name__ == "__main__":
    main()
