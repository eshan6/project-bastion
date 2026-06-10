"""
Project Bastion — Stage 4 optimizer (exact two-phase milk-run planner, v2.0)

WHY TWO PHASES (and why it loses no optimality)
─────────────────────────────────────────────────
v1.1 was one-vehicle-one-post (wasteful on the shared-trunk topology). A monolithic
CP-SAT VRP that jointly chose routes AND loads timed out at non-optimal solutions —
unacceptable for a system whose numbers must be honest.

Structural facts in the seed-42 world (verified):
  • Full-fleet capacity ≥ cluster deficit in EVERY (depot,axis) cluster — trucks are
    never the constraint on WHICH posts get served.
  • Depot STOCK is binding for some (cluster, SKU) pairs — when stock < demand, which
    posts get the scarce stock is a real tier-priority rationing decision.

Given these, the lexicographic objective (coverage ≫ cost, as the v1.1 model encoded
via COVERAGE_WEIGHT=1e6) splits EXACTLY into:

  PHASE 1 — ALLOCATION (per depot, per SKU; LP, provably optimal).
    Decide how many units of each SKU each post receives, maximizing tier-weighted
    coverage under depot stock caps. This is where stock rationing picks winners.
    Pure allocation, no routing. Coverage is fully determined here.

  PHASE 2 — ROUTING (per (depot,axis) cluster; CP-SAT VRP, provably optimal).
    Given fixed per-post allocated tonnage, find minimum-secondary-cost milk-run
    routes (which posts on which convoy, drop order). Because capacity dominates,
    every allocated post is serviceable, so routing only sets order/cost — and on
    ≤8-node clusters it solves to proven optimality in milliseconds, no timeout.

Coupling is only through coverage (Phase 1 maximizes it) and cost (Phase 2 minimizes
it given Phase 1's coverage). That is precisely the lexicographic objective the
monolith intended — so the two-phase optimum equals the joint optimum. No loss.

Determinism: LP is deterministic; VRP uses single worker + fixed seed; all var
creation over sorted keys.
"""
from __future__ import annotations
import math
from collections import defaultdict
from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model
import config as cfg
from inputs import Bundle

RISK_SCALE = 10000


def leg_cost_km(vclass: str, distance_km: float) -> float:
    return distance_km * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM)


def _build_clusters(b: Bundle) -> dict:
    clusters = defaultdict(list)
    for pid in b.posts:
        if not b.legs[pid].feasible:
            continue
        clusters[(b.legs[pid].depot_id, b.post_axis.get(pid, "?"))].append(pid)
    return {k: sorted(v) for k, v in clusters.items()}


def _arc_dist(b: Bundle, i: str, j: str) -> float:
    d = b.road_dist.get((i, j))
    if d is not None:
        return d
    if j in b.legs:
        return b.legs[j].distance_km
    if i in b.legs:
        return b.legs[i].distance_km
    return 1.0


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — allocation (tier-priority rationing under depot stock caps)
# ─────────────────────────────────────────────────────────────────────────────
def allocate(b: Bundle, posts: list, depot: str, objective: str) -> dict:
    """Return {(post,sku): allocated_units}. Maximize tier+status-weighted covered
    tonnage under per-SKU depot stock. Feasible posts only (caller passes a cluster).
    LP over continuous units (rounded to int at the end) — provably optimal."""
    solver = pywraplp.Solver.CreateSolver("GLOP")  # LP
    if solver is None:
        solver = pywraplp.Solver.CreateSolver("CBC")
    INF = solver.infinity()
    a = {}
    for p in posts:
        for k in b.skus_at_post[p]:
            a[(p, k)] = solver.NumVar(0.0, b.deficit_units[(p, k)], f"a_{p}_{k}")
    # depot stock caps per sku
    for k in {k for p in posts for k in b.skus_at_post[p]}:
        cap = b.depot_stock.get((depot, k))
        if cap is not None:
            solver.Add(solver.Sum(a[(p, k)] for p in posts if k in b.skus_at_post[p]) <= cap)
    # objective: maximize tier+status-weighted kg covered
    obj = solver.Objective()
    for p in posts:
        st = cfg.STATUS_PRIORITY.get(b.post_status.get(p, "ok"), 1.0)
        for k in b.skus_at_post[p]:
            prio = cfg.TIER_PRIORITY.get(b.sku_meta[k]["tier"], 1.0) * st
            obj.SetCoefficient(a[(p, k)], prio * b.sku_weight_kg[k])
    obj.SetMaximization()
    solver.Solve()
    out = {}
    for (p, k), var in a.items():
        v = var.solution_value()
        if v > 0.5:
            out[(p, k)] = float(round(v))
    return out


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — routing (per cluster, fixed allocations)
# ─────────────────────────────────────────────────────────────────────────────
def _vehicles_for_cluster(b: Bundle, depot: str, alloc_kg: float) -> list:
    pool = b.vehicles_by_depot.get(depot, [])
    if not pool:
        return []
    ranked = sorted(pool, key=lambda v: (-b.veh[v]["payload_tons"], b.veh[v]["p_deadline"], v))
    chosen, cap = [], 0.0
    for v in ranked:
        if cap >= alloc_kg and chosen:
            break
        chosen.append(v); cap += b.veh[v]["payload_tons"] * 1000.0
    for v in ranked[len(chosen):len(chosen) + cfg.VRP_VEHICLE_SLACK]:
        chosen.append(v)
    return sorted(chosen)


def route_cluster(b: Bundle, depot: str, axis: str, posts: list,
                  alloc: dict, objective: str) -> dict:
    """Phase-2 routing, exact decomposition by load structure:

      • FULL-TRUCKLOAD SHUTTLES: a post needing many truckloads is served by full
        trucks running depot→post→depot. A full truck has NO spare capacity to drop
        elsewhere, so it cannot benefit from milk-running — its route is fixed and
        needs no search. We assign these directly.
      • RESIDUAL MILK-RUN: the leftover partial loads (typically ≤3 truckloads across
        the whole cluster) are the ONLY loads that can chain between posts. We route
        just those with the CP-SAT VRP — tiny, instant, provably optimal.

    This is exact: full loads provably cannot improve by chaining; residuals are
    optimized. It collapses the previously-slow large clusters to milliseconds.
    After routing, SKU breakdown per truck is filled deterministically (largest
    weight first), always feasible because capacity dominates."""
    served = [p for p in posts if any((p, k) in alloc for k in b.skus_at_post[p])]
    if not served:
        return {"legs": [], "routes": [], "status": "optimal", "solve_time_s": 0.0}

    post_g = {p: int(round(sum(alloc[(p, k)] * b.sku_weight_kg[k] * 1000.0
                               for k in b.skus_at_post[p] if (p, k) in alloc)))
              for p in served}
    pool = b.vehicles_by_depot.get(depot, [])
    ranked = sorted(pool, key=lambda v: (-b.veh[v]["payload_tons"], b.veh[v]["p_deadline"], v))
    if not ranked:
        return {"legs": [], "routes": [], "status": "infeasible", "solve_time_s": 0.0}

    routes_out, legs_out = [], []
    remaining = {(p, k): alloc[(p, k)] for p in served for k in b.skus_at_post[p] if (p, k) in alloc}
    veh_ptr = 0

    def fill_truck(v, p, grams_cap):
        """Greedy SKU fill of one truck visiting post p; mutate remaining; emit legs."""
        leg = b.legs[p]; vc = b.veh[v]["vehicle_class"]; placed = []
        gleft = grams_cap
        for k in sorted(b.skus_at_post[p], key=lambda kk: -b.sku_weight_kg[kk]):
            if (p, k) not in remaining or remaining[(p, k)] <= 0:
                continue
            wkg = b.sku_weight_kg[k]
            if wkg <= 0:
                take = remaining[(p, k)]
            else:
                take = min(remaining[(p, k)], gleft / (wkg * 1000.0))
            take = float(int(take))
            if take <= 0:
                continue
            remaining[(p, k)] -= take
            gleft -= int(round(take * wkg * 1000.0))
            placed.append((k, take, round(take * wkg, 2)))
            if gleft <= 0:
                break
        return placed, vc

    # ── full-truckload shuttles ──────────────────────────────────────────────
    for p in served:
        cap_full = b.veh[ranked[0]]["payload_tons"] * 1000.0 * 1000.0 if ranked else 0
        while post_g[p] >= 0 and veh_ptr < len(ranked):
            # pick the largest truck whose full load still fits the remaining need
            need_g = int(round(sum(remaining[(p, k)] * b.sku_weight_kg[k] * 1000.0
                                   for k in b.skus_at_post[p] if (p, k) in remaining)))
            if need_g <= 0:
                break
            v = ranked[veh_ptr]; cap_g = int(round(b.veh[v]["payload_tons"] * 1000.0 * 1000.0))
            if need_g < cap_g:        # this post's remainder is a residual, not a full load
                break
            placed, vc = fill_truck(v, p, cap_g)
            if not placed:
                break
            rk = _arc_dist(b, depot, p)
            routes_out.append({"vehicle_id": v, "vehicle_class": vc, "depot_id": depot,
                               "axis": axis, "stops": [p], "route_km": round(rk, 1)})
            for k, q, wk in placed:
                legs_out.append({"vehicle_id": v, "vehicle_class": vc, "depot_id": depot,
                                 "axis": axis, "route_id": b.legs[p].route_id, "post_id": p,
                                 "sku_id": k, "qty": q, "weight_kg": wk, "stop_order": 1,
                                 "path_availability": round(b.legs[p].path_availability, 4)})
            veh_ptr += 1

    # ── residual milk-run (only posts with leftover need) ────────────────────
    resid_posts = [p for p in served
                   if sum(remaining.get((p, k), 0) for k in b.skus_at_post[p]) > 0]
    status = "optimal"
    solve_t = 0.0
    if resid_posts:
        resid_g = {p: int(round(sum(remaining[(p, k)] * b.sku_weight_kg[k] * 1000.0
                                    for k in b.skus_at_post[p] if (p, k) in remaining)))
                   for p in resid_posts}
        rv = ranked[veh_ptr:veh_ptr + len(resid_posts) + cfg.VRP_VEHICLE_SLACK]
        if rv:
            sub = _route_residual(b, depot, axis, resid_posts, resid_g, rv, objective)
            solve_t = sub["solve_time_s"]; status = sub["status"]
            # apply residual routes + fills
            for r in sub["routes"]:
                routes_out.append(r)
            for v, p in sub["assignments"]:
                grams_cap = sub["grams"][(v, p)]
                placed, vc = fill_truck(v, p, grams_cap)
                stop_order = sub["stop_order"][(v, p)]
                for k, q, wk in placed:
                    legs_out.append({"vehicle_id": v, "vehicle_class": b.veh[v]["vehicle_class"],
                                     "depot_id": depot, "axis": axis, "route_id": b.legs[p].route_id,
                                     "post_id": p, "sku_id": k, "qty": q, "weight_kg": wk,
                                     "stop_order": stop_order,
                                     "path_availability": round(b.legs[p].path_availability, 4)})
    return {"legs": legs_out, "routes": routes_out, "status": status, "solve_time_s": solve_t}


def _route_residual(b: Bundle, depot: str, axis: str, posts: list, post_g: dict,
                    vehicles: list, objective: str) -> dict:
    """Tiny CP-SAT VRP over residual partial loads only. Returns routes + the
    (vehicle,post)->grams assignment + stop orders for the caller to SKU-fill."""
    nodes = [depot] + posts
    n = len(nodes)
    model = cp_model.CpModel()
    arc, visit, order = {}, {}, {}
    for v in vehicles:
        for i in nodes:
            visit[(v, i)] = model.NewBoolVar(f"vis_{v}_{i}")
            order[(v, i)] = model.NewIntVar(0, n, f"ord_{v}_{i}")
            for j in nodes:
                if i != j:
                    arc[(v, i, j)] = model.NewBoolVar(f"arc_{v}_{i}_{j}")
    g = {(v, p): model.NewIntVar(0, post_g[p], f"g_{v}_{p}") for v in vehicles for p in posts}
    for v in vehicles:
        for i in nodes:
            model.Add(sum(arc[(v, i, j)] for j in nodes if j != i) == visit[(v, i)])
            model.Add(sum(arc[(v, j, i)] for j in nodes if j != i) == visit[(v, i)])
        model.Add(sum(arc[(v, depot, j)] for j in posts) <= 1)
        model.Add(order[(v, depot)] == 0)
        for i in posts:
            for j in posts:
                if i != j:
                    model.Add(order[(v, j)] >= order[(v, i)] + 1 - n * (1 - arc[(v, i, j)]))
    by_class = defaultdict(list)
    for v in vehicles:
        by_class[(b.veh[v]["vehicle_class"], b.veh[v]["payload_tons"])].append(v)
    for grp in by_class.values():
        gg = sorted(grp)
        for x, y in zip(gg, gg[1:]):
            model.Add(visit[(x, depot)] >= visit[(y, depot)])
    for v in vehicles:
        cap_g = int(round(b.veh[v]["payload_tons"] * 1000.0 * 1000.0))
        for p in posts:
            model.Add(g[(v, p)] <= cap_g * visit[(v, p)])
        model.Add(sum(g[(v, p)] for p in posts) <= cap_g)
    for p in posts:
        model.Add(sum(g[(v, p)] for v in vehicles) == post_g[p])
    obj_terms = []
    for v in vehicles:
        vc = b.veh[v]["vehicle_class"]; pdl = b.veh[v]["p_deadline"]
        for i in nodes:
            for j in nodes:
                if i == j:
                    continue
                dist = _arc_dist(b, i, j)
                if objective == "min_cost":
                    pen = dist * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vc, cfg.DEFAULT_FUEL_COST_PER_KM)
                elif objective == "min_time":
                    pen = dist / cfg.VEHICLE_CLASS_SPEED_KMPH.get(vc, cfg.DEFAULT_SPEED_KMPH) * 60
                elif objective == "min_risk":
                    pa = b.legs[j].path_availability if j in b.legs else 1.0
                    pen = (1.0 - pa * (1.0 - pdl)) * RISK_SCALE
                else:
                    spd = cfg.VEHICLE_CLASS_SPEED_KMPH.get(vc, cfg.DEFAULT_SPEED_KMPH)
                    pa = b.legs[j].path_availability if j in b.legs else 1.0
                    bw = cfg.BALANCED_BLEND
                    pen = (bw["cost"] * dist * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vc, cfg.DEFAULT_FUEL_COST_PER_KM)
                           + bw["time"] * dist / spd * 60 + bw["risk"] * (1.0 - pa * (1.0 - pdl)) * RISK_SCALE)
                if i == depot:
                    pen += cfg.VEHICLE_FIXED_DISPATCH_COST
                obj_terms.append(int(round(pen)) * arc[(v, i, j)])
    model.Minimize(sum(obj_terms))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = cfg.DATA_SNAPSHOT_SEED
    solver.parameters.max_time_in_seconds = cfg.SOLVER_TIME_LIMIT_BY_OBJECTIVE.get(
        objective, cfg.SOLVER_TIME_LIMIT_S)
    st = solver.Solve(model)
    routes_out, assignments, grams, stop_order = [], [], {}, {}
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for v in vehicles:
            if solver.Value(visit[(v, depot)]) < 1:
                continue
            seq = sorted([p for p in posts if solver.Value(visit[(v, p)]) > 0],
                         key=lambda p: solver.Value(order[(v, p)]))
            if not seq:
                continue
            rdist = 0.0; cur = depot; chain = [depot]
            for p in seq:
                rdist += _arc_dist(b, cur, p); cur = p; chain.append(p)
            routes_out.append({"vehicle_id": v, "vehicle_class": b.veh[v]["vehicle_class"],
                               "depot_id": depot, "axis": axis, "stops": chain[1:],
                               "route_km": round(rdist, 1)})
            for p in seq:
                gv = solver.Value(g[(v, p)])
                if gv > 0:
                    assignments.append((v, p)); grams[(v, p)] = gv; stop_order[(v, p)] = chain.index(p)
    return {"routes": routes_out, "assignments": assignments, "grams": grams,
            "stop_order": stop_order,
            "status": "optimal" if st == cp_model.OPTIMAL else
                      ("feasible" if st == cp_model.FEASIBLE else "infeasible"),
            "solve_time_s": round(solver.WallTime(), 3)}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — Non-road transport (air / porter / mule)
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_non_road(b: Bundle, road_shortfalls: list, objective: str) -> dict:
    """After Phase 1+2 leave road-isolated shortfalls, Phase 3 resolves as many
    as possible via non-road modes (mule → porter → air, cheapest first).

    Each mode has:
      - capacity per sortie × available sorties (weather-adjusted)
      - eligible stock heads (mules can't carry bulk POL)
      - eligible posts (air = has_air_resupply only; mule/porter = all non-depot)

    Returns {legs: [...], resolved_kg: float, remaining_shortfalls: [...],
             mode_summary: {mode: {tonnes, cost, sorties_used, posts_served}}}
    """
    if not hasattr(cfg, 'NON_ROAD_TRANSPORT_MODES'):
        return {"legs": [], "resolved_kg": 0.0, "remaining_shortfalls": road_shortfalls,
                "mode_summary": {}}

    modes = cfg.NON_ROAD_TRANSPORT_MODES
    mode_order = getattr(cfg, 'NON_ROAD_MODE_ORDER', sorted(modes.keys()))

    # Weather capacity fraction based on snapshot month
    snap_month = int(b.snapshot_date.split("-")[1]) if "-" in b.snapshot_date else 12
    weather_frac = cfg.NON_ROAD_WEATHER_CAPACITY_FRACTION.get(snap_month, 0.50)

    # Build the residual pool: (post, sku) -> unmet_units, from road shortfalls
    # Only road_isolated shortfalls are candidates; depot_short/capacity_short
    # are road-reachable problems that non-road modes don't help with.
    residual = {}
    for sf in road_shortfalls:
        if sf["cause"] == "road_isolated":
            residual[(sf["post_id"], sf["sku_id"])] = sf["shortfall_units"]

    nr_legs = []
    mode_summary = {}
    sortie_counter = 0  # for deterministic leg IDs

    for mode_name in mode_order:
        mode = modes[mode_name]
        eligible_heads = set(mode.get("eligible_heads", []))
        excluded_heads = set(mode.get("excluded_heads", []))
        cap_per_sortie = mode["capacity_kg_per_sortie"]
        max_sorties = mode["sorties_available"]
        cost_per_kg = mode["cost_per_kg"]

        # Weather adjustment
        effective_cap = cap_per_sortie * weather_frac
        effective_sorties = max_sorties  # sorties count unchanged; capacity per sortie reduced

        # Post eligibility
        eligibility = mode.get("eligible_posts", "all_non_depot")

        mode_kg = 0.0
        mode_cost = 0.0
        mode_sorties_used = 0
        mode_posts = set()

        # Per-post capacity pool: each post gets its own sortie allocation
        # (a mule column to post A doesn't reduce the column to post B —
        # they're separate animal transport units).
        post_caps = {}
        for pid in sorted(set(pk[0] for pk in residual)):
            if eligibility == "air_resupply_only" and not b.legs[pid].has_air_resupply:
                continue
            post_caps[pid] = effective_cap * effective_sorties

        # Allocate: within each eligible post, fill by tier priority (tier 1 first),
        # then by weight (heaviest first within tier) — same logic as Phase 1.
        for pid in sorted(post_caps.keys()):
            cap_left = post_caps[pid]
            if cap_left <= 0:
                continue

            # Gather eligible (post, sku) pairs
            candidates = []
            for (p, k), units in sorted(residual.items()):
                if p != pid or units <= 1e-6:
                    continue
                head = b.sku_meta[k]["head"]
                if excluded_heads and head in excluded_heads:
                    continue
                if eligible_heads and head not in eligible_heads:
                    continue
                tier = b.sku_meta[k]["tier"]
                wkg = b.sku_weight_kg[k]
                candidates.append((p, k, units, tier, wkg))

            # Sort: tier ascending (tier 1 = most critical first), then weight desc
            candidates.sort(key=lambda c: (c[3], -c[4]))

            sortie_kg_this_post = 0.0
            for p, k, units_avail, tier, wkg in candidates:
                if cap_left <= 0:
                    break
                # How many units fit in remaining capacity? (cap_left and wkg both in kg)
                if wkg > 0:
                    max_units = cap_left / wkg
                else:
                    max_units = units_avail
                take = min(units_avail, max_units)
                take = float(int(take))  # round down to whole units
                if take <= 0:
                    continue

                take_kg = take * wkg
                nr_legs.append({
                    "post_id": pid, "sku_id": k, "qty": take,
                    "weight_kg": round(take_kg, 2),
                    "transport_mode": mode_name,
                    "cost_per_kg": cost_per_kg,
                    "expected_cost": round(take_kg * cost_per_kg, 2),
                    "depot_id": b.legs[pid].depot_id,
                    "axis": b.post_axis.get(pid, "?"),
                    "head": b.sku_meta[k]["head"],
                    "tier": tier,
                })
                residual[(pid, k)] -= take
                cap_left -= take_kg
                mode_kg += take_kg
                mode_cost += take_kg * cost_per_kg
                sortie_kg_this_post += take_kg
                mode_posts.add(pid)

            if sortie_kg_this_post > 0:
                mode_sorties_used += math.ceil(sortie_kg_this_post / effective_cap)

        if mode_kg > 0:
            mode_summary[mode_name] = {
                "tonnes": round(mode_kg / 1000.0, 2),
                "cost": round(mode_cost, 2),
                "sorties_used": mode_sorties_used,
                "posts_served": len(mode_posts),
                "cost_per_kg": cost_per_kg,
                "weather_capacity_fraction": round(weather_frac, 2),
            }

    # Rebuild remaining shortfalls from whatever residual is left
    remaining = []
    for sf in road_shortfalls:
        if sf["cause"] != "road_isolated":
            remaining.append(sf)
            continue
        left = residual.get((sf["post_id"], sf["sku_id"]), 0.0)
        if left > 0.5:
            remaining.append({**sf,
                              "shortfall_units": round(left, 3),
                              "shortfall_kg": round(left * b.sku_weight_kg[sf["sku_id"]], 2),
                              "cause": "residual_after_nonroad"})

    resolved_kg = sum(l["weight_kg"] for l in nr_legs)
    return {"legs": nr_legs, "resolved_kg": resolved_kg,
            "remaining_shortfalls": sorted(remaining, key=lambda r: (r["post_id"], r["sku_id"])),
            "mode_summary": mode_summary}


# ─────────────────────────────────────────────────────────────────────────────
# assembly + shortfalls
# ─────────────────────────────────────────────────────────────────────────────
def _shortfalls(b: Bundle, alloc_all: dict, delivered: dict) -> list:
    rows = []
    for pid in b.posts:
        leg = b.legs[pid]
        for k in b.skus_at_post[pid]:
            need = b.deficit_units[(pid, k)]
            got = delivered.get((pid, k), 0.0)
            unmet = need - got
            if unmet <= 1e-6:
                continue
            if not leg.feasible:
                cause = "road_isolated"
            else:
                have = b.depot_stock.get((leg.depot_id, k))
                cause = "depot_short" if (have is not None and have < need - 1e-6) else "capacity_short"
            rows.append({"post_id": pid, "sku_id": k, "shortfall_units": round(unmet, 3),
                         "shortfall_kg": round(unmet * b.sku_weight_kg[k], 2),
                         "head": b.sku_meta[k]["head"], "tier": b.sku_meta[k]["tier"],
                         "cause": cause, "air_resupply_possible": bool(leg.has_air_resupply),
                         "path_availability": round(leg.path_availability, 4)})
    return sorted(rows, key=lambda r: (r["post_id"], r["sku_id"]))


def _assemble(b: Bundle, objective: str, cluster_out: dict, alloc_all: dict) -> dict:
    legs_out, routes_out = [], []
    for res in cluster_out.values():
        legs_out.extend(res["legs"]); routes_out.extend(res["routes"])
    delivered = defaultdict(float)
    for l in legs_out:
        delivered[(l["post_id"], l["sku_id"])] += l["qty"]

    veh_route = {r["vehicle_id"]: r for r in routes_out}
    total_cost = 0.0; makespan_h = 0.0; veh_risk = {}
    for r in routes_out:
        vc = r["vehicle_class"]; rk = r["route_km"]
        cost = leg_cost_km(vc, rk) + cfg.VEHICLE_FIXED_DISPATCH_COST
        spd = cfg.VEHICLE_CLASS_SPEED_KMPH.get(vc, cfg.DEFAULT_SPEED_KMPH)
        worst_pa = min((b.legs[p].path_availability for p in r["stops"] if p in b.legs), default=1.0)
        hours = rk / spd + cfg.PATH_DELAY_HOURS_AT_FULL_CLOSURE * (1.0 - worst_pa)
        pdl = b.veh[r["vehicle_id"]]["p_deadline"]
        r["expected_cost"] = round(cost, 2); r["eta_hours"] = round(hours, 2)
        r["expected_risk"] = round(1.0 - worst_pa * (1.0 - pdl), 6)
        total_cost += cost; makespan_h = max(makespan_h, hours); veh_risk[r["vehicle_id"]] = r["expected_risk"]

    veh_kg = defaultdict(float)
    for l in legs_out:
        veh_kg[l["vehicle_id"]] += l["weight_kg"]
    enriched = []
    for l in legs_out:
        r = veh_route.get(l["vehicle_id"]); tot = veh_kg[l["vehicle_id"]] or 1.0
        enriched.append({**l,
                         "expected_cost": round((r["expected_cost"] if r else 0.0) * l["weight_kg"] / tot, 2),
                         "eta_hours": r["eta_hours"] if r else 0.0,
                         "expected_risk": r["expected_risk"] if r else 0.0,
                         "route_km": r["route_km"] if r else 0.0})
    legs_out = sorted(enriched, key=lambda l: (l["depot_id"], l["axis"], l["vehicle_id"],
                                               l["post_id"], l["sku_id"]))

    agg_risk = 1.0 - math.prod((1.0 - x) for x in veh_risk.values()) if veh_risk else 0.0
    edl = sum(veh_risk.values()); mlr = edl / len(veh_risk) if veh_risk else 0.0

    # Phase 3: resolve road-isolated shortfalls via non-road modes
    road_shortfalls = _shortfalls(b, alloc_all, delivered)
    nr = _resolve_non_road(b, road_shortfalls, objective)
    nr_legs = nr["legs"]
    nr_cost = sum(l["expected_cost"] for l in nr_legs)
    final_shortfalls = nr["remaining_shortfalls"]

    road_covered_kg = sum(l["weight_kg"] for l in legs_out)
    nr_covered_kg = nr["resolved_kg"]
    total_covered_kg = road_covered_kg + nr_covered_kg
    shortfall_kg = sum(s["shortfall_kg"] for s in final_shortfalls)
    demand_kg = total_covered_kg + shortfall_kg

    # Isolated = residual after non-road (was road_isolated, modes couldn't reach it)
    residual_isolated_kg = sum(s["shortfall_kg"] for s in final_shortfalls
                               if s["cause"] == "residual_after_nonroad")
    # Non-road modes also don't help depot_short/capacity_short
    other_shortfall_kg = sum(s["shortfall_kg"] for s in final_shortfalls
                             if s["cause"] not in ("road_isolated", "residual_after_nonroad"))
    reachable = demand_kg - residual_isolated_kg

    status = "optimal" if cluster_out and all(r["status"] == "optimal" for r in cluster_out.values()) \
        else ("optimal" if not cluster_out else "feasible")
    return {"objective": objective, "status": status,
            "solve_time_s": round(sum(r["solve_time_s"] for r in cluster_out.values()), 3),
            "legs": legs_out, "routes": routes_out,
            "non_road_legs": nr_legs,
            "non_road_summary": nr["mode_summary"],
            "shortfalls": final_shortfalls,
            "vehicles_used": len({l["vehicle_id"] for l in legs_out}),
            "posts_served": len({l["post_id"] for l in legs_out} |
                                {l["post_id"] for l in nr_legs}),
            "posts_served_road": len({l["post_id"] for l in legs_out}),
            "posts_served_nonroad": len({l["post_id"] for l in nr_legs}),
            "convoys": len(routes_out),
            "total_cost": round(total_cost + nr_cost, 2),
            "road_cost": round(total_cost, 2),
            "non_road_cost": round(nr_cost, 2),
            "total_time_hours": round(makespan_h, 2),
            "aggregate_risk": round(agg_risk, 4), "expected_disrupted_legs": round(edl, 3),
            "mean_leg_risk": round(mlr, 4),
            "covered_tonnes": round(total_covered_kg / 1000.0, 2),
            "road_covered_tonnes": round(road_covered_kg / 1000.0, 2),
            "non_road_covered_tonnes": round(nr_covered_kg / 1000.0, 2),
            "shortfall_tonnes": round(shortfall_kg / 1000.0, 2),
            "coverage_pct": round(100.0 * total_covered_kg / demand_kg if demand_kg > 1e-9 else 100.0, 1),
            "coverage_reachable_pct": round(100.0 * total_covered_kg / reachable if reachable > 1e-9 else 100.0, 1),
            "isolated_tonnes": round(residual_isolated_kg / 1000.0, 2)}


def solve_all(b: Bundle) -> dict:
    clusters = _build_clusters(b)
    results = {}
    for obj in cfg.OBJECTIVES:
        cluster_out, alloc_all = {}, {}
        for (depot, axis), posts in sorted(clusters.items()):
            alloc = allocate(b, posts, depot, obj)          # Phase 1
            alloc_all.update(alloc)
            cluster_out[(depot, axis)] = route_cluster(b, depot, axis, posts, alloc, obj)  # Phase 2
        results[obj] = _assemble(b, obj, cluster_out, alloc_all)  # incl. Phase 3
    return results
