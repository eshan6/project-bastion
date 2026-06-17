"""
Project Bastion — Stage 4 optimizer (ε-constraint frontier planner, v3.0)

WHAT CHANGED FROM v2.0 AND WHY
──────────────────────────────
v2.0's four objectives (min_cost / min_time / min_risk / balanced) produced four
near-identical plans on the seed-42 / 15-Dec snapshot: coverage byte-identical,
cost within 1.1%, makespan within 8%, aggregate_risk pinned at 1.0 in all four.
Measured root causes:
  1. Phase-1 allocation accepted `objective` and never read it — every plan
     shipped the identical manifest.
  2. 84 of 90 convoys were full-truckload shuttles assigned by an
     objective-blind greedy; only 4.9% of tonnage reached the objective-aware
     residual VRP.
  3. The fleet has no cost-vs-time tradeoff (the cheapest class per km is also
     the fastest), so min_cost ≡ min_time.
  4. Each post has exactly one inbound path, so min_risk had no route choice;
     and compounded P(any leg fails) saturates at 1.0 with ~90 convoys.

v3.0 therefore restructures WHAT the objectives are allowed to trade:

  full_coverage  Lexicographic max coverage, then min routing cost (the v2.0
                 behaviour, honestly named). Reference plan for the floors.
  min_cost       Minimize rupees subject to covering ≥ 98% (config) of the
                 full_coverage tonnage per depot, Tier-1 never sacrificed.
                 Frees the allocator to drop the most expensive marginal
                 tonnage and the router to pick the cheapest ₹/t·km fleet mix.
  min_exposure   Minimize tier-weighted EXPECTED SHORTFALL: kg deliberately
                 unshipped count in full; kg shipped count × P(leg fails);
                 plus an exposure charge (config.EXPOSURE_WEIGHT) per kg sent
                 over a marginal pass — the cost of putting men and vehicles
                 on a road that is probably shut. Tier-1 floored at the
                 full_coverage level; total floored at 95% (config). Convoys
                 staffed most-reliable-vehicle-first.

  min_time is REMOVED until the world contains a real time axis (multi-modal
  legs / multi-day dispatch windows). Documented in config.py.

ALLOCATION BUG FIX (correctness, changes the headline number)
──────────────────────────────────────────────────────────────
v2.0 allocated per (depot, axis) cluster with the FULL depot stock cap in each
cluster and no decrement. Depots P003/P004 serve two axes each, and several
(depot, SKU) pairs are stock-binding — the same stock was promised to both
axes. v3.0 allocates ONCE PER DEPOT, jointly across that depot's axes, then
routes per (depot, axis) cluster. Reported coverage drops accordingly: the old
figure was optimistic by the double-counted stock. Honest numbers only.

RISK REFORMULATION
──────────────────
aggregate_risk = 1 − Π(1 − r_v) is retained for schema continuity but is
documented as saturating (it answers "P(≥1 of ~90 sorties has any trouble)",
which is ~1 by construction in winter). The decision-grade metrics are now:
  expected_arrived_tonnes    Σ route_kg × (1 − route_risk)
  expected_loss_tonnes       shipped − expected_arrived
  unserved_reachable_tonnes  reachable demand deliberately or capacity-unmet
  expected_shortfall_tonnes  loss + unserved_reachable  (excludes road-isolated,
                             which no road plan can address — that stays its own
                             honestly-surfaced number)
  max_leg_risk, risky_sorties (convoys whose worst path P(open) < 0.5)

Shortfall rows gain cause "objective_tradeoff" when a floor-constrained plan
deliberately leaves reachable, in-stock tonnage behind — so a planner can see
exactly what min_cost / min_exposure chose to sacrifice, post by post, SKU by
SKU. A dropped delivery is a decision, never a silent omission.

PHASE STRUCTURE (unchanged in spirit, still exact)
──────────────────────────────────────────────────
  PHASE 1 — per-DEPOT allocation LP (GLOP, provably optimal per formulation).
  PHASE 2 — per-(depot,axis) routing: full-truckload shuttles assigned directly
            (a full truck cannot milk-run), residual partial loads solved as a
            tiny CP-SAT VRP (provably optimal on ≤8-node clusters).
Vehicle ranking inside Phase 2 is now objective-aware:
  full_coverage  largest payload first (fewest sorties)
  min_cost       cheapest ₹ per tonne-km first
  min_exposure   lowest P(deadline) first (most reliable vehicles)

Determinism: GLOP LP deterministic; CP-SAT single worker + fixed seed; all var
creation and iteration over sorted keys. Verified byte-identical across runs.
"""
from __future__ import annotations
import math
from collections import defaultdict
from ortools.linear_solver import pywraplp
from ortools.sat.python import cp_model
import config as cfg
from inputs import Bundle

RISK_SCALE = 10000

# class payloads (tons) — mirrors stage2_world vehicle generation
CLASS_PAYLOAD_TONS = {"Tata-LPTA": 2.5, "Stallion-4x4": 5.0,
                      "Stallion-6x6": 7.5, "BharatBenz-HD": 10.0}


def leg_cost_km(vclass: str, distance_km: float) -> float:
    return distance_km * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM)


def _rupee_per_tonne_km(vclass: str) -> float:
    """Cost-efficiency of a class when running full."""
    payload = CLASS_PAYLOAD_TONS.get(vclass, 5.0)
    rate = cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM)
    return rate / payload


def _best_rupee_per_tonne_km() -> tuple:
    """(₹ per tonne-km, payload_tons) of the most cost-efficient class."""
    best_vc = min(sorted(cfg.VEHICLE_CLASS_FUEL_COST_PER_KM), key=_rupee_per_tonne_km)
    return _rupee_per_tonne_km(best_vc), CLASS_PAYLOAD_TONS[best_vc]


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


def _rank_vehicles(b: Bundle, pool: list, objective: str) -> list:
    """Objective-aware vehicle ordering — a real decision v2.0 threw away."""
    if objective == "min_exposure":
        # maximize expected ARRIVED kg per sortie: payload × P(vehicle survives).
        # (Pure reliability-first was tried and backfired: it staffed convoys
        # with small young trucks, inflating sortie count 82→117 and putting
        # MORE convoys on marginal passes. Fewer, bigger, reliable loads win.)
        key = lambda v: (-(b.veh[v]["payload_tons"] * (1.0 - b.veh[v]["p_deadline"])), v)
    elif objective == "min_cost":
        key = lambda v: (_rupee_per_tonne_km(b.veh[v]["vehicle_class"]),
                         -b.veh[v]["payload_tons"], v)
    else:  # full_coverage: fewest sorties
        key = lambda v: (-b.veh[v]["payload_tons"], b.veh[v]["p_deadline"], v)
    return sorted(pool, key=key)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — per-DEPOT allocation (joint across the depot's axes — the v3 fix)
# ─────────────────────────────────────────────────────────────────────────────
def allocate_depot(b: Bundle, depot: str, posts: list, objective: str,
                   fc_ref: dict | None = None) -> dict:
    """Return {(post, sku): allocated_units} for ALL feasible posts this depot
    serves, across every axis, against the depot's stock exactly once.

    full_coverage : maximize tier+status-weighted covered kg (lexicographic
                    reference plan). fc_ref unused.
    min_cost      : minimize Σ ₹-proxy(post)·kg·alloc subject to
                      covered_kg ≥ floor · fc_covered_kg, tier1_kg ≥ fc_tier1_kg.
    min_exposure  : maximize Σ kg·alloc·(tier_w·pa − EW·(1−pa)) — i.e. minimize
                    tier-weighted expected shortfall plus the exposure charge —
                    under the same style of floors at its own (lower) coverage
                    fraction. pa = path availability of the post's single leg;
                    EW = config.EXPOSURE_WEIGHT.

    LP over continuous units (GLOP, provably optimal), rounded at the end.
    Falls back to the full_coverage allocation if a constrained LP is ever
    infeasible (floors are ≤ the fc optimum by construction; guarded anyway).
    """
    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        solver = pywraplp.Solver.CreateSolver("CBC")
    a = {}
    for p in posts:
        for k in b.skus_at_post[p]:
            a[(p, k)] = solver.NumVar(0.0, b.deficit_units[(p, k)], f"a_{p}_{k}")

    # depot stock caps per SKU — JOINT across all this depot's posts/axes
    for k in sorted({k for p in posts for k in b.skus_at_post[p]}):
        cap = b.depot_stock.get((depot, k))
        if cap is not None:
            solver.Add(solver.Sum(a[(p, k)] for p in posts
                                  if k in b.skus_at_post[p]) <= cap)

    all_pairs = sorted(a.keys())
    t1_pairs = [pk for pk in all_pairs if b.sku_meta[pk[1]]["tier"] == 1]

    def kg_expr(pairs):
        return solver.Sum(a[pk] * b.sku_weight_kg[pk[1]] for pk in pairs)

    obj = solver.Objective()
    if objective == "full_coverage":
        for (p, k) in all_pairs:
            st = cfg.STATUS_PRIORITY.get(b.post_status.get(p, "ok"), 1.0)
            prio = cfg.TIER_PRIORITY.get(b.sku_meta[k]["tier"], 1.0) * st
            obj.SetCoefficient(a[(p, k)], prio * b.sku_weight_kg[k])
        obj.SetMaximization()
    else:
        floor = cfg.COVERAGE_FLOOR_FRAC[objective]
        # fc_ref totals come from the ROUNDED reference allocation; rounding can
        # overshoot the LP-achievable optimum by a fraction of a unit per pair.
        # A 0.1% slack on the Tier-1 floor keeps the constraint feasible without
        # materially weakening it (verified: without slack the LP is infeasible
        # by rounding epsilon and silently falls back to full_coverage).
        solver.Add(kg_expr(all_pairs) >= floor * fc_ref["covered_kg"] - 1e-6)
        solver.Add(kg_expr(t1_pairs) >= 0.999 * fc_ref["tier1_kg"] - 1e-6)
        if objective == "min_cost":
            tkm, payload_t = _best_rupee_per_tonne_km()
            for (p, k) in all_pairs:
                # ₹ per kg delivered to p: line-haul at best-class efficiency
                # + amortized fixed dispatch over a full best-class load
                c = (b.legs[p].distance_km * tkm / 1000.0
                     + cfg.VEHICLE_FIXED_DISPATCH_COST / (payload_t * 1000.0))
                obj.SetCoefficient(a[(p, k)], c * b.sku_weight_kg[k])
            obj.SetMinimization()
        else:  # min_exposure
            ew = cfg.EXPOSURE_WEIGHT
            for (p, k) in all_pairs:
                pa = b.legs[p].path_availability
                tw = cfg.TIER_PRIORITY.get(b.sku_meta[k]["tier"], 1.0)
                obj.SetCoefficient(a[(p, k)],
                                   (tw * pa - ew * (1.0 - pa)) * b.sku_weight_kg[k])
            obj.SetMaximization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL and objective != "full_coverage":
        return allocate_depot(b, depot, posts, "full_coverage")
    out = {}
    for (p, k), var in a.items():
        v = var.solution_value()
        if v > 0.5:
            out[(p, k)] = float(round(v))
    # HARD Tier-1 guarantee: constrained plans restore Tier-1 allocations to the
    # full_coverage reference exactly (the 0.1% floor slack exists only to absorb
    # rounding; it must never surface as a Tier-1 sacrifice in the shortfall
    # table). Stock-cap safe: the reference allocation already satisfied caps,
    # and Tier-1 SKUs share their caps only with other Tier-1 rows of that SKU.
    if objective != "full_coverage" and fc_ref and "alloc" in fc_ref:
        for (p, k), q in fc_ref["alloc"].items():
            if b.sku_meta[k]["tier"] == 1:
                out[(p, k)] = q
        out = {pk: q for pk, q in out.items() if q > 0}
    return out


def _alloc_totals(b: Bundle, alloc: dict) -> dict:
    kg = sum(q * b.sku_weight_kg[k] for (p, k), q in alloc.items())
    t1 = sum(q * b.sku_weight_kg[k] for (p, k), q in alloc.items()
             if b.sku_meta[k]["tier"] == 1)
    return {"covered_kg": kg, "tier1_kg": t1}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — routing (per cluster, fixed allocations)
# ─────────────────────────────────────────────────────────────────────────────
def route_cluster(b: Bundle, depot: str, axis: str, posts: list,
                  alloc: dict, objective: str) -> dict:
    """Exact decomposition by load structure (logic as v2.0, but vehicle
    ranking is now objective-aware):

      • FULL-TRUCKLOAD SHUTTLES: a post needing many truckloads is served by
        full trucks depot→post→depot. A full truck has no spare capacity to
        drop elsewhere, so its route needs no search.
      • RESIDUAL MILK-RUN: leftover partial loads routed by a tiny CP-SAT VRP
        (provably optimal on ≤8-node clusters).

    SKU breakdown per truck is filled deterministically (largest weight first),
    always feasible because capacity dominates."""
    served = [p for p in posts if any((p, k) in alloc for k in b.skus_at_post[p])]
    if not served:
        return {"legs": [], "routes": [], "status": "optimal", "solve_time_s": 0.0}

    post_g = {p: int(round(sum(alloc[(p, k)] * b.sku_weight_kg[k] * 1000.0
                               for k in b.skus_at_post[p] if (p, k) in alloc)))
              for p in served}
    pool = b.vehicles_by_depot.get(depot, [])
    ranked = _rank_vehicles(b, pool, objective)
    if not ranked:
        return {"legs": [], "routes": [], "status": "infeasible", "solve_time_s": 0.0}

    routes_out, legs_out = [], []
    remaining = {(p, k): alloc[(p, k)] for p in served
                 for k in b.skus_at_post[p] if (p, k) in alloc}
    veh_ptr = 0

    def fill_truck(v, p, grams_cap):
        """Greedy SKU fill of one truck visiting post p; mutate remaining; emit legs."""
        vc = b.veh[v]["vehicle_class"]; placed = []
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
        while post_g[p] >= 0 and veh_ptr < len(ranked):
            need_g = int(round(sum(remaining[(p, k)] * b.sku_weight_kg[k] * 1000.0
                                   for k in b.skus_at_post[p] if (p, k) in remaining)))
            if need_g <= 0:
                break
            v = ranked[veh_ptr]
            cap_g = int(round(b.veh[v]["payload_tons"] * 1000.0 * 1000.0))
            if need_g < cap_g:        # remainder is a residual, not a full load
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
                if objective == "min_exposure":
                    pa = b.legs[j].path_availability if j in b.legs else 1.0
                    pen = (1.0 - pa * (1.0 - pdl)) * RISK_SCALE
                else:  # full_coverage and min_cost: cost is the routing penalty
                    pen = dist * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vc, cfg.DEFAULT_FUEL_COST_PER_KM)
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
                    assignments.append((v, p)); grams[(v, p)] = gv
                    stop_order[(v, p)] = chain.index(p)
    return {"routes": routes_out, "assignments": assignments, "grams": grams,
            "stop_order": stop_order,
            "status": "optimal" if st == cp_model.OPTIMAL else
                      ("feasible" if st == cp_model.FEASIBLE else "infeasible"),
            "solve_time_s": round(solver.WallTime(), 3)}


# ─────────────────────────────────────────────────────────────────────────────
# assembly + shortfalls
# ─────────────────────────────────────────────────────────────────────────────
def _shortfalls(b: Bundle, delivered: dict, objective: str, alloc: dict) -> list:
    """Per-(post, SKU) unmet demand with an honest cause tag. v3.0 adds cause
    'objective_tradeoff': reachable, in-stock tonnage a floor-constrained plan
    DELIBERATELY left behind (allocated < deficit by the LP's choice) — a
    decision the planner can see and overrule. Sub-unit truck-fill rounding
    crumbs are NOT tradeoffs and stay labeled capacity_short, so the tradeoff
    table contains only genuine decisions."""
    # total reachable need per (depot, sku), to identify true depot shortage
    depot_need = defaultdict(float)
    for pid in b.posts:
        leg = b.legs[pid]
        if not leg.feasible:
            continue
        for k in b.skus_at_post[pid]:
            depot_need[(leg.depot_id, k)] += b.deficit_units[(pid, k)]
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
                allocated = alloc.get((pid, k), 0.0)
                if have is not None and have < depot_need[(leg.depot_id, k)] - 1e-6:
                    cause = "depot_short"
                elif objective != "full_coverage" and allocated < need - 0.5:
                    cause = "objective_tradeoff"   # the LP chose to leave this
                else:
                    cause = "capacity_short"       # truck-fill rounding crumb
            rows.append({"post_id": pid, "sku_id": k, "shortfall_units": round(unmet, 3),
                         "shortfall_kg": round(unmet * b.sku_weight_kg[k], 2),
                         "head": b.sku_meta[k]["head"], "tier": b.sku_meta[k]["tier"],
                         "cause": cause, "air_resupply_possible": bool(leg.has_air_resupply),
                         "path_availability": round(leg.path_availability, 4)})
    return sorted(rows, key=lambda r: (r["post_id"], r["sku_id"]))


def _assemble(b: Bundle, objective: str, cluster_out: dict, alloc: dict) -> dict:
    legs_out, routes_out = [], []
    for res in cluster_out.values():
        legs_out.extend(res["legs"]); routes_out.extend(res["routes"])
    delivered = defaultdict(float)
    for l in legs_out:
        delivered[(l["post_id"], l["sku_id"])] += l["qty"]

    # map each leg to its route — a vehicle may run multiple sorties (one per
    # cluster); key (vehicle, post) is unique because a vehicle visits a given
    # post on at most one sortie
    route_of = {}
    for idx, r in enumerate(routes_out):
        for p in r["stops"]:
            route_of[(r["vehicle_id"], p)] = idx

    total_cost = 0.0; makespan_h = 0.0
    risky_sorties = 0; max_leg_risk = 0.0
    for r in routes_out:
        vc = r["vehicle_class"]; rk = r["route_km"]
        cost = leg_cost_km(vc, rk) + cfg.VEHICLE_FIXED_DISPATCH_COST
        spd = cfg.VEHICLE_CLASS_SPEED_KMPH.get(vc, cfg.DEFAULT_SPEED_KMPH)
        worst_pa = min((b.legs[p].path_availability for p in r["stops"] if p in b.legs),
                       default=1.0)
        hours = rk / spd + cfg.PATH_DELAY_HOURS_AT_FULL_CLOSURE * (1.0 - worst_pa)
        pdl = b.veh[r["vehicle_id"]]["p_deadline"]
        r["expected_cost"] = round(cost, 2); r["eta_hours"] = round(hours, 2)
        r["expected_risk"] = round(1.0 - worst_pa * (1.0 - pdl), 6)
        total_cost += cost; makespan_h = max(makespan_h, hours)
        max_leg_risk = max(max_leg_risk, r["expected_risk"])
        if worst_pa < cfg.RISKY_SORTIE_PAVAIL:
            risky_sorties += 1

    # per-route cargo (correct under multi-sortie vehicles)
    route_kg = defaultdict(float)
    for l in legs_out:
        idx = route_of.get((l["vehicle_id"], l["post_id"]))
        if idx is not None:
            route_kg[idx] += l["weight_kg"]

    enriched = []
    for l in legs_out:
        idx = route_of.get((l["vehicle_id"], l["post_id"]))
        r = routes_out[idx] if idx is not None else None
        rkg = route_kg.get(idx, 0.0) or 1.0
        enriched.append({**l,
                         "expected_cost": round((r["expected_cost"] if r else 0.0) * l["weight_kg"] / rkg, 2),
                         "eta_hours": r["eta_hours"] if r else 0.0,
                         "expected_risk": r["expected_risk"] if r else 0.0,
                         "route_km": r["route_km"] if r else 0.0})
    legs_out = sorted(enriched, key=lambda l: (l["depot_id"], l["axis"], l["vehicle_id"],
                                               l["post_id"], l["sku_id"]))

    # risk metrics — decision-grade (see module docstring)
    expected_arrived_kg = sum(route_kg[i] * (1.0 - routes_out[i]["expected_risk"])
                              for i in route_kg)
    agg_risk = (1.0 - math.prod((1.0 - r["expected_risk"]) for r in routes_out)
                if routes_out else 0.0)
    edl = sum(r["expected_risk"] for r in routes_out)
    mlr = edl / len(routes_out) if routes_out else 0.0

    shortfalls = _shortfalls(b, delivered, objective, alloc)
    covered_kg = sum(l["weight_kg"] for l in legs_out)
    shortfall_kg = sum(s["shortfall_kg"] for s in shortfalls)
    demand_kg = covered_kg + shortfall_kg
    isolated_kg = sum(s["shortfall_kg"] for s in shortfalls if s["cause"] == "road_isolated")
    tradeoff_kg = sum(s["shortfall_kg"] for s in shortfalls if s["cause"] == "objective_tradeoff")
    reachable = demand_kg - isolated_kg
    unserved_reachable_kg = shortfall_kg - isolated_kg
    expected_loss_kg = covered_kg - expected_arrived_kg
    status = "optimal" if cluster_out and all(r["status"] == "optimal" for r in cluster_out.values()) \
        else ("optimal" if not cluster_out else "feasible")
    return {"objective": objective, "status": status,
            "solve_time_s": round(sum(r["solve_time_s"] for r in cluster_out.values()), 3),
            "legs": legs_out, "routes": routes_out, "shortfalls": shortfalls,
            "vehicles_used": len({l["vehicle_id"] for l in legs_out}),
            "posts_served": len({l["post_id"] for l in legs_out}),
            "convoys": len(routes_out),
            "total_cost": round(total_cost, 2), "total_time_hours": round(makespan_h, 2),
            "aggregate_risk": round(agg_risk, 4),
            "expected_disrupted_legs": round(edl, 3),
            "mean_leg_risk": round(mlr, 4),
            "max_leg_risk": round(max_leg_risk, 4),
            "risky_sorties": risky_sorties,
            "expected_arrived_tonnes": round(expected_arrived_kg / 1000.0, 2),
            "expected_loss_tonnes": round(expected_loss_kg / 1000.0, 2),
            "unserved_reachable_tonnes": round(unserved_reachable_kg / 1000.0, 2),
            "objective_tradeoff_tonnes": round(tradeoff_kg / 1000.0, 2),
            "expected_shortfall_tonnes": round((expected_loss_kg + unserved_reachable_kg) / 1000.0, 2),
            "covered_tonnes": round(covered_kg / 1000.0, 2),
            "shortfall_tonnes": round(shortfall_kg / 1000.0, 2),
            "coverage_pct": round(100.0 * covered_kg / demand_kg if demand_kg > 1e-9 else 100.0, 1),
            "coverage_reachable_pct": round(100.0 * covered_kg / reachable if reachable > 1e-9 else 100.0, 1),
            "isolated_tonnes": round(isolated_kg / 1000.0, 2)}


def solve_all(b: Bundle) -> dict:
    clusters = _build_clusters(b)
    # group each depot's feasible posts across ALL its axes (joint allocation —
    # the v3.0 fix for per-axis stock double-allocation)
    depot_posts = defaultdict(list)
    for (depot, axis), posts in sorted(clusters.items()):
        depot_posts[depot].extend(posts)
    depot_posts = {d: sorted(ps) for d, ps in depot_posts.items()}

    # reference (full_coverage) allocation per depot — defines the floors
    fc_alloc, fc_ref = {}, {}
    for depot in sorted(depot_posts):
        alloc = allocate_depot(b, depot, depot_posts[depot], "full_coverage")
        fc_alloc[depot] = alloc
        fc_ref[depot] = {**_alloc_totals(b, alloc), "alloc": alloc}

    results = {}
    for obj in cfg.OBJECTIVES:
        alloc_all = {}
        for depot in sorted(depot_posts):
            if obj == "full_coverage":
                alloc = fc_alloc[depot]
            else:
                alloc = allocate_depot(b, depot, depot_posts[depot], obj, fc_ref[depot])
            alloc_all.update(alloc)
        cluster_out = {}
        for (depot, axis), posts in sorted(clusters.items()):
            cluster_out[(depot, axis)] = route_cluster(b, depot, axis, posts, alloc_all, obj)
        results[obj] = _assemble(b, obj, cluster_out, alloc_all)
    return results
