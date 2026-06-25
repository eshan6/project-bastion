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
CLASS_PAYLOAD_TONS = {"Tata-LPTA": 2.5, "Stallion-4x4": 5.0,
                      "Stallion-6x6": 7.5, "BharatBenz-HD": 10.0}

# v3.x NOTE: this file is the pristine v2.2 two-phase planner (Phases 1/2/3 incl.
# air/porter/mule) transformed in place to add: the ε-constraint frontier
# (full_coverage/min_cost/min_exposure), per-DEPOT joint allocation (the v3.0
# depot-stock double-count fix), time-expanded dispatch scheduling (Phase 2.5),
# expected-shortfall risk, and wargaming/wartime mode plumbing. Phase 3 non-road
# transport is preserved unchanged and runs after road routing as before.


def leg_cost_km(vclass: str, distance_km: float) -> float:
    return distance_km * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM)


def _rupee_per_tonne_km(vclass: str) -> float:
    payload = CLASS_PAYLOAD_TONS.get(vclass, 5.0)
    return cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vclass, cfg.DEFAULT_FUEL_COST_PER_KM) / payload


def _best_rupee_per_tonne_km() -> tuple:
    best = min(sorted(cfg.VEHICLE_CLASS_FUEL_COST_PER_KM), key=_rupee_per_tonne_km)
    return _rupee_per_tonne_km(best), CLASS_PAYLOAD_TONS[best]


def _mode_ctx(mode_cfg: dict | None, time_limit: float | None) -> dict:
    mc = mode_cfg or {}
    return {"objectives": mc.get("objectives", cfg.OBJECTIVES),
            "ammo_tier_override": mc.get("ammo_tier_override"),
            "exposure_weight": mc.get("exposure_weight", cfg.EXPOSURE_WEIGHT),
            "coverage_floor_frac": mc.get("coverage_floor_frac", cfg.COVERAGE_FLOOR_FRAC),
            "earliness_weight": mc.get("earliness_weight", cfg.PEACETIME_EARLINESS_WEIGHT),
            "time_limit": time_limit}


def _tier(b: Bundle, k: str, ctx: dict) -> int:
    t = b.sku_meta[k]["tier"]
    if ctx.get("ammo_tier_override") and b.sku_meta[k]["head"] == "Ammunition":
        return min(t, ctx["ammo_tier_override"])
    return t


def _diversions(b: Bundle, objective: str, ctx: dict) -> set:
    """v3.4: (post,sku) pairs to proactively route by NON-ROAD because their best
    road path is too marginal to risk critical cargo on. Returns a set; empty
    unless the objective opts in (config.MULTIMODAL_DIVERT_OBJECTIVES) or wartime
    raises ammunition. The diverted pairs are removed from the road manifest and
    resolved by Phase 3's mule->porter->air as a first-class pre-road manifest."""
    objs = getattr(cfg, "MULTIMODAL_DIVERT_OBJECTIVES", [])
    wartime_ammo = ctx.get("ammo_tier_override") == 1
    if objective not in objs and not (wartime_ammo and objective == "max_tempo"):
        return set()
    thr = getattr(cfg, "MULTIMODAL_ROAD_PA_THRESHOLD", 0.40)
    out = set()
    for pid in b.posts:
        leg = b.legs[pid]
        if not leg.feasible or leg.path_availability >= thr:
            continue
        heads = set(getattr(cfg, "MULTIMODAL_DIVERT_HEADS", []))
        for k in b.skus_at_post[pid]:
            if (_tier(b, k, ctx) <= getattr(cfg, "MULTIMODAL_DIVERT_TIER", 1)
                    and (not heads or b.sku_meta[k]["head"] in heads)):
                out.add((pid, k))
    return out


def _select_paths(b: Bundle, objective: str) -> Bundle:
    """v3.3: choose ONE road path per post from its candidates, per objective,
    then return a Bundle view whose active legs reflect that choice. This is the
    routing decision the single-path world could not express.

      min_exposure : highest path availability (take the safer, longer road).
      min_cost     : shortest distance (cheapest haul) among FEASIBLE candidates.
      full_coverage / max_tempo : primary (doctrine route) unless infeasible, in
                     which case the most-available feasible candidate (so the
                     plan still reaches the post).
    Ties broken by route_id. Posts with a single candidate are unchanged."""
    import copy
    from dataclasses import replace as _dc
    legs = {}
    for pid, leg in b.legs.items():
        cands = leg.candidates or ()
        if len(cands) <= 1:
            legs[pid] = leg
            continue
        feas = [c for c in cands if c.feasible] or list(cands)
        if objective == "min_exposure":
            pick = max(feas, key=lambda c: (c.path_availability, -c.distance_km, c.route_id))
        elif objective == "min_cost":
            pick = min(feas, key=lambda c: (c.distance_km, -c.path_availability, c.route_id))
        else:  # full_coverage / max_tempo: primary if feasible, else safest feasible
            prim = next((c for c in cands if c.kind == "primary"), cands[0])
            pick = prim if prim.feasible else max(feas, key=lambda c: (c.path_availability,
                                                                       -c.distance_km, c.route_id))
        legs[pid] = _dc(leg, depot_id=pick.depot_id, route_id=pick.route_id,
                        distance_km=pick.distance_km, passes=list(pick.passes),
                        path_availability=pick.path_availability, feasible=pick.feasible,
                        pa_by_slot=pick.pa_by_slot)
    nb = copy.copy(b)
    nb.legs = legs
    return nb


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
def allocate_depot(b: Bundle, depot: str, posts: list, objective: str,
                   fc_ref: dict | None = None, ctx: dict | None = None) -> dict:
    """v3.0 per-DEPOT joint allocation (fixes the v2 bug where a depot serving
    two axes had its stock cap applied once per axis, double-counting stock).
    Returns {(post,sku): units} for ALL feasible posts this depot serves, across
    every axis, against the depot's stock exactly once.

      full_coverage : maximize tier+status-weighted covered kg (reference plan).
      min_cost      : minimize ₹-proxy(post)·kg·alloc s.t. covered_kg >= floor·fc,
                      tier1_kg >= fc_tier1_kg.
      min_exposure  : maximize kg·alloc·(tier_w·pa − EW·(1−pa)) under the same
                      style of floors (its own, lower fraction).

    GLOP LP over continuous units, rounded. Falls back to full_coverage if a
    constrained LP is ever infeasible (floors <= fc by construction)."""
    ctx = ctx or _mode_ctx(None, None)
    solver = pywraplp.Solver.CreateSolver("GLOP")
    if solver is None:
        solver = pywraplp.Solver.CreateSolver("CBC")
    a = {}
    for p in posts:
        for k in b.skus_at_post[p]:
            a[(p, k)] = solver.NumVar(0.0, b.deficit_units[(p, k)], f"a_{p}_{k}")
    for k in sorted({k for p in posts for k in b.skus_at_post[p]}):
        cap = b.depot_stock.get((depot, k))
        if cap is not None:
            solver.Add(solver.Sum(a[(p, k)] for p in posts
                                  if k in b.skus_at_post[p]) <= cap)
    all_pairs = sorted(a.keys())
    t1_pairs = [pk for pk in all_pairs if _tier(b, pk[1], ctx) == 1]

    def kg_expr(pairs):
        return solver.Sum(a[pk] * b.sku_weight_kg[pk[1]] for pk in pairs)

    obj = solver.Objective()
    if objective in ("full_coverage", "max_tempo"):
        for (p, k) in all_pairs:
            st = cfg.STATUS_PRIORITY.get(b.post_status.get(p, "ok"), 1.0)
            prio = cfg.TIER_PRIORITY.get(_tier(b, k, ctx), 1.0) * st
            obj.SetCoefficient(a[(p, k)], prio * b.sku_weight_kg[k])
        obj.SetMaximization()
    else:
        floor = ctx["coverage_floor_frac"].get(objective,
                cfg.COVERAGE_FLOOR_FRAC.get(objective, 0.95))
        solver.Add(kg_expr(all_pairs) >= floor * fc_ref["covered_kg"] - 1e-6)
        solver.Add(kg_expr(t1_pairs) >= 0.999 * fc_ref["tier1_kg"] - 1e-6)
        if objective == "min_cost":
            tkm, payload_t = _best_rupee_per_tonne_km()
            for (p, k) in all_pairs:
                c = (b.legs[p].distance_km * tkm / 1000.0
                     + cfg.VEHICLE_FIXED_DISPATCH_COST / (payload_t * 1000.0))
                obj.SetCoefficient(a[(p, k)], c * b.sku_weight_kg[k])
            obj.SetMinimization()
        else:  # min_exposure
            ew = ctx["exposure_weight"]
            for (p, k) in all_pairs:
                pa = b.legs[p].path_availability
                tw = cfg.TIER_PRIORITY.get(_tier(b, k, ctx), 1.0)
                obj.SetCoefficient(a[(p, k)],
                                   (tw * pa - ew * (1.0 - pa)) * b.sku_weight_kg[k])
            obj.SetMaximization()

    status = solver.Solve()
    if status != pywraplp.Solver.OPTIMAL and objective not in ("full_coverage", "max_tempo"):
        return allocate_depot(b, depot, posts, "full_coverage", ctx=ctx)
    out = {}
    for (p, k), var in a.items():
        v = var.solution_value()
        if v > 0.5:
            out[(p, k)] = float(round(v))
    # HARD Tier-1 guarantee: constrained plans restore Tier-1 to the fc reference
    # exactly (the 0.1% floor slack absorbs rounding only; never a Tier-1 cut).
    if objective not in ("full_coverage", "max_tempo") and fc_ref and "alloc" in fc_ref:
        for (p, k), q in fc_ref["alloc"].items():
            if _tier(b, k, ctx) == 1:
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
def _vehicle_rank_key(b: Bundle, objective: str):
    """Objective-aware vehicle ranking (#1: makes the risk objective bite on
    fleet selection).

    Tested alternative — risk-per-ton (p_deadline/payload) — and REJECTED it:
    it selects smaller reliable trucks, which adds routes, and in this world
    route exposure (1-pa) dominates vehicle hazard (~0.01), so E[disrupted
    legs] went UP 56.3 → 58.7. The honest physics: fewest-biggest-trucks is
    risk-optimal at the route level; vehicle reliability is the SECONDARY
    criterion choosing WHICH big trucks roll.

    So: min_risk/balanced rank payload-first with p_deadline tiebreak (consult
    VOR history); min_cost/min_time rank payload-first with ID tiebreak (a
    cost planner doesn't consult VOR history). Vehicle ID is always the final
    tiebreak — determinism."""
    if objective in ("min_risk", "balanced"):
        return lambda v: (-b.veh[v]["payload_tons"], b.veh[v]["p_deadline"], v)
    return lambda v: (-b.veh[v]["payload_tons"], v)


def _vehicles_for_cluster(b: Bundle, depot: str, alloc_kg: float,
                           objective: str = "min_cost") -> list:
    pool = b.vehicles_by_depot.get(depot, [])
    if not pool:
        return []
    ranked = sorted(pool, key=_vehicle_rank_key(b, objective))
    chosen, cap = [], 0.0
    for v in ranked:
        if cap >= alloc_kg and chosen:
            break
        chosen.append(v); cap += b.veh[v]["payload_tons"] * 1000.0
    for v in ranked[len(chosen):len(chosen) + cfg.VRP_VEHICLE_SLACK]:
        chosen.append(v)
    return sorted(chosen)


def _rank_vehicles(b: Bundle, pool: list, objective: str) -> list:
    """v3 objective-aware ordering used by route_cluster:
      full_coverage / max_tempo : largest payload first (fewest sorties)
      min_cost                  : cheapest ₹ per tonne-km first
      min_exposure              : max expected ARRIVED kg/sortie
                                  (payload × P(vehicle survives)) — pure
                                  reliability-first was tried and rejected (it
                                  inflated sortie count by adding small trucks)."""
    if objective == "min_exposure":
        key = lambda v: (-(b.veh[v]["payload_tons"] * (1.0 - b.veh[v]["p_deadline"])), v)
    elif objective == "min_cost":
        key = lambda v: (_rupee_per_tonne_km(b.veh[v]["vehicle_class"]),
                         -b.veh[v]["payload_tons"], v)
    else:  # full_coverage / max_tempo
        key = lambda v: (-b.veh[v]["payload_tons"], b.veh[v]["p_deadline"], v)
    return sorted(pool, key=key)


def route_cluster(b: Bundle, depot: str, axis: str, posts: list,
                  alloc: dict, objective: str, sorties_used: dict,
                  ctx: dict | None = None) -> dict:
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
    ctx = ctx or _mode_ctx(None, None)
    pool = b.vehicles_by_depot.get(depot, [])
    ranked = _rank_vehicles(b, pool, objective)
    if not ranked:
        return {"legs": [], "routes": [], "status": "infeasible", "solve_time_s": 0.0}
    # v3.1: a vehicle may run ONE SORTIE PER DISPATCH SLOT (Phase 2.5 forces a
    # vehicle's sorties onto distinct days). One round trip per 14-day window was
    # never realistic; one per slot is the conservative tempo end. The budget is
    # GLOBAL per vehicle across the depot's clusters via the sorties_used ledger.
    n_sorties = max(1, len(b.schedule_slots))
    expanded = []
    for _cycle in range(n_sorties):
        expanded.extend(ranked)
    ranked = [v for i, v in enumerate(expanded)
              if expanded[:i].count(v) + sorties_used.get(v, 0) < n_sorties]

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
            ruid = f"{depot}-{axis}-{len(routes_out)}"
            routes_out.append({"vehicle_id": v, "vehicle_class": vc, "depot_id": depot,
                               "axis": axis, "stops": [p], "route_km": round(rk, 1),
                               "_ruid": ruid})
            for k, q, wk in placed:
                legs_out.append({"vehicle_id": v, "vehicle_class": vc, "depot_id": depot,
                                 "axis": axis, "route_id": b.legs[p].route_id, "post_id": p,
                                 "sku_id": k, "qty": q, "weight_kg": wk, "stop_order": 1,
                                 "_ruid": ruid,
                                 "path_availability": round(b.legs[p].path_availability, 4)})
            sorties_used[v] = sorties_used.get(v, 0) + 1
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
        rv_seen, rv = set(), []
        for v in ranked[veh_ptr:]:
            if v not in rv_seen and sorties_used.get(v, 0) < n_sorties:
                rv_seen.add(v); rv.append(v)
            if len(rv) >= len(resid_posts) + cfg.VRP_VEHICLE_SLACK:
                break
        if rv:
            sub = _route_residual(b, depot, axis, resid_posts, resid_g, rv, objective, ctx)
            solve_t = sub["solve_time_s"]; status = sub["status"]
            vrp_ruid = {}
            for r in sub["routes"]:
                ruid = f"{depot}-{axis}-{len(routes_out)}"
                r["_ruid"] = ruid
                for p in r["stops"]:
                    vrp_ruid[(r["vehicle_id"], p)] = ruid
                sorties_used[r["vehicle_id"]] = sorties_used.get(r["vehicle_id"], 0) + 1
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
                                     "_ruid": vrp_ruid.get((v, p), ""),
                                     "path_availability": round(b.legs[p].path_availability, 4)})
    return {"legs": legs_out, "routes": routes_out, "status": status, "solve_time_s": solve_t}


def _route_residual(b: Bundle, depot: str, axis: str, posts: list, post_g: dict,
                    vehicles: list, objective: str, ctx: dict | None = None) -> dict:
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
                else:  # full_coverage / max_tempo / min_cost route on cost
                    pen = dist * cfg.VEHICLE_CLASS_FUEL_COST_PER_KM.get(vc, cfg.DEFAULT_FUEL_COST_PER_KM)
                if i == depot:
                    pen += cfg.VEHICLE_FIXED_DISPATCH_COST
                obj_terms.append(int(round(pen)) * arc[(v, i, j)])
    model.Minimize(sum(obj_terms))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = cfg.DATA_SNAPSHOT_SEED
    # DETERMINISM UNDER TIMEOUT: a single-worker CP-SAT that times out can still
    # return run-to-run-different incumbents unless its search is fully pinned.
    # Pin it: no interleaving, fixed-order portfolio, deterministic time. With
    # these, a "feasible" (non-proven-optimal) result is byte-identical across
    # runs — essential because these residual VRPs do hit the limit on the
    # larger clusters and we report their output as committed.
    solver.parameters.interleave_search = False
    solver.parameters.num_search_workers = 1
    tl = (ctx or {}).get("time_limit")
    solver.parameters.max_time_in_seconds = tl if tl else \
        cfg.SOLVER_TIME_LIMIT_BY_OBJECTIVE.get(objective, cfg.SOLVER_TIME_LIMIT_S)
    # bound determinism to deterministic time as well (wall-clock cutoffs are
    # what make timed-out incumbents vary)
    solver.parameters.max_deterministic_time = (tl if tl else
        cfg.SOLVER_TIME_LIMIT_BY_OBJECTIVE.get(objective, cfg.SOLVER_TIME_LIMIT_S)) * 1000.0
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
def _resolve_non_road(b: Bundle, road_shortfalls: list, objective: str,
                      forced: dict | None = None) -> dict:
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
    # v3.4: proactively diverted (post,sku) enter the SAME resolver even though
    # their road path is feasible — the exposure objective chose not to gamble
    # them on a marginal pass.
    if forced:
        for (pid, k), units in forced.items():
            if units > 1e-6:
                residual[(pid, k)] = residual.get((pid, k), 0.0) + units

    nr_legs = []
    mode_summary = {}
    platform_commitment = {}
    sortie_counter = 0  # for deterministic leg IDs

    # ── Phase 3: commit INDUCTED PLATFORMS first (drones, robotic mules) ──────
    # The Army wants its newly-procured hardware tasked to the hardest posts
    # before falling back to animal/manned columns. Each platform fills the
    # residual using its per-unit payload × fleet × turnarounds, tagged with the
    # airframe/section count committed — that count is the procurement-relevant
    # output. Legacy modes below then mop up what platforms cannot reach/carry.
    if getattr(cfg, "PREFER_INDUCTED_PLATFORMS", False) and hasattr(cfg, "INDUCTED_PLATFORMS"):
        for plat_name in sorted(cfg.INDUCTED_PLATFORMS,
                                key=lambda p: cfg.INDUCTED_PLATFORMS[p]["cost_per_kg"]):
            plat = cfg.INDUCTED_PLATFORMS[plat_name]
            base_mode = modes.get(plat["maps_to_mode"], {})
            eligibility = base_mode.get("eligible_posts", "all_non_depot")
            elig_heads = set(plat.get("eligible_heads", []))
            excl_heads = set(plat.get("excluded_heads", []))
            unit_payload = plat["payload_kg_per_unit"]
            per_unit_cap = unit_payload * plat["sorties_per_unit_per_day"] * weather_frac
            fleet_cap_kg = per_unit_cap * plat["fleet_units"]
            cost_per_kg = plat["cost_per_kg"]

            fleet_kg_left = fleet_cap_kg
            plat_kg = 0.0; plat_cost = 0.0; plat_posts = set()
            # prefer the hardest posts first: air-eligible / lowest path availability
            def _post_hardness(pid):
                leg = b.legs.get(pid)
                air = 1 if (leg and leg.has_air_resupply) else 0
                pa = leg.path_availability if leg else 1.0
                return (-air, pa, pid)   # air-DZ posts first, then most isolated
            cand_posts = sorted({pk[0] for pk in residual}, key=_post_hardness)
            for pid in cand_posts:
                if fleet_kg_left <= 0:
                    break
                leg = b.legs.get(pid)
                if eligibility == "air_resupply_only" and not (leg and leg.has_air_resupply):
                    continue
                cands = []
                for (p, k), units in sorted(residual.items()):
                    if p != pid or units <= 1e-6:
                        continue
                    head = b.sku_meta[k]["head"]
                    if excl_heads and head in excl_heads:
                        continue
                    if elig_heads and head not in elig_heads:
                        continue
                    cands.append((k, units, b.sku_meta[k]["tier"], b.sku_weight_kg[k]))
                cands.sort(key=lambda c: (c[2], -c[3]))
                post_kg = 0.0
                for k, units_avail, tier, wkg in cands:
                    if fleet_kg_left <= 0:
                        break
                    max_units = (fleet_kg_left / wkg) if wkg > 0 else units_avail
                    take = float(int(min(units_avail, max_units)))
                    if take <= 0:
                        continue
                    take_kg = take * wkg
                    nr_legs.append({
                        "post_id": pid, "sku_id": k, "qty": take,
                        "weight_kg": round(take_kg, 2),
                        "transport_mode": plat["maps_to_mode"],
                        "platform": plat_name,
                        "platform_name": plat["display_name"],
                        "cost_per_kg": cost_per_kg,
                        "expected_cost": round(take_kg * cost_per_kg, 2),
                        "depot_id": (leg.depot_id if leg else "?"),
                        "axis": b.post_axis.get(pid, "?"),
                        "head": b.sku_meta[k]["head"], "tier": tier,
                        "provenance": plat.get("provenance", "synthetic-inferred"),
                    })
                    residual[(pid, k)] -= take
                    fleet_kg_left -= take_kg
                    plat_kg += take_kg; plat_cost += take_kg * cost_per_kg
                    post_kg += take_kg; plat_posts.add(pid)
            if plat_kg > 0:
                # units committed = ceil(kg / per-unit daily capacity), capped at fleet
                units_committed = min(plat["fleet_units"],
                                      int(math.ceil(plat_kg / max(per_unit_cap, 1e-9))))
                platform_commitment[plat_name] = {
                    "display_name": plat["display_name"],
                    "units_committed": units_committed,
                    "fleet_units": plat["fleet_units"],
                    "tonnes": round(plat_kg / 1000.0, 2),
                    "cost": round(plat_cost, 2),
                    "cost_per_kg": cost_per_kg,
                    "posts_served": len(plat_posts),
                    "weather_capacity_fraction": round(weather_frac, 2),
                    "provenance": plat.get("provenance", "synthetic-inferred"),
                }

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
            "mode_summary": mode_summary,
            "platform_commitment": platform_commitment}


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2.5 — convoy dispatch scheduling (v3.1, time-expanded)
# ─────────────────────────────────────────────────────────────────────────────
def _schedule_convoys(b: Bundle, routes_out: list, route_kg: dict,
                      ctx: dict | None = None, objective: str = "") -> None:
    """Assign every convoy a departure day from the Stage 3 prediction slots
    (1/3/7/14 d), maximizing tonnage-weighted P(path open at dispatch). Exact
    CP-SAT assignment: one slot per convoy, a vehicle runs at most one convoy
    per slot. Replaces v2's day-14 scoring + 72h closure-delay fudge. Mutates
    routes in place: depart_day, pa_at_dispatch."""
    slots = b.schedule_slots
    if not routes_out:
        return
    if not slots:
        for r in routes_out:
            r["depart_day"] = 1
            r["pa_at_dispatch"] = min((b.legs[p].path_availability
                                       for p in r["stops"] if p in b.legs), default=1.0)
        return

    def pa_route_slot(r, si):
        return min((b.legs[p].pa_by_slot[si] for p in r["stops"] if p in b.legs),
                   default=1.0)

    model = cp_model.CpModel()
    x = {}
    for ci in range(len(routes_out)):
        for si in range(len(slots)):
            x[(ci, si)] = model.NewBoolVar(f"x_{ci}_{si}")
        model.AddExactlyOne(x[(ci, si)] for si in range(len(slots)))
    by_vehicle = defaultdict(list)
    for ci, r in enumerate(routes_out):
        by_vehicle[r["vehicle_id"]].append(ci)
    for v, cis in sorted(by_vehicle.items()):
        if len(cis) > 1:
            for si in range(len(slots)):
                model.AddAtMostOne(x[(ci, si)] for ci in cis)
    # earliness: strong pull for max_tempo, mild tiebreak otherwise
    ew = ((ctx or {}).get("earliness_weight", cfg.PEACETIME_EARLINESS_WEIGHT)
          if objective == "max_tempo" else cfg.PEACETIME_EARLINESS_WEIGHT)
    n_s = len(slots)
    model.Maximize(sum(
        int(round(route_kg.get(ci, 0.0) * 100.0 *
                  (pa_route_slot(routes_out[ci], si) + ew * (n_s - 1 - si) / max(n_s - 1, 1))))
        * x[(ci, si)]
        for ci in range(len(routes_out)) for si in range(len(slots))))
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = cfg.DATA_SNAPSHOT_SEED
    solver.parameters.max_time_in_seconds = 10.0
    st = solver.Solve(model)
    if st in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        for ci, r in enumerate(routes_out):
            si = next(s for s in range(len(slots)) if solver.Value(x[(ci, s)]) > 0)
            r["depart_day"] = slots[si]
            r["pa_at_dispatch"] = round(pa_route_slot(r, si), 4)
    else:
        counter = {}
        for r in sorted(routes_out, key=lambda r: r.get("_ruid", "")):
            k = r["vehicle_id"]; si = counter.get(k, 0) % len(slots)
            counter[k] = si + 1
            r["depart_day"] = slots[si]
            r["pa_at_dispatch"] = round(pa_route_slot(r, si), 4)


# ─────────────────────────────────────────────────────────────────────────────
# assembly + shortfalls
# ─────────────────────────────────────────────────────────────────────────────
def _shortfalls(b: Bundle, alloc_all: dict, delivered: dict,
                objective: str = "full_coverage", ctx: dict | None = None) -> list:
    rows = []
    _depot_need = defaultdict(float)
    for pid in b.posts:
        leg = b.legs[pid]
        if leg.feasible:
            for k in b.skus_at_post[pid]:
                _depot_need[(leg.depot_id, k)] += b.deficit_units[(pid, k)]
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
                allocated = alloc_all.get((pid, k), 0.0)
                depot_need = _depot_need.get((leg.depot_id, k), 0.0)
                if have is not None and have < depot_need - 1e-6:
                    cause = "depot_short"
                elif objective not in ("full_coverage", "max_tempo") and allocated < need - 0.5:
                    cause = "objective_tradeoff"   # the LP chose to leave this
                else:
                    cause = "capacity_short"       # truck-fill rounding crumb
            rows.append({"post_id": pid, "sku_id": k, "shortfall_units": round(unmet, 3),
                         "shortfall_kg": round(unmet * b.sku_weight_kg[k], 2),
                         "head": b.sku_meta[k]["head"], "tier": b.sku_meta[k]["tier"],
                         "cause": cause, "air_resupply_possible": bool(leg.has_air_resupply),
                         "path_availability": round(leg.path_availability, 4)})
    return sorted(rows, key=lambda r: (r["post_id"], r["sku_id"]))


def _assemble(b: Bundle, objective: str, cluster_out: dict, alloc_all: dict,
              ctx: dict | None = None, forced_nonroad: dict | None = None) -> dict:
    ctx = ctx or _mode_ctx(None, None)
    legs_out, routes_out = [], []
    for res in cluster_out.values():
        legs_out.extend(res["legs"]); routes_out.extend(res["routes"])
    delivered = defaultdict(float)
    for l in legs_out:
        delivered[(l["post_id"], l["sku_id"])] += l["qty"]

    # route mapping by UID — collision-proof under multi-sortie vehicles
    route_of = {r["_ruid"]: idx for idx, r in enumerate(routes_out)}
    route_kg = defaultdict(float)
    for l in legs_out:
        idx = route_of.get(l["_ruid"])
        if idx is not None:
            route_kg[idx] += l["weight_kg"]

    # v3.1 PHASE 2.5: assign each convoy its dispatch day, then score at the
    # availability of the day it actually rolls (no day-14 worst case, no fudge).
    _schedule_convoys(b, routes_out, route_kg, ctx, objective)

    total_cost = 0.0; makespan_h = 0.0; risky_sorties = 0; max_leg_risk = 0.0
    for r in routes_out:
        vc = r["vehicle_class"]; rk = r["route_km"]
        cost = leg_cost_km(vc, rk) + cfg.VEHICLE_FIXED_DISPATCH_COST
        spd = cfg.VEHICLE_CLASS_SPEED_KMPH.get(vc, cfg.DEFAULT_SPEED_KMPH)
        pa_d = r["pa_at_dispatch"]
        hours = (r["depart_day"] - 1) * 24.0 + rk / spd
        pdl = b.veh[r["vehicle_id"]]["p_deadline"]
        r["expected_cost"] = round(cost, 2); r["eta_hours"] = round(hours, 2)
        r["expected_risk"] = round(1.0 - pa_d * (1.0 - pdl), 6)
        total_cost += cost; makespan_h = max(makespan_h, hours)
        max_leg_risk = max(max_leg_risk, r["expected_risk"])
        if pa_d < cfg.RISKY_SORTIE_PAVAIL:
            risky_sorties += 1

    enriched = []
    for l in legs_out:
        idx = route_of.get(l.pop("_ruid", ""), None)
        r = routes_out[idx] if idx is not None else None
        rkg = route_kg.get(idx, 0.0) or 1.0
        enriched.append({**l,
                         "expected_cost": round((r["expected_cost"] if r else 0.0) * l["weight_kg"] / rkg, 2),
                         "eta_hours": r["eta_hours"] if r else 0.0,
                         "expected_risk": r["expected_risk"] if r else 0.0,
                         "depart_day": r["depart_day"] if r else 1,
                         "pa_at_dispatch": r["pa_at_dispatch"] if r else 0.0,
                         "route_km": r["route_km"] if r else 0.0})
    legs_out = sorted(enriched, key=lambda l: (l["depot_id"], l["axis"], l["vehicle_id"],
                                               l["post_id"], l["sku_id"]))

    expected_arrived_kg = sum(route_kg[i] * (1.0 - routes_out[i]["expected_risk"]) for i in route_kg)
    agg_risk = (1.0 - math.prod((1.0 - r["expected_risk"]) for r in routes_out)
                if routes_out else 0.0)
    edl = sum(r["expected_risk"] for r in routes_out)
    mlr = edl / len(routes_out) if routes_out else 0.0
    for r in routes_out:
        r.pop("_ruid", None)

    # Phase 3 (PRESERVED): resolve road-isolated shortfalls via non-road modes.
    road_shortfalls = _shortfalls(b, alloc_all, delivered, objective, ctx)
    nr = _resolve_non_road(b, road_shortfalls, objective, forced=forced_nonroad)
    nr_legs = nr["legs"]
    # v3.4: diverted (post,sku) had their road deficit zeroed; non-road resolves
    # some. Any diverted demand NOT lifted by non-road must reappear as shortfall
    # so the demand base stays honest (coverage denominators include it).
    if forced_nonroad:
        nr_by_pair = defaultdict(float)
        for l in nr_legs:
            nr_by_pair[(l["post_id"], l["sku_id"])] += l["qty"]
        existing = {(s["post_id"], s["sku_id"]) for s in nr["remaining_shortfalls"]}
        for (pid, k), units in forced_nonroad.items():
            unmet = units - nr_by_pair.get((pid, k), 0.0)
            if unmet > 0.5 and (pid, k) not in existing:
                nr["remaining_shortfalls"].append({
                    "post_id": pid, "sku_id": k, "shortfall_units": round(unmet, 3),
                    "shortfall_kg": round(unmet * b.sku_weight_kg[k], 2),
                    "head": b.sku_meta[k]["head"], "tier": b.sku_meta[k]["tier"],
                    "cause": "residual_after_nonroad",
                    "air_resupply_possible": bool(b.legs[pid].has_air_resupply),
                    "path_availability": round(b.legs[pid].path_availability, 4)})
        nr["remaining_shortfalls"] = sorted(nr["remaining_shortfalls"],
                                            key=lambda r: (r["post_id"], r["sku_id"]))
    nr_cost = sum(l["expected_cost"] for l in nr_legs)
    final_shortfalls = nr["remaining_shortfalls"]

    road_covered_kg = sum(l["weight_kg"] for l in legs_out)
    nr_covered_kg = nr["resolved_kg"]
    total_covered_kg = road_covered_kg + nr_covered_kg
    shortfall_kg = sum(s["shortfall_kg"] for s in final_shortfalls)
    demand_kg = total_covered_kg + shortfall_kg

    residual_isolated_kg = sum(s["shortfall_kg"] for s in final_shortfalls
                               if s["cause"] == "residual_after_nonroad")
    tradeoff_kg = sum(s["shortfall_kg"] for s in final_shortfalls
                      if s["cause"] == "objective_tradeoff")
    reachable = demand_kg - residual_isolated_kg
    unserved_reachable_kg = shortfall_kg - residual_isolated_kg
    expected_loss_kg = road_covered_kg - expected_arrived_kg

    status = "optimal" if cluster_out and all(r["status"] == "optimal" for r in cluster_out.values()) \
        else ("optimal" if not cluster_out else "feasible")
    return {"objective": objective, "status": status,
            "solve_time_s": round(sum(r["solve_time_s"] for r in cluster_out.values()), 3),
            "legs": legs_out, "routes": routes_out,
            "non_road_legs": nr_legs, "non_road_summary": nr["mode_summary"],
            "platform_commitment": nr.get("platform_commitment", {}),
            "shortfalls": final_shortfalls,
            "vehicles_used": len({l["vehicle_id"] for l in legs_out}),
            "posts_served": len({l["post_id"] for l in legs_out} | {l["post_id"] for l in nr_legs}),
            "posts_served_road": len({l["post_id"] for l in legs_out}),
            "posts_served_nonroad": len({l["post_id"] for l in nr_legs}),
            "convoys": len(routes_out),
            "total_cost": round(total_cost + nr_cost, 2),
            "road_cost": round(total_cost, 2), "non_road_cost": round(nr_cost, 2),
            "total_time_hours": round(makespan_h, 2),
            "aggregate_risk": round(agg_risk, 4),
            "expected_disrupted_legs": round(edl, 3),
            "mean_leg_risk": round(mlr, 4), "max_leg_risk": round(max_leg_risk, 4),
            "risky_sorties": risky_sorties,
            "expected_arrived_tonnes": round(expected_arrived_kg / 1000.0, 2),
            "expected_loss_tonnes": round(expected_loss_kg / 1000.0, 2),
            "unserved_reachable_tonnes": round(unserved_reachable_kg / 1000.0, 2),
            "objective_tradeoff_tonnes": round(tradeoff_kg / 1000.0, 2),
            "expected_shortfall_tonnes": round((expected_loss_kg + unserved_reachable_kg) / 1000.0, 2),
            "dispatch_days_used": sorted({r["depart_day"] for r in routes_out}),
            "mean_pa_at_dispatch": round(sum(r["pa_at_dispatch"] * route_kg[i]
                                             for i, r in enumerate(routes_out)) /
                                         max(sum(route_kg.values()), 1e-9), 4) if routes_out else 0.0,
            "covered_tonnes": round(total_covered_kg / 1000.0, 2),
            "road_covered_tonnes": round(road_covered_kg / 1000.0, 2),
            "non_road_covered_tonnes": round(nr_covered_kg / 1000.0, 2),
            "shortfall_tonnes": round(shortfall_kg / 1000.0, 2),
            "coverage_pct": round(100.0 * total_covered_kg / demand_kg if demand_kg > 1e-9 else 100.0, 1),
            "coverage_reachable_pct": round(100.0 * total_covered_kg / reachable if reachable > 1e-9 else 100.0, 1),
            "isolated_tonnes": round(residual_isolated_kg / 1000.0, 2)}


def solve_all(b: Bundle, mode_cfg: dict | None = None,
              time_limit: float | None = None) -> dict:
    ctx = _mode_ctx(mode_cfg, time_limit)
    # reference (full_coverage) allocation uses the full_coverage PATH choice
    bf = _select_paths(b, "full_coverage")
    fc_clusters = _build_clusters(bf)
    fc_depot_posts = defaultdict(list)
    for (depot, axis), posts in sorted(fc_clusters.items()):
        fc_depot_posts[depot].extend(posts)
    fc_depot_posts = {d: sorted(ps) for d, ps in fc_depot_posts.items()}
    fc_ref = {}
    for depot in sorted(fc_depot_posts):
        alloc = allocate_depot(bf, depot, fc_depot_posts[depot], "full_coverage", ctx=ctx)
        fc_ref[depot] = {**_alloc_totals(bf, alloc), "alloc": alloc}

    results = {}
    for obj in ctx["objectives"]:
        # v3.3: each objective routes on its OWN path selection
        bo = _select_paths(b, obj)
        # v3.4: proactively divert critical cargo off marginal road paths
        divert = _diversions(bo, obj, ctx)
        forced = {}
        if divert:
            import copy
            forced = {(p, k): bo.deficit_units[(p, k)] for (p, k) in divert
                      if (p, k) in bo.deficit_units}
            # road manifest excludes diverted pairs: zero their deficit in a view
            bo = copy.copy(bo)
            bo.deficit_units = {pk: (0.0 if pk in divert else q)
                                for pk, q in bo.deficit_units.items()}
        clusters = _build_clusters(bo)
        depot_posts = defaultdict(list)
        for (depot, axis), posts in sorted(clusters.items()):
            depot_posts[depot].extend(posts)
        depot_posts = {d: sorted(ps) for d, ps in depot_posts.items()}
        alloc_all = {}
        for depot in sorted(depot_posts):
            ref = fc_ref.get(depot)
            if obj in ("full_coverage", "max_tempo"):
                alloc = allocate_depot(bo, depot, depot_posts[depot], obj, ctx=ctx)
            else:
                alloc = allocate_depot(bo, depot, depot_posts[depot], obj, ref, ctx=ctx)
            alloc_all.update(alloc)
        cluster_out, sorties_used = {}, {}
        for (depot, axis), posts in sorted(clusters.items()):
            cluster_out[(depot, axis)] = route_cluster(bo, depot, axis, posts, alloc_all,
                                                       obj, sorties_used, ctx=ctx)
        results[obj] = _assemble(bo, obj, cluster_out, alloc_all, ctx=ctx, forced_nonroad=forced)
    return results


def solve_manifest(b: Bundle, items: dict, objective: str = "custom",
                   mode_cfg: dict | None = None, time_limit: float | None = None) -> dict:
    """v3.2: re-optimize routing + vehicles + dispatch schedule (+ Phase 3
    non-road) for a USER-FIXED manifest {(post,sku): units}. Phase 1 is skipped;
    user quantities are final except clamping to depot stock (jointly per depot,
    largest requests first by tier then kg) and road feasibility. Clamps itemised
    back in 'clamped_requests'."""
    ctx = _mode_ctx(mode_cfg, time_limit)
    clusters = _build_clusters(b)
    remaining_stock = dict(b.depot_stock)
    alloc_all = {}
    order = sorted(items.items(),
                   key=lambda kv: (_tier(b, kv[0][1], ctx),
                                   -kv[1] * b.sku_weight_kg.get(kv[0][1], 0.0), kv[0]))
    for (p, k), q in order:
        if p not in b.legs or not b.legs[p].feasible or q <= 0 or k not in b.sku_weight_kg:
            continue
        cap = remaining_stock.get((b.legs[p].depot_id, k))
        take = float(q) if cap is None else float(min(q, max(cap, 0)))
        if take <= 0:
            continue
        if cap is not None:
            remaining_stock[(b.legs[p].depot_id, k)] = cap - take
        alloc_all[(p, k)] = round(take)
    cluster_out, sorties_used = {}, {}
    for (depot, axis), posts in sorted(clusters.items()):
        cluster_out[(depot, axis)] = route_cluster(b, depot, axis, posts, alloc_all,
                                                   "min_cost", sorties_used, ctx=ctx)
    res = _assemble(b, "min_cost", cluster_out, alloc_all, ctx=ctx)
    res["objective"] = objective
    res["clamped_requests"] = sorted(
        [{"post_id": p, "sku_id": k, "requested": float(items[(p, k)]),
          "granted": alloc_all.get((p, k), 0.0)}
         for (p, k) in items if alloc_all.get((p, k), 0.0) < float(items[(p, k)]) - 1e-6],
        key=lambda r: (r["post_id"], r["sku_id"]))
    return res
