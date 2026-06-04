"""
Project Bastion — Stage 4 plan service (v1.0)

Stage 4's orchestrator (analog of Stage 3 predict_service.run_snapshot). Given a
Stage 3 snapshot dir, it:
  1. assembles the optimizer bundle  (inputs.load_bundle)
  2. solves all four objectives      (optimizer.solve_all, warm-started)
  3. generates the alert set         (alerts.generate_alerts)
  4. writes, into <snapshot>/stage4/:
        resupply_plans.parquet        one row per (objective) plan + headline metrics
        resupply_plan_legs.parquet    one row per (plan, vehicle, sku) leg
        alerts.parquet                all three alert types
        planning_diagnostics.json     the decision-focused readout (isolation,
                                       binding constraints, plan comparison matrix)
        lineage.json                  model_version + snapshot lineage stamp

The parquet schemas mirror bastion.resupply_plan / resupply_plan_leg / alert so
load_plans.py is a 1:1 passthrough into the live ontology.
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone
import pandas as pd

import config as cfg
import inputs
import optimizer
import alerts as alerts_mod


def run_plan(snapshot_dir: str | Path,
             planning_horizon: int | None = None,
             out_dir: Path | None = None) -> dict:
    snapshot_dir = Path(snapshot_dir)
    H = planning_horizon or cfg.PLANNING_HORIZON_DAYS
    out_dir = out_dir or (snapshot_dir / "stage4")
    out_dir.mkdir(exist_ok=True, parents=True)

    print(f"\n══ Stage 4 planning: {snapshot_dir.name}  (horizon {H}d) ══")
    t0 = time.time()

    # 1. Bundle ----------------------------------------------------------------
    b = inputs.load_bundle(snapshot_dir, planning_horizon=H)
    d = b.diagnostics
    print(f"  at-risk posts: {d['n_at_risk_posts']}   deficit: {d['total_deficit_tonnes']} t   "
          f"eligible vehicles: {d['eligible_vehicles']}")
    if d["n_isolated_legs"]:
        print(f"  ⚠ road-isolated at-risk posts (path P(open) < "
              f"{cfg.PATH_FEASIBILITY_MIN}): {d['n_isolated_legs']}")

    # 2. Optimize (4 objectives, warm-started) ---------------------------------
    results = optimizer.solve_all(b)

    generated_at = datetime.now(timezone.utc).isoformat()
    snap_date = b.snapshot_date
    lineage = {
        "model_version": cfg.MODEL_VERSION,
        "snapshot_date": snap_date,
        "planning_horizon_days": H,
        "generated_at": generated_at,
        "data_snapshot_seed": cfg.DATA_SNAPSHOT_SEED,
    }

    # 3. Assemble plan + leg rows ----------------------------------------------
    plan_rows, leg_rows = [], []
    plan_compare = []
    # Deterministic plan_id: stable across reruns for the same snapshot+objective+model.
    plan_ns = uuid.uuid5(uuid.NAMESPACE_URL, "bastion/stage4/resupply_plan")
    for obj in cfg.OBJECTIVES:
        res = results[obj]
        plan_id = str(uuid.uuid5(plan_ns, f"{snap_date}:{H}:{cfg.MODEL_VERSION}:{obj}"))
        plan_rows.append({
            "plan_id": plan_id, "objective": obj, "status": res["status"],
            "total_cost": res["total_cost"], "total_time_hours": res["total_time_hours"],
            "aggregate_risk": res["aggregate_risk"],
            "expected_disrupted_legs": res["expected_disrupted_legs"],
            "mean_leg_risk": res["mean_leg_risk"],
            "vehicles_used": res["vehicles_used"], "posts_served": res["posts_served"],
            "covered_tonnes": res["covered_tonnes"], "shortfall_tonnes": res["shortfall_tonnes"],
            "coverage_pct": res["coverage_pct"], "solve_time_s": res["solve_time_s"],
            **lineage,
        })
        for seq, leg in enumerate(res["legs"]):
            leg_rows.append({"plan_id": plan_id, "seq": seq, **leg,
                             "depart_date": snap_date, **lineage})
        plan_compare.append({
            "objective": obj, "status": res["status"],
            "vehicles_used": res["vehicles_used"], "posts_served": res["posts_served"],
            "coverage_pct": res["coverage_pct"], "shortfall_tonnes": res["shortfall_tonnes"],
            "total_cost": res["total_cost"], "total_time_hours_makespan": res["total_time_hours"],
            "aggregate_risk": res["aggregate_risk"],
            "expected_disrupted_legs": res["expected_disrupted_legs"],
            "mean_leg_risk": res["mean_leg_risk"], "solve_time_s": res["solve_time_s"],
        })

    plans_df = pd.DataFrame(plan_rows)
    legs_df = pd.DataFrame(leg_rows) if leg_rows else pd.DataFrame(columns=[
        "plan_id", "seq", "vehicle_id", "vehicle_class", "depot_id", "route_id",
        "post_id", "sku_id", "qty", "weight_kg", "expected_cost", "expected_risk",
        "eta_hours", "path_availability", "depart_date", *lineage.keys()])

    # 4. Alerts ----------------------------------------------------------------
    alerts_df = alerts_mod.generate_alerts(snapshot_dir, planning_horizon=H)

    # ── Persist ───────────────────────────────────────────────────────────────
    p_plans = out_dir / "resupply_plans.parquet"
    p_legs = out_dir / "resupply_plan_legs.parquet"
    p_alerts = out_dir / "alerts.parquet"
    plans_df.to_parquet(p_plans, index=False)
    legs_df.to_parquet(p_legs, index=False)
    alerts_df.to_parquet(p_alerts, index=False)

    # ── Decision-focused diagnostics (the "would change a decision" readout) ──
    diagnostics = {
        **lineage,
        "scope": {
            "at_risk_posts": d["n_at_risk_posts"],
            "deficit_pairs": d["n_deficit_pairs"],
            "total_deficit_tonnes": d["total_deficit_tonnes"],
            "eligible_vehicles": d["eligible_vehicles"],
            "depots_in_play": d["depots_in_play"],
        },
        "reachability": {
            "road_isolated_at_risk_posts": d["n_isolated_legs"],
            "isolated_detail": d["isolated_legs"],
            "no_road_posts": d["no_road_posts"],
            "pass_path_open_prob_at_horizon": d["passes_path_open_prob"],
        },
        "plan_comparison": plan_compare,
        "alerts_summary": {
            "total": int(len(alerts_df)),
            "by_type": alerts_df["alert_type"].value_counts().to_dict() if len(alerts_df) else {},
            "by_severity": alerts_df["severity"].value_counts().to_dict() if len(alerts_df) else {},
        },
        "interpretation": _interpretation(b, plan_compare),
    }
    (out_dir / "planning_diagnostics.json").write_text(json.dumps(diagnostics, indent=2, default=str))
    (out_dir / "lineage.json").write_text(json.dumps({
        **lineage,
        "outputs": {"resupply_plans": p_plans.name, "resupply_plan_legs": p_legs.name,
                    "alerts": p_alerts.name},
        "row_counts": {"resupply_plans": len(plans_df), "resupply_plan_legs": len(legs_df),
                       "alerts": len(alerts_df)},
    }, indent=2))

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n  plans:")
    for pc in plan_compare:
        print(f"    {pc['objective']:9s}  cover {pc['coverage_pct']:5.1f}%  "
              f"veh {pc['vehicles_used']:3d}  ₹{pc['total_cost']:>12,.0f}  "
              f"makespan {pc['total_time_hours_makespan']:6.1f}h  "
              f"E[disrupted] {pc['expected_disrupted_legs']:5.2f}  "
              f"({pc['solve_time_s']:.2f}s)")
    print(f"  alerts: {len(alerts_df)}  "
          f"({diagnostics['alerts_summary']['by_severity']})")
    print(f"\n✓ Stage 4 plan complete in {time.time()-t0:.1f}s  → {out_dir}")

    return {"out_dir": out_dir, **lineage,
            "n_plans": len(plans_df), "n_legs": len(legs_df), "n_alerts": len(alerts_df)}


def _interpretation(b: inputs.Bundle, plan_compare: list) -> list:
    """Plain-language, decision-grade notes. Keeps the Foundry-engineer stance:
    surface what changes a decision, not what describes the run."""
    notes = []
    iso = b.diagnostics["n_isolated_legs"]
    if iso:
        air = sum(1 for x in b.diagnostics["isolated_legs"] if x["has_air_resupply"])
        notes.append(
            f"{iso} at-risk post(s) are road-isolated at the planning horizon "
            f"(serving pass path P(open) below {cfg.PATH_FEASIBILITY_MIN}). "
            f"{air} of them support air resupply; the remainder cannot be sustained "
            f"by any modelled means and need pre-positioning BEFORE the pass shuts. "
            f"These deficits show as shortfall in every plan — the optimizer is "
            f"correctly refusing to promise a delivery it cannot make.")
    covers = {pc["objective"]: pc["coverage_pct"] for pc in plan_compare}
    if covers and min(covers.values()) < 100.0:
        notes.append(
            f"Best achievable road coverage is {max(covers.values()):.1f}% — the "
            f"gap is transport/reachability-bound, not stock-bound (depots hold the "
            f"goods). The lever is convoys-before-closure, not more inventory.")
    # plan spread
    feasible = [pc for pc in plan_compare if pc["status"] in ("optimal", "feasible")]
    if len(feasible) >= 2:
        cost_spread = max(pc["total_cost"] for pc in feasible) - min(pc["total_cost"] for pc in feasible)
        # use expected_disrupted_legs (does not saturate the way P(>=1 fail) does)
        risk_spread = (max(pc["expected_disrupted_legs"] for pc in feasible)
                       - min(pc["expected_disrupted_legs"] for pc in feasible))
        notes.append(
            f"At equal coverage, plan choice trades ₹{cost_spread:,.0f} of transport "
            f"cost against {risk_spread:.2f} expected disrupted legs — that spread is "
            f"the actual decision in front of the planner. (When passes are marginal, "
            f"P(>=1 leg disrupted) pins near 1.0; expected disrupted legs is the metric "
            f"that still discriminates.)")
    return notes


if __name__ == "__main__":
    import sys
    # Default to the canonical committed snapshot if none given.
    default = cfg.STAGE3_OUTPUT_DIR / "snapshot_2024-12-15"
    snap = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    run_plan(snap)
