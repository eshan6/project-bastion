"""
Project Bastion — Stage 4 optimizer (OR-Tools MIP, v1.0)

Problem (right-sized to the AOR's hub-and-spoke topology):
  Each at-risk post is served by ONE source depot via ONE inbound road leg with a
  known distance + pass chain. The decision is which depot vehicles to dispatch
  and how to load them so every at-risk post is topped up to (horizon + reserve)
  days of WORST-CASE (P90) cover, subject to:
     - vehicle payload (tonnage) capacity        [usually the binding constraint]
     - depot on-hand stock per SKU                [rarely binding; depots hold a lot]
     - road feasibility: a leg whose path P(open) < PATH_FEASIBILITY_MIN cannot be
       driven -> that post's deficit becomes a surfaced shortfall (air-resupply
       flagged if supported). Isolation is an explicit output, never a silent miss.

Formulation (MIP, pywraplp/CBC):
  Vars
    x[v,p] in {0,1}     vehicle v dispatched to post p (>=0, <=1 mission/vehicle)
    f[v,p,k] >= 0       units of SKU k loaded on v for p
    u[p,k] >= 0         unmet deficit (shortfall) for (post, sku)
  Constraints
    (1) sum_p x[v,p] <= 1                                       one mission/vehicle
    (2) sum_k f[v,p,k]*wkg[k] <= payload_t[v]*1000 * x[v,p]     capacity gate+link
    (3) sum_v f[v,p,k] + u[p,k] = deficit[p,k]                  coverage accounting
    (4) sum_{v@d, p} f[v,p,k] <= depot_stock[d,k]               supply cap
  Objective (minimize)
    COVERAGE_WEIGHT * sum priority[p,k]*wkg[k]*u[p,k]    (lexicographically first)
      + sum over legs  secondary_penalty(objective) * x[v,p]
  Four objectives change only the secondary penalty, so all four COVER the same
  deficit but route/select vehicles differently:
    min_cost  -> fuel(class)*dist + fixed dispatch
    min_time  -> one-way convoy hours (dist/speed(class)) + marginal-path hold
    min_risk  -> expected leg failure = 1 - P(path open)*P(vehicle survives)
    balanced  -> normalized blend of the three

Determinism: single-thread CBC, sorted variable creation, fixed time limit.
Warm-start: solve min_cost, feed its x as a hint to the other three (< 5s replan).
"""
from __future__ import annotations
import time
import math
import pandas as pd
from ortools.linear_solver import pywraplp
import config as cfg
from inputs import Bundle


# ─────────────────────────────────────────────────────────────────────────────
# Per-leg economics (deterministic functions of class + leg)
# ─────────────────────────────────────────────────────────────────────────────
def leg_cost(vclass: str, distance_km: float) -> float:
    fuel = cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM)
    return distance_km * fuel + cfg.VEHICLE_FIXED_DISPATCH_COST


def leg_eta_hours(vclass: str, distance_km: float, path_availability: float) -> float:
    speed = cfg.VEHICLE_CLASS_SPEED_KMPH.get(vclass, cfg.DEFAULT_SPEED_KMPH)
    drive = distance_km / speed
    hold = cfg.PATH_DELAY_HOURS_AT_FULL_CLOSURE * (1.0 - path_availability)
    return drive + hold


def leg_risk(path_availability: float, p_deadline: float) -> float:
    # Expected mission failure: path shut OR vehicle deadlines en route.
    return 1.0 - path_availability * (1.0 - p_deadline)


# ─────────────────────────────────────────────────────────────────────────────
# Candidate legs (vehicle, post) and per-objective secondary penalties
# ─────────────────────────────────────────────────────────────────────────────
def _candidates(b: Bundle):
    """Yield (vehicle_id, post_id) candidate assignments + precomputed penalties."""
    cand = {}
    for pid in b.posts:
        leg = b.legs[pid]
        if not leg.feasible:
            continue  # isolated post: no road assignment; deficit -> shortfall
        for vid in b.vehicles_by_depot.get(leg.depot_id, []):
            v = b.veh[vid]
            c = leg_cost(v["vehicle_class"], leg.distance_km)
            t = leg_eta_hours(v["vehicle_class"], leg.distance_km, leg.path_availability)
            r = leg_risk(leg.path_availability, v["p_deadline"])
            cand[(vid, pid)] = {"cost": c, "time": t, "risk": r}
    return cand


def _secondary_penalty(objective: str, pen: dict, scale: dict) -> float:
    if objective == "min_cost":
        return pen["cost"]
    if objective == "min_time":
        return pen["time"]
    if objective == "min_risk":
        return pen["risk"]
    # balanced: normalized blend in [0,1] units, scaled back up so it is not
    # dwarfed numerically (multiply by mean cost scale to keep magnitudes sane).
    bw = cfg.BALANCED_BLEND
    norm = (bw["cost"] * pen["cost"] / scale["cost"]
            + bw["time"] * pen["time"] / scale["time"]
            + bw["risk"] * pen["risk"] / scale["risk"])
    return norm * scale["cost"]   # re-scale to ₹-ish magnitude


# ─────────────────────────────────────────────────────────────────────────────
# Build + solve one objective
# ─────────────────────────────────────────────────────────────────────────────
def solve_one(b: Bundle, objective: str, cand: dict, scale: dict,
              hint: dict | None = None) -> dict:
    solver = pywraplp.Solver.CreateSolver(cfg.SOLVER_BACKEND)
    if solver is None:
        raise RuntimeError("CBC solver unavailable in this OR-Tools build")
    solver.SetNumThreads(cfg.SOLVER_NUM_THREADS)
    solver.SetTimeLimit(cfg.SOLVER_TIME_LIMIT_MS)

    INF = solver.infinity()

    # Decision vars (sorted creation order -> determinism)
    x = {}    # (v,p) -> binary
    for (vid, pid) in sorted(cand.keys()):
        x[(vid, pid)] = solver.BoolVar(f"x_{vid}_{pid}")

    f = {}    # (v,p,k) -> continuous units
    for (vid, pid) in sorted(cand.keys()):
        for k in b.skus_at_post[pid]:
            f[(vid, pid, k)] = solver.NumVar(0.0, INF, f"f_{vid}_{pid}_{k}")

    u = {}    # (p,k) -> shortfall units
    for pid in b.posts:
        for k in b.skus_at_post[pid]:
            u[(pid, k)] = solver.NumVar(0.0, INF, f"u_{pid}_{k}")

    # (1) one mission per vehicle
    by_vehicle: dict[str, list] = {}
    for (vid, pid) in x:
        by_vehicle.setdefault(vid, []).append(pid)
    for vid, pids in by_vehicle.items():
        solver.Add(solver.Sum(x[(vid, p)] for p in pids) <= 1)

    # (2) capacity gate + load-only-if-assigned link (single constraint)
    for (vid, pid) in x:
        cap_kg = b.veh[vid]["payload_tons"] * 1000.0
        solver.Add(
            solver.Sum(f[(vid, pid, k)] * b.sku_weight_kg[k] for k in b.skus_at_post[pid])
            <= cap_kg * x[(vid, pid)]
        )

    # (3) coverage accounting: delivered + shortfall = deficit
    for pid in b.posts:
        for k in b.skus_at_post[pid]:
            delivered = solver.Sum(
                f[(vid, pid, k)] for vid in b.vehicles_by_depot.get(b.legs[pid].depot_id, [])
                if (vid, pid) in x
            )
            solver.Add(delivered + u[(pid, k)] == b.deficit_units[(pid, k)])

    # (4) depot supply cap per (depot, sku)
    depot_sku_terms: dict[tuple, list] = {}
    for (vid, pid, k) in f:
        d = b.veh[vid]["depot_id"]
        depot_sku_terms.setdefault((d, k), []).append(f[(vid, pid, k)])
    for (d, k), terms in depot_sku_terms.items():
        cap = b.depot_stock.get((d, k))
        if cap is not None:
            solver.Add(solver.Sum(terms) <= cap)

    # Objective
    obj = solver.Objective()
    # coverage term (dominant): priority * weight_kg * shortfall_units
    for pid in b.posts:
        st_mult = cfg.STATUS_PRIORITY.get(b.post_status.get(pid, "ok"), 1.0)
        for k in b.skus_at_post[pid]:
            tier = b.sku_meta[k]["tier"]
            prio = cfg.TIER_PRIORITY.get(tier, 1.0) * st_mult
            obj.SetCoefficient(u[(pid, k)], cfg.COVERAGE_WEIGHT * prio * b.sku_weight_kg[k])
    # secondary transport term
    for (vid, pid) in x:
        pen = _secondary_penalty(objective, cand[(vid, pid)], scale)
        obj.SetCoefficient(x[(vid, pid)], pen)
    obj.SetMinimization()

    # Warm start hint from a prior solution (min_cost -> others)
    if hint:
        vars_, vals_ = [], []
        for (vid, pid), val in hint.items():
            if (vid, pid) in x:
                vars_.append(x[(vid, pid)]); vals_.append(val)
        if vars_:
            solver.SetHint(vars_, vals_)

    t0 = time.time()
    status = solver.Solve()
    solve_s = time.time() - t0
    status_name = {pywraplp.Solver.OPTIMAL: "optimal",
                   pywraplp.Solver.FEASIBLE: "feasible",
                   pywraplp.Solver.INFEASIBLE: "infeasible",
                   pywraplp.Solver.UNBOUNDED: "unbounded",
                   pywraplp.Solver.ABNORMAL: "abnormal",
                   pywraplp.Solver.NOT_SOLVED: "not_solved"}.get(status, str(status))

    # Extract solution
    legs_out, assign_sol = [], {}
    vehicles_used, posts_served = set(), set()
    total_cost = 0.0
    makespan_h = 0.0
    veh_risk = {}   # vehicle -> its leg risk (for aggregate, counted once per vehicle)
    if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE):
        for (vid, pid) in sorted(x.keys()):
            if x[(vid, pid)].solution_value() > 0.5:
                assign_sol[(vid, pid)] = 1
                vehicles_used.add(vid); posts_served.add(pid)
                leg = b.legs[pid]; vc = b.veh[vid]["vehicle_class"]
                lc = leg_cost(vc, leg.distance_km)
                lt = leg_eta_hours(vc, leg.distance_km, leg.path_availability)
                lr = leg_risk(leg.path_availability, b.veh[vid]["p_deadline"])
                total_cost += lc
                makespan_h = max(makespan_h, lt)
                veh_risk[vid] = lr
                # one leg row per (vehicle, sku) actually loaded; apportion cost by kg
                loaded = [(k, f[(vid, pid, k)].solution_value())
                          for k in b.skus_at_post[pid]
                          if f[(vid, pid, k)].solution_value() > 1e-6]
                tot_kg = sum(q * b.sku_weight_kg[k] for k, q in loaded) or 1.0
                for k, q in loaded:
                    legs_out.append({
                        "vehicle_id": vid, "vehicle_class": vc, "depot_id": leg.depot_id,
                        "route_id": leg.route_id, "post_id": pid, "sku_id": k,
                        "qty": round(q, 3), "weight_kg": round(q * b.sku_weight_kg[k], 2),
                        "expected_cost": round(lc * (q * b.sku_weight_kg[k]) / tot_kg, 2),
                        "expected_risk": round(lr, 6), "eta_hours": round(lt, 2),
                        "path_availability": round(leg.path_availability, 4),
                    })

    # aggregate risk = P(>=1 dispatched leg fails) under independence, counted per vehicle
    agg_risk = 1.0 - math.prod((1.0 - r) for r in veh_risk.values()) if veh_risk else 0.0
    # non-saturating companions (the deep-winter case pins agg_risk at ~1.0):
    expected_disrupted_legs = sum(veh_risk.values())          # E[# legs disrupted]
    mean_leg_risk = (expected_disrupted_legs / len(veh_risk)) if veh_risk else 0.0

    covered_kg = sum(l["weight_kg"] for l in legs_out)
    shortfall_kg = sum(u[(pid, k)].solution_value() * b.sku_weight_kg[k]
                       for pid in b.posts for k in b.skus_at_post[pid]) \
                   if status in (pywraplp.Solver.OPTIMAL, pywraplp.Solver.FEASIBLE) else 0.0
    demand_kg = covered_kg + shortfall_kg
    coverage_pct = (100.0 * covered_kg / demand_kg) if demand_kg > 1e-9 else 100.0

    return {
        "objective": objective, "status": status_name, "solve_time_s": round(solve_s, 3),
        "legs": legs_out, "assign_solution": assign_sol,
        "vehicles_used": len(vehicles_used), "posts_served": len(posts_served),
        "total_cost": round(total_cost, 2),
        "total_time_hours": round(makespan_h, 2),     # makespan = latest delivery
        "aggregate_risk": round(agg_risk, 4),
        "expected_disrupted_legs": round(expected_disrupted_legs, 3),
        "mean_leg_risk": round(mean_leg_risk, 4),
        "covered_tonnes": round(covered_kg / 1000.0, 2),
        "shortfall_tonnes": round(shortfall_kg / 1000.0, 2),
        "coverage_pct": round(coverage_pct, 1),
    }


def solve_all(b: Bundle) -> dict:
    """Solve all four objectives, warm-starting non-cost objectives from min_cost.

    Returns {objective: result}. If there is nothing actionable (no feasible legs
    and no deficits), returns an empty-plan result per objective so the contract
    downstream is uniform.
    """
    cand = _candidates(b)
    if not cand:
        empty = {"status": "no_action", "legs": [], "assign_solution": {},
                 "vehicles_used": 0, "posts_served": 0, "total_cost": 0.0,
                 "total_time_hours": 0.0, "aggregate_risk": 0.0,
                 "expected_disrupted_legs": 0.0, "mean_leg_risk": 0.0,
                 "covered_tonnes": 0.0,
                 "shortfall_tonnes": round(sum(
                     b.deficit_units[(p, k)] * b.sku_weight_kg[k]
                     for p in b.posts for k in b.skus_at_post[p]) / 1000.0, 2),
                 "coverage_pct": 0.0, "solve_time_s": 0.0}
        return {o: {**empty, "objective": o} for o in cfg.OBJECTIVES}

    # scale references for the balanced blend (max over candidate legs)
    scale = {
        "cost": max(c["cost"] for c in cand.values()) or 1.0,
        "time": max(c["time"] for c in cand.values()) or 1.0,
        "risk": max(c["risk"] for c in cand.values()) or 1.0,
    }

    results = {}
    res_cost = solve_one(b, "min_cost", cand, scale, hint=None)
    results["min_cost"] = res_cost
    hint = res_cost["assign_solution"]
    for obj in cfg.OBJECTIVES:
        if obj == "min_cost":
            continue
        results[obj] = solve_one(b, obj, cand, scale, hint=hint)
    return results
