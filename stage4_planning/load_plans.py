#!/usr/bin/env python3
"""
Project Bastion — Stage 4 loader (plans + alerts -> Postgres ontology).

Writes the Stage 4 planning outputs into the live Supabase ontology defined by
db/001_ontology.sql, with full lineage. Mirrors db/load_world.py conventions
(psycopg2, execute_values, DATABASE_URL env, snapshot-grain idempotency).

Reads:
  DATABASE_URL    — Postgres connection string (Supabase pooler URL)
  BASTION_ROOT    — repo root (default ".")
  BASTION_SNAPSHOT_DIR — Stage 3 snapshot dir holding stage4/ outputs
                          (default: stage3_models/output/snapshot_2024-12-15)

Behaviour:
  - Requires the world snapshot to already exist (run db/load_world.py first).
  - Registers an 'optimizer' model_version (kind enum already in schema).
  - Idempotent + authoritative: deletes any prior resupply_plan rows for this
    snapshot+model (legs cascade) and ALL alerts for this snapshot, then inserts
    the full Stage 4 set. This supersedes the stopgap stockout alerts that
    db/load_world.py inserts, so there is exactly one authoritative alert set.
  - Re-links alerts to their source rows (alert -> stockout_risk / route_prediction)
    so bastion.v_prediction_lineage stays whole.
"""
import os
import json
import uuid
from pathlib import Path
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values

ROOT = Path(os.environ.get("BASTION_ROOT", "."))
SNAP_DIR = Path(os.environ.get(
    "BASTION_SNAPSHOT_DIR",
    ROOT / "stage3_models" / "output" / "snapshot_2024-12-15"))
STAGE4_DIR = SNAP_DIR / "stage4"

SNAPSHOT_LABEL = "canonical_seed42"
SNAPSHOT_DATE = "2024-12-15"
MODEL_VERSION_NAME = "stage4-v1.1"


def pq(name):
    return pd.read_parquet(STAGE4_DIR / name)


def main():
    if not STAGE4_DIR.exists():
        raise SystemExit(f"No Stage 4 outputs at {STAGE4_DIR}. Run plan_service.py first.")

    plans = pq("resupply_plans.parquet")
    legs = pq("resupply_plan_legs.parquet")
    alerts = pq("alerts.parquet")
    diag = json.loads((STAGE4_DIR / "planning_diagnostics.json").read_text())

    dsn = os.environ["DATABASE_URL"]
    conn = psycopg2.connect(dsn); conn.autocommit = False
    cur = conn.cursor()

    # ── snapshot must exist (world loaded first) ──────────────────────────────
    cur.execute("SELECT snapshot_id FROM bastion_provenance.data_snapshot "
                "WHERE label=%s AND as_of_date=%s", (SNAPSHOT_LABEL, SNAPSHOT_DATE))
    row = cur.fetchone()
    if not row:
        conn.close()
        raise SystemExit("World snapshot not found — run db/load_world.py before load_plans.py.")
    snap = row[0]

    # ── register optimizer model_version (idempotent) ─────────────────────────
    metrics = {"plan_comparison": diag.get("plan_comparison"),
               "reachability": diag.get("reachability", {}).get("road_isolated_at_risk_posts"),
               "horizon_days": diag.get("planning_horizon_days")}
    params = {"planning_horizon_days": diag.get("planning_horizon_days"),
              "reserve_days": 7, "coverage_weight": 1e6,
              "solver": "CBC", "objectives": ["min_cost", "min_time", "min_risk", "balanced"]}
    cur.execute(
        "INSERT INTO bastion_provenance.model_version (kind,name,algorithm,params,metrics,trained_on_snapshot,notes) "
        "VALUES ('optimizer',%s,%s,%s,%s,%s,%s) "
        "ON CONFLICT (kind,name) DO UPDATE SET metrics=EXCLUDED.metrics, params=EXCLUDED.params "
        "RETURNING model_version_id",
        (MODEL_VERSION_NAME, "OR-Tools MIP (capacitated assignment, coverage-dominant, 4 objectives)",
         json.dumps(params), json.dumps(metrics), snap,
         "Stage 4 planner. Plans P90 worst-case deficit, anticipatory dispatch; isolation surfaced as shortfall."))
    mv_opt = cur.fetchone()[0]

    # ── idempotent supersede: clear prior plans (this snapshot+model) + alerts ─
    cur.execute("DELETE FROM bastion.resupply_plan WHERE snapshot_id=%s AND model_version_id=%s",
                (snap, mv_opt))
    cur.execute("DELETE FROM bastion.alert WHERE snapshot_id=%s", (snap,))

    # ── resupply_plan ─────────────────────────────────────────────────────────
    plan_vals = [(p.plan_id, p.objective, float(p.total_cost), float(p.total_time_hours),
                  float(p.aggregate_risk), mv_opt, snap) for p in plans.itertuples()]
    execute_values(cur,
        "INSERT INTO bastion.resupply_plan "
        "(plan_id,objective,total_cost,total_time_hours,aggregate_risk,model_version_id,snapshot_id) VALUES %s",
        plan_vals)

    # ── resupply_plan_leg ─────────────────────────────────────────────────────
    if len(legs):
        leg_vals = [(l.plan_id, int(l.seq), l.vehicle_id, l.route_id, l.sku_id,
                     float(l.qty), str(l.depart_date)[:10], float(l.expected_cost), float(l.expected_risk))
                    for l in legs.itertuples()]
        execute_values(cur,
            "INSERT INTO bastion.resupply_plan_leg "
            "(plan_id,seq,vehicle_id,route_id,sku_id,qty,depart_date,expected_cost,expected_risk) VALUES %s",
            leg_vals)

    # ── alerts (authoritative set; re-link source rows for lineage) ───────────
    # stockout_risk alerts -> source_risk_id via (post,sku,horizon,snapshot)
    n_stock = n_route = n_veh = 0
    for a in alerts.itertuples():
        if a.alert_type == "stockout_risk":
            cur.execute("""
                INSERT INTO bastion.alert
                  (alert_type,severity,message,post_id,sku_id,source_risk_id,snapshot_id)
                SELECT 'stockout_risk'::bastion.alert_type, %s::bastion.alert_severity, %s, %s, %s, r.risk_id, %s
                FROM bastion.stockout_risk r
                WHERE r.snapshot_id=%s AND r.post_id=%s AND r.sku_id=%s AND r.horizon_days=%s
                ORDER BY r.created_at DESC LIMIT 1
            """, (a.severity, a.message, a.post_id, a.sku_id, snap,
                  snap, a.post_id, a.sku_id, int(a.horizon_days)))
            n_stock += cur.rowcount
        elif a.alert_type == "disruption":
            cur.execute("""
                INSERT INTO bastion.alert
                  (alert_type,severity,message,pass_name,source_route_prediction_id,snapshot_id)
                SELECT 'disruption'::bastion.alert_type, %s::bastion.alert_severity, %s, %s, rp.prediction_id, %s
                FROM bastion.route_prediction rp
                WHERE rp.snapshot_id=%s AND rp.pass_name=%s
                ORDER BY rp.p_closed DESC LIMIT 1
            """, (a.severity, a.message, a.pass_name, snap, snap, a.pass_name))
            n_route += cur.rowcount
        elif a.alert_type == "vehicle_deadline":
            cur.execute("""
                INSERT INTO bastion.alert
                  (alert_type,severity,message,vehicle_id,snapshot_id)
                VALUES ('vehicle_deadline'::bastion.alert_type, %s::bastion.alert_severity, %s, %s, %s)
            """, (a.severity, a.message, a.vehicle_id, snap))
            n_veh += cur.rowcount

    conn.commit()
    print(f"STAGE4 LOAD OK  snapshot={snap}  plans={len(plans)}  legs={len(legs)}  "
          f"alerts(stockout/route/veh)={n_stock}/{n_route}/{n_veh}")
    conn.close()


if __name__ == "__main__":
    main()
