"""
Project Bastion — Stage 4 plan service (v1.0)

Stage 4's orchestrator (analog of Stage 3 predict_service.run_snapshot). Given a
Stage 3 snapshot dir, it:
  1. assembles the optimizer bundle  (inputs.load_bundle)
  2. solves the 3-plan ε-constraint frontier (full_coverage/min_cost/min_exposure)
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
    print(f"  in-scope posts: {d['n_in_scope_posts']} "
          f"(isolation-gated {d['n_gated_by_isolation']}, alert-only {d['n_in_scope_by_alert_only']})   "
          f"deficit: {d['total_deficit_tonnes']} t   eligible vehicles: {d['eligible_vehicles']}")
    print(f"  deficit by head (t): {d['deficit_tonnes_by_head']}")
    if d["n_substitutions"]:
        print(f"  perishable substitutions: {d['n_substitutions']} "
              f"({d['substituted_tonnes']} t routed to longer-life substitute)")
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
    plan_rows, leg_rows, route_rows = [], [], []
    plan_compare = []
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
            "max_leg_risk": res.get("max_leg_risk", 0.0),
            "risky_sorties": res.get("risky_sorties", 0),
            "expected_loss_tonnes": res.get("expected_loss_tonnes", 0.0),
            "objective_tradeoff_tonnes": res.get("objective_tradeoff_tonnes", 0.0),
            "expected_shortfall_tonnes": res.get("expected_shortfall_tonnes", 0.0),
            "mean_pa_at_dispatch": res.get("mean_pa_at_dispatch", 0.0),
            "dispatch_days_used": ",".join(str(d) for d in res.get("dispatch_days_used", [])),
            "vehicles_used": res["vehicles_used"], "posts_served": res["posts_served"],
            "convoys": res.get("convoys", 0),
            "covered_tonnes": res["covered_tonnes"], "shortfall_tonnes": res["shortfall_tonnes"],
            "road_covered_tonnes": res.get("road_covered_tonnes", res["covered_tonnes"]),
            "non_road_covered_tonnes": res.get("non_road_covered_tonnes", 0.0),
            "road_cost": res.get("road_cost", res["total_cost"]),
            "non_road_cost": res.get("non_road_cost", 0.0),
            "posts_served_nonroad": res.get("posts_served_nonroad", 0),
            "coverage_pct": res["coverage_pct"],
            "coverage_reachable_pct": res.get("coverage_reachable_pct", res["coverage_pct"]),
            "isolated_tonnes": res.get("isolated_tonnes", 0.0),
            "solve_time_s": res["solve_time_s"],
            **lineage,
        })
        snap_ts = pd.Timestamp(snap_date)
        for seq, leg in enumerate(res["legs"]):
            dd = int(leg.get("depart_day", 1))
            leg_rows.append({"plan_id": plan_id, "seq": seq, **leg,
                             "depart_date": str((snap_ts + pd.Timedelta(days=dd)).date()),
                             **lineage})
        # convoy manifest (one row per dispatched vehicle route)
        for r in res.get("routes", []):
            route_rows.append({"plan_id": plan_id, "objective": obj,
                               "vehicle_id": r["vehicle_id"], "vehicle_class": r["vehicle_class"],
                               "depot_id": r["depot_id"], "axis": r["axis"],
                               "stops": ">".join(r["stops"]), "n_stops": len(r["stops"]),
                               "route_km": r["route_km"],
                               "expected_cost": r.get("expected_cost", 0.0),
                               "eta_hours": r.get("eta_hours", 0.0),
                               "expected_risk": r.get("expected_risk", 0.0),
                               "depart_day": int(r.get("depart_day", 1)),
                               "pa_at_dispatch": r.get("pa_at_dispatch", 0.0),
                               "depart_date": str((pd.Timestamp(snap_date) + pd.Timedelta(days=int(r.get("depart_day", 1)))).date()),
                               **lineage})
        plan_compare.append({
            "objective": obj, "status": res["status"],
            "vehicles_used": res["vehicles_used"], "posts_served": res["posts_served"],
            "convoys": res.get("convoys", 0),
            "coverage_pct": res["coverage_pct"],
            "coverage_reachable_pct": res.get("coverage_reachable_pct", res["coverage_pct"]),
            "shortfall_tonnes": res["shortfall_tonnes"], "isolated_tonnes": res.get("isolated_tonnes", 0.0),
            "non_road_covered_tonnes": res.get("non_road_covered_tonnes", 0.0),
            "non_road_cost": res.get("non_road_cost", 0.0),
            "non_road_summary": res.get("non_road_summary", {}),
            "total_cost": res["total_cost"], "total_time_hours_makespan": res["total_time_hours"],
            "aggregate_risk": res["aggregate_risk"],
            "expected_disrupted_legs": res["expected_disrupted_legs"],
            "mean_leg_risk": res["mean_leg_risk"],
            "max_leg_risk": res.get("max_leg_risk", 0.0),
            "risky_sorties": res.get("risky_sorties", 0),
            "expected_loss_tonnes": res.get("expected_loss_tonnes", 0.0),
            "objective_tradeoff_tonnes": res.get("objective_tradeoff_tonnes", 0.0),
            "expected_shortfall_tonnes": res.get("expected_shortfall_tonnes", 0.0),
            "dispatch_days_used": ",".join(str(d) for d in res.get("dispatch_days_used", [])),
            "solve_time_s": res["solve_time_s"],
        })

    plans_df = pd.DataFrame(plan_rows)
    legs_df = pd.DataFrame(leg_rows) if leg_rows else pd.DataFrame(columns=[
        "plan_id", "seq", "vehicle_id", "vehicle_class", "depot_id", "axis", "route_id",
        "post_id", "sku_id", "qty", "weight_kg", "stop_order", "route_km",
        "expected_cost", "expected_risk", "eta_hours", "path_availability",
        "depart_date", *lineage.keys()])
    if len(legs_df):
        legs_df = legs_df.sort_values(
            ["plan_id", "depot_id", "axis", "vehicle_id", "stop_order", "post_id", "sku_id"]
        ).reset_index(drop=True)
        legs_df["seq"] = legs_df.groupby("plan_id").cumcount()
    routes_df = pd.DataFrame(route_rows) if route_rows else pd.DataFrame(columns=[
        "plan_id", "objective", "vehicle_id", "vehicle_class", "depot_id", "axis",
        "stops", "n_stops", "route_km", "expected_cost", "eta_hours", "expected_risk",
        "depart_date", *lineage.keys()])
    if len(routes_df):
        routes_df = routes_df.sort_values(
            ["plan_id", "depot_id", "axis", "vehicle_id"]).reset_index(drop=True)

    # 4. Alerts ----------------------------------------------------------------
    alerts_df = alerts_mod.generate_alerts(snapshot_dir, planning_horizon=H)

    # 4b. Shortfalls (per plan) + substitutions (bundle-level) -----------------
    shortfall_rows = []
    for obj in cfg.OBJECTIVES:
        pid_obj = str(uuid.uuid5(plan_ns, f"{snap_date}:{H}:{cfg.MODEL_VERSION}:{obj}"))
        for sf in results[obj].get("shortfalls", []):
            shortfall_rows.append({"plan_id": pid_obj, "objective": obj, **sf, **lineage})
    shortfalls_df = pd.DataFrame(shortfall_rows) if shortfall_rows else pd.DataFrame(
        columns=["plan_id", "objective", "post_id", "sku_id", "shortfall_units",
                 "shortfall_kg", "head", "tier", "cause", "air_resupply_possible",
                 "path_availability", *lineage.keys()])
    if len(shortfalls_df):
        shortfalls_df = shortfalls_df.sort_values(
            ["plan_id", "post_id", "sku_id"]).reset_index(drop=True)
    subs_df = pd.DataFrame(b.substitutions) if b.substitutions else pd.DataFrame(
        columns=["post_id", "from_sku", "to_sku", "units_from", "units_to", "note"])

    # 4c. Non-road legs (air/porter/mule) — first-class ontology rows ----------
    nr_rows = []
    for obj in cfg.OBJECTIVES:
        pid_obj = str(uuid.uuid5(plan_ns, f"{snap_date}:{H}:{cfg.MODEL_VERSION}:{obj}"))
        for seq, l in enumerate(results[obj].get("non_road_legs", [])):
            nr_rows.append({"plan_id": pid_obj, "objective": obj, "seq": seq, **l,
                            "depart_date": snap_date, **lineage})
    nonroad_df = pd.DataFrame(nr_rows) if nr_rows else pd.DataFrame(
        columns=["plan_id", "objective", "seq", "post_id", "sku_id", "qty",
                 "weight_kg", "transport_mode", "cost_per_kg", "expected_cost",
                 "depot_id", "axis", "head", "tier", "depart_date", *lineage.keys()])
    if len(nonroad_df):
        nonroad_df = nonroad_df.sort_values(
            ["plan_id", "transport_mode", "post_id", "sku_id"]).reset_index(drop=True)
        nonroad_df["seq"] = nonroad_df.groupby("plan_id").cumcount()

    # ── Persist ───────────────────────────────────────────────────────────────
    p_plans = out_dir / "resupply_plans.parquet"
    p_legs = out_dir / "resupply_plan_legs.parquet"
    p_alerts = out_dir / "alerts.parquet"
    plans_df.to_parquet(p_plans, index=False)
    legs_df.to_parquet(p_legs, index=False)
    alerts_df.to_parquet(p_alerts, index=False)
    p_routes = out_dir / "resupply_convoys.parquet"
    routes_df.to_parquet(p_routes, index=False)
    p_short = out_dir / "resupply_shortfalls.parquet"
    p_subs = out_dir / "perishable_substitutions.parquet"
    shortfalls_df.to_parquet(p_short, index=False)
    subs_df.to_parquet(p_subs, index=False)
    p_nonroad = out_dir / "resupply_nonroad_legs.parquet"
    nonroad_df.to_parquet(p_nonroad, index=False)

    # ── Decision-focused diagnostics (the "would change a decision" readout) ──
    diagnostics = {
        **lineage,
        "scope": {
            "in_scope_posts": d["n_in_scope_posts"],
            "isolation_gated": d["n_gated_by_isolation"],
            "alert_only": d["n_in_scope_by_alert_only"],
            "deficit_pairs": d["n_deficit_pairs"],
            "total_deficit_tonnes": d["total_deficit_tonnes"],
            "deficit_tonnes_by_head": d["deficit_tonnes_by_head"],
            "stocking_window_by_post": d["stocking_window_by_post"],
            "days_to_closure_by_post": d["days_to_closure_by_post"],
            "n_substitutions": d["n_substitutions"],
            "substituted_tonnes": d["substituted_tonnes"],
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
                    "resupply_convoys": p_routes.name,
                    "alerts": p_alerts.name, "resupply_shortfalls": p_short.name,
                    "perishable_substitutions": p_subs.name,
                    "resupply_nonroad_legs": p_nonroad.name},
        "row_counts": {"resupply_plans": len(plans_df), "resupply_plan_legs": len(legs_df),
                       "resupply_convoys": len(routes_df),
                       "alerts": len(alerts_df), "resupply_shortfalls": len(shortfalls_df),
                       "perishable_substitutions": len(subs_df),
                       "resupply_nonroad_legs": len(nonroad_df)},
    }, indent=2))

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n  plans:")
    for pc in plan_compare:
        print(f"    {pc['objective']:13s}  reach-cover {pc['coverage_reachable_pct']:5.1f}%  "
              f"convoys {pc['convoys']:3d}  veh {pc['vehicles_used']:3d}  ₹{pc['total_cost']:>12,.0f}  "
              f"makespan {pc['total_time_hours_makespan']:6.1f}h  "
              f"({pc['status']}, {pc['solve_time_s']:.2f}s)")
        nrs = pc.get("non_road_summary", {})
        if nrs:
            modes = "  ".join(f"{m}: {s['tonnes']}t/₹{s['cost']:,.0f}" for m, s in nrs.items())
            print(f"              non-road  {pc.get('non_road_covered_tonnes', 0)}t total — {modes}")
    print(f"  alerts: {len(alerts_df)}  "
          f"({diagnostics['alerts_summary']['by_severity']})")
    print(f"\n✓ Stage 4 plan complete in {time.time()-t0:.1f}s  → {out_dir}")

    return {"out_dir": out_dir, **lineage,
            "n_plans": len(plans_df), "n_legs": len(legs_df),
            "n_convoys": len(routes_df), "n_alerts": len(alerts_df)}


def _interpretation(b: inputs.Bundle, plan_compare: list) -> list:
    """Plain-language, decision-grade notes. Keeps the Foundry-engineer stance:
    surface what changes a decision, not what describes the run."""
    notes = []
    iso = b.diagnostics["n_isolated_legs"]
    if iso:
        air = sum(1 for x in b.diagnostics["isolated_legs"] if x["has_air_resupply"])
        nr = plan_compare[0].get("non_road_summary", {}) if plan_compare else {}
        nr_t = plan_compare[0].get("non_road_covered_tonnes", 0.0) if plan_compare else 0.0
        nr_cost = plan_compare[0].get("non_road_cost", 0.0) if plan_compare else 0.0
        residual = plan_compare[0].get("isolated_tonnes", 0.0) if plan_compare else 0.0
        notes.append(
            f"{iso} at-risk post(s) are road-isolated at the planning horizon "
            f"(serving pass path P(open) below {cfg.PATH_FEASIBILITY_MIN}). "
            f"{air} of them have an ALG/DZ for air resupply. Non-road modes "
            f"(mule column, porter column, air-drop) resolve {nr_t:.1f}t of the "
            f"isolated deficit at ₹{nr_cost:,.0f} — roughly {len(nr)} mode(s) in "
            f"play. The remaining {residual:.1f}t is the genuine pre-positioning "
            f"gap: bulk tonnage (dominated by POL) that exceeds what animal "
            f"columns and the available air window can lift. It must move by "
            f"road BEFORE the pass shuts.")
    covers = {pc["objective"]: pc["coverage_pct"] for pc in plan_compare}
    if covers and min(covers.values()) < 100.0:
        notes.append(
            f"Best achievable coverage including non-road modes is "
            f"{max(covers.values()):.1f}% — the residual gap is lift-capacity-"
            f"bound, not stock-bound (depots hold the goods). The lever is "
            f"convoys-before-closure; air/porter/mule is the in-season mitigation, "
            f"at ~40-50x road cost per tonne.")
    # plan spread — the ε-constraint frontier is the decision
    feasible = [pc for pc in plan_compare if pc["status"] in ("optimal", "feasible")]
    by_obj = {pc["objective"]: pc for pc in feasible}
    fc, mx = by_obj.get("full_coverage"), by_obj.get("min_exposure")
    if fc and mx:
        notes.append(
            f"The frontier is the decision: full_coverage ships everything reachable "
            f"({fc['coverage_reachable_pct']:.1f}%, {fc['convoys']} convoys, "
            f"₹{fc['total_cost']:,.0f}); min_exposure deliberately leaves "
            f"{mx['objective_tradeoff_tonnes']:.1f} t of low-tier cargo off marginal "
            f"passes (every dropped kg listed per post/SKU under cause "
            f"'objective_tradeoff'), cutting convoys {fc['convoys']}→{mx['convoys']} and "
            f"expected in-transit loss {fc['expected_loss_tonnes']:.1f}→"
            f"{mx['expected_loss_tonnes']:.1f} t for ₹{fc['total_cost']-mx['total_cost']:,.0f} "
            f"less. Tier-1 is identical in every plan by construction.")
    notes.append(
        "expected_loss_tonnes is computed at planning-horizon path availability — a "
        "conservative exposure index for COMPARING plans, not a literal arrival "
        "forecast (convoys dispatch anticipatorily while roads are open). aggregate_risk "
        "saturates near 1.0 in deep winter; use the tonnage-denominated metrics.")
    return notes


if __name__ == "__main__":
    import sys
    # Default to the canonical committed snapshot if none given.
    default = cfg.STAGE3_OUTPUT_DIR / "snapshot_2024-12-15"
    snap = Path(sys.argv[1]) if len(sys.argv) > 1 else default
    run_plan(snap)
