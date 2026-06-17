"""
Project Bastion — Stage 4 input assembly (v1.1, Advance Winter Stocking)

Reads ONE Stage 3 snapshot output dir + Stage 2 topology and assembles the typed
bundle the optimizer consumes. This is the "interrogate, don't describe" layer.

v1.1 deficit logic (the rebuild — see config.py header for the full WHY):
  A forward post that is going to be cut off for the winter must hold enough to
  consume through (days_to_closure + ISOLATION_DURATION + RESERVE) days of WORST-
  CASE (P90) demand. Deficit = that target − current_stock, clipped at 0.

  Gate (IF we stock anticipatorily): isolation_probability >= ISOLATION_GATE, OR a
  fired tier alert / bad worst-case status (a post already starving is in scope
  regardless of isolation).

  Horizon (how MUCH we stock): days_to_closure is derived per post from route
  predictions — a post about to be cut off tomorrow needs the full window now; one
  whose road holds longer needs less *additional* cover today.

  Shelf-life cap + substitution: each SKU's stocking window is capped at its
  shelf_life_days (read live from skus.parquet). Perishable demand beyond shelf
  life is routed into a longer-life substitute (SUBSTITUTION_MAP). Any residual the
  depot cannot supply is surfaced downstream as an explicit shortfall.

Contract (from stage3_models/predict_service.py): reads stockout_risk.parquet +
route_predictions.parquet + vehicle_reliability.parquet, plus Stage 2 topology.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd
import numpy as np
import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# Typed bundle
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Leg:
    post_id: str
    depot_id: str
    route_id: str
    distance_km: float
    passes: list
    path_availability: float        # v3.1: BEST availability across dispatch slots
    feasible: bool                  # v3.1: judged at the best slot, not day-14
    has_air_resupply: bool
    days_to_closure: int            # v1.1: how long the inbound path stays usable
    pa_by_slot: tuple = ()          # v3.1: P(path open) at each ROUTE_HORIZONS_DAYS
    pa_horizon: float = 0.0         # v3.1: the old single day-14 value, for reference
    candidates: tuple = ()          # v3.3: alternate PathOption legs (incl. primary)


@dataclass
class PathOption:
    """v3.3: one candidate road path to a post. The primary plus derived
    alternates compete inside the optimizer; min_exposure can pick the longer,
    safer route over the short, marginal-pass one."""
    kind: str                       # "primary" | "alt_depot" | "pass_variant"
    depot_id: str
    route_id: str
    distance_km: float
    passes: tuple
    pa_by_slot: tuple
    path_availability: float        # best across slots
    feasible: bool


@dataclass
class Bundle:
    snapshot_date: str
    planning_horizon: int
    posts: list
    skus_at_post: dict              # post_id -> sorted [sku_id] with deficit>0 (post-substitution)
    deficit_units: dict             # (post_id, sku_id) -> units to top up
    sku_weight_kg: dict
    sku_meta: dict                  # sku_id -> {head, tier, shelf_life_days}
    post_status: dict
    isolation_prob: dict
    post_window: dict               # post_id -> stocking window days used (days_to_closure+iso+reserve)
    legs: dict
    depot_stock: dict
    post_axis: dict                 # post_id -> axis (for VRP milk-run clustering)
    road_dist: dict                 # (from_id, to_id) -> road_km (post->post + depot->post)
    substitutions: list             # [{post_id, from_sku, to_sku, units_from, units_to, note}]
    vehicles: list
    vehicles_by_depot: dict
    veh: dict
    schedule_slots: list = field(default_factory=list)   # v3.1: dispatch days
    depot_axis_peers: dict = field(default_factory=dict) # v3.3: axis -> [depot ids]
    diagnostics: dict = field(default_factory=dict)


def _nearest_route_horizon(h: int) -> int:
    return min(cfg.ROUTE_HORIZONS_DAYS, key=lambda x: abs(x - h))


def _path_availability(passes: list, ppass_open: dict) -> float:
    """P(all passes on the leg open) under independence (conservative: product of
    P(open) under-estimates joint openness -> we plan earlier)."""
    if not passes:
        return 1.0
    p = 1.0
    for pn in passes:
        p *= float(ppass_open.get(pn, 0.5))
    return p


def _days_to_closure(passes: list, routes_pred: pd.DataFrame, snap_ts: pd.Timestamp) -> int:
    """Earliest route horizon at which the leg's path availability falls below
    DAYS_TO_CLOSURE_PAVAIL -> treated as 'shut for the season' from that horizon.
    If it never crosses inside the route horizon, default (road assumed to hold).

    NOTE: this is the SYNTHETIC-INFERRED bridge between Stage 3's 14d route horizon
    and the multi-month stocking horizon. Documented as such; a real seasonal
    closure-date model replaces it cleanly here."""
    if not passes:
        return cfg.DAYS_TO_CLOSURE_DEFAULT
    for h in cfg.ROUTE_HORIZONS_DAYS:                       # 1,3,7,14 ascending
        rp_h = routes_pred[(routes_pred["horizon"] == h) & (routes_pred["date"] == snap_ts)]
        if len(rp_h) == 0:
            continue
        ppass = dict(zip(rp_h["pass_name"], rp_h["p_open"]))
        pavail = _path_availability(passes, ppass)
        if pavail < cfg.DAYS_TO_CLOSURE_PAVAIL:
            return h
    return cfg.DAYS_TO_CLOSURE_DEFAULT


def _build_candidates(pid, primary_depot, primary_route_id, primary_dist, primary_passes,
                      ppass_by_slot, slots, ppass_open, posts_df, axis,
                      depot_axis_peers, road_dist):
    """v3.3: derive up to ALT_PATHS_MAX road PathOptions for a post. Primary
    first, then alternate-depot (same axis), then pass-variant. Deterministic."""
    def pa_for(passes):
        sl = tuple(_path_availability(list(passes), ppass_by_slot[h]) for h in slots)
        best = max(sl) if sl else _path_availability(list(passes), ppass_open)
        return sl, best

    sl0, best0 = pa_for(primary_passes)
    opts = [PathOption("primary", primary_depot, primary_route_id, round(primary_dist, 1),
                       tuple(primary_passes), sl0, best0, best0 >= cfg.PATH_FEASIBILITY_MIN)]

    # ALTERNATE DEPOT: another depot on the same axis (sorted, excluding primary).
    peers = [d for d in depot_axis_peers.get(axis, []) if d != primary_depot]
    for alt_depot in sorted(peers):
        adep = posts_df[posts_df["id"] == alt_depot]
        if not len(adep):
            continue
        # pass-chain via the alternate depot = union of its served_by and the
        # post's own beyond-depot passes (the alt depot still sits behind the
        # axis chokepoints, but may bypass one forward pass).
        alt_passes = sorted(set(adep.iloc[0]["served_by"]))
        # distance: prefer committed road graph if present, else detour heuristic
        d = road_dist.get((alt_depot, pid))
        alt_dist = float(d) if d is not None else primary_dist * cfg.ALT_PATH_DETOUR_RATIO
        sl, best = pa_for(alt_passes)
        if best >= best0 + cfg.ALT_PATH_MIN_PA_GAIN or alt_dist < primary_dist:
            opts.append(PathOption("alt_depot", alt_depot,
                                   f"{primary_route_id}-ALT-{alt_depot}", round(alt_dist, 1),
                                   tuple(alt_passes), sl, best,
                                   best >= cfg.PATH_FEASIBILITY_MIN))
        if len(opts) >= cfg.ALT_PATHS_MAX:
            return tuple(opts[:cfg.ALT_PATHS_MAX])

    # PASS-VARIANT: drop the post's MOST MARGINAL pass (lowest current P(open))
    # and route the rest longer — models a detour that swaps a near-shut pass.
    if len(primary_passes) >= 2:
        marg = min(primary_passes, key=lambda pn: ppass_open.get(pn, 0.5))
        var_passes = tuple(p for p in primary_passes if p != marg)
        sl, best = pa_for(var_passes)
        if best >= best0 + cfg.ALT_PATH_MIN_PA_GAIN:
            opts.append(PathOption("pass_variant", primary_depot,
                                   f"{primary_route_id}-VAR", round(primary_dist * cfg.ALT_PASS_VARIANT_DETOUR, 1),
                                   var_passes, sl, best, best >= cfg.PATH_FEASIBILITY_MIN))
    return tuple(opts[:cfg.ALT_PATHS_MAX])


def load_bundle(snapshot_dir: str | Path,
                planning_horizon: int | None = None) -> Bundle:
    snapshot_dir = Path(snapshot_dir)
    H = planning_horizon or cfg.PLANNING_HORIZON_DAYS

    # ── Stage 3 prediction outputs ───────────────────────────────────────────
    risk = pd.read_parquet(snapshot_dir / "stockout_risk.parquet")
    routes_pred = pd.read_parquet(snapshot_dir / "route_predictions.parquet")
    veh_rel = pd.read_parquet(snapshot_dir / "vehicle_reliability.parquet")
    snap_date = str(pd.to_datetime(risk["snapshot_date"]).max().date())

    # ── Stage 2 topology ─────────────────────────────────────────────────────
    posts = pd.read_parquet(cfg.DATA_DIR / "posts.parquet")
    routes = pd.read_parquet(cfg.DATA_DIR / "routes.parquet")
    vehicles = pd.read_parquet(cfg.DATA_DIR / "vehicles.parquet")
    skus = pd.read_parquet(cfg.DATA_DIR / "skus.parquet")

    # post->post + depot->post road matrix for VRP milk-runs (Stage 2 road_network).
    # Falls back to empty if absent (optimizer then uses leg distances per arc).
    road_dist: dict = {}
    pd_path = cfg.DATA_DIR / "post_distances.parquet"
    if pd_path.exists():
        pdist = pd.read_parquet(pd_path)
        road_dist = {(r.from_id, r.to_id): float(r.road_km) for r in pdist.itertuples()}

    # sku_meta now carries shelf_life_days (read live, never hardcoded).
    sku_meta = {r.sku: {"head": r.head, "tier": int(r.tier),
                        "shelf_life_days": int(r.shelf_life_days)}
                for r in skus.itertuples()}
    sku_weight = {s: cfg.SKU_WEIGHT_KG.get(
                      s, cfg.HEAD_WEIGHT_FALLBACK_KG.get(sku_meta[s]["head"], 1.0))
                  for s in sku_meta}

    serving_depot = dict(zip(posts["id"], posts["serving_depot_id"]))
    # v3.3: which depots serve each axis (for alternate-depot candidates)
    depot_axis_peers: dict = {}
    _dep_df = posts[posts["is_depot"]]
    for _, _dp in _dep_df.iterrows():
        depot_axis_peers.setdefault(str(_dp["axis"]), []).append(str(_dp["id"]))
    # also let any depot on the post's axis be a peer (forward axes share depots)
    for _, _p in posts[~posts["is_depot"]].iterrows():
        ax = str(_p["axis"])
        depot_axis_peers.setdefault(ax, [])
    # union depots that actually serve posts on each axis
    for _, _p in posts[~posts["is_depot"]].iterrows():
        ax = str(_p["axis"]); d = str(_p["serving_depot_id"])
        if d not in depot_axis_peers[ax]:
            depot_axis_peers[ax].append(d)
    has_air = dict(zip(posts["id"], posts["has_air_resupply"]))
    depot_ids = set(posts.loc[posts["is_depot"], "id"])

    # ── Risk rows at the rate horizon ────────────────────────────────────────
    if H not in set(risk["horizon_days"].unique()):
        H = int(min(risk["horizon_days"].unique(), key=lambda x: abs(x - H)))
    rh = risk[risk["horizon_days"] == H].copy()
    rh["daily_p90"] = rh["p90"] / 7.0   # Stage 3 p90 is a weekly total

    # ── Route predictions at snapshot ────────────────────────────────────────
    routes_pred = routes_pred.copy()
    routes_pred["date"] = pd.to_datetime(routes_pred["date"])
    snap_ts = pd.to_datetime(snap_date)
    # if snapshot date absent, snap to latest <= snapshot
    if (routes_pred["date"] == snap_ts).sum() == 0:
        snap_ts = routes_pred[routes_pred["date"] <= snap_ts]["date"].max()
    rh_route = _nearest_route_horizon(H)
    rp_at = routes_pred[(routes_pred["horizon"] == rh_route) & (routes_pred["date"] == snap_ts)]
    ppass_open = dict(zip(rp_at["pass_name"], rp_at["p_open"]))
    # v3.1: per-slot pass availability — one map per Stage 3 route horizon
    # (1/3/7/14 d). Real model outputs only; no interpolation between slots.
    ppass_by_slot = {}
    for _h in cfg.ROUTE_HORIZONS_DAYS:
        _rp_h = routes_pred[(routes_pred["horizon"] == _h) & (routes_pred["date"] == snap_ts)]
        if len(_rp_h):
            ppass_by_slot[_h] = dict(zip(_rp_h["pass_name"], _rp_h["p_open"]))
    slots = sorted(ppass_by_slot)

    # ── Scope: which posts enter stocking ────────────────────────────────────
    # gate = isolation gate OR fired alert OR bad worst-case status. depot band excluded.
    iso_by_post = rh.groupby("post_id")["isolation_probability"].first()
    gated_posts = set(iso_by_post[iso_by_post >= cfg.ISOLATION_GATE].index)
    bad = rh["tier_alert_fired"] | rh["predicted_status_worstcase"].isin(cfg.ACTIONABLE_WORSTCASE_STATUSES)
    alert_posts = set(rh.loc[bad & ~rh["band"].eq("depot"), "post_id"])
    in_scope = sorted((gated_posts | alert_posts) - depot_ids)

    # ── Resolve each in-scope post -> depot + inbound leg + days_to_closure ──
    legs: dict[str, Leg] = {}
    post_axis: dict[str, str] = {}
    for pid in in_scope:
        inbound = routes[routes["destination_id"] == pid]
        if len(inbound) == 0:
            continue
        dep = serving_depot.get(pid)
        pick = inbound[inbound["origin_id"] == dep]
        rrow = (pick.iloc[0] if len(pick) else inbound.iloc[0])
        passes = list(rrow["passes_crossed"]) if rrow["passes_crossed"] is not None else []
        pa_h = _path_availability(passes, ppass_open)
        pa_slots = tuple(_path_availability(passes, ppass_by_slot[h]) for h in slots)
        # v3.1: a post is reachable if ANY dispatch slot works — convoys roll on
        # the best day, not day 14. The old day-14 gate wrote off posts whose
        # pass is open early in the window.
        pa_best = max(pa_slots) if pa_slots else pa_h
        d2c = _days_to_closure(passes, routes_pred, snap_ts)
        post_axis[pid] = str(rrow["axis"]) if "axis" in rrow else "?"
        cands = _build_candidates(
            pid, str(rrow["origin_id"]), str(rrow["route_id"]), float(rrow["distance_km"]),
            passes, ppass_by_slot, slots, ppass_open, posts, post_axis[pid],
            depot_axis_peers, road_dist)
        legs[pid] = Leg(
            post_id=pid, depot_id=str(rrow["origin_id"]), route_id=str(rrow["route_id"]),
            distance_km=float(rrow["distance_km"]), passes=passes,
            path_availability=pa_best, feasible=pa_best >= cfg.PATH_FEASIBILITY_MIN,
            has_air_resupply=bool(has_air.get(pid, False)), days_to_closure=d2c,
            pa_by_slot=pa_slots, pa_horizon=pa_h, candidates=cands,
        )
    no_road = [p for p in in_scope if p not in legs]
    in_scope = [p for p in in_scope if p in legs]

    # ── AWS deficits, shelf-life cap, substitution ───────────────────────────
    skus_at_post: dict[str, list] = {}
    deficit_units: dict[tuple, float] = {}
    post_status: dict[str, str] = {}
    isolation_prob: dict[str, float] = {}
    post_window: dict[str, int] = {}
    substitutions: list = []
    sev_rank = {"ok": 0, "rationing": 1, "stockout": 2}

    for pid in in_scope:
        d2c = legs[pid].days_to_closure
        base_window = d2c + cfg.ISOLATION_DURATION_DAYS + cfg.RESERVE_DAYS
        post_window[pid] = base_window
        sub_rows = rh[rh["post_id"] == pid]

        # accumulate per-SKU deficit (post-cap), plus substitution routing
        pid_deficits: dict[str, float] = {}
        for r in sub_rows.itertuples():
            sku = r.sku
            shelf = sku_meta[sku]["shelf_life_days"]
            # window for THIS sku is capped at its shelf life
            eff_window = min(base_window, shelf) if cfg.PERISHABLE_SHELF_CAP_ENABLED else base_window
            target = r.daily_p90 * eff_window
            deficit = max(target - float(r.current_stock), 0.0)

            # substitution: demand beyond shelf life for a perishable -> substitute sku
            if cfg.PERISHABLE_SHELF_CAP_ENABLED and sku in cfg.SUBSTITUTION_MAP and base_window > shelf:
                full_target = r.daily_p90 * base_window
                # units of original we could NOT stock because of shelf life
                unmet_perishable = max(full_target - target, 0.0)
                spec = cfg.SUBSTITUTION_MAP[sku]
                to_sku = spec["substitute"]; ratio = float(spec["ratio"])
                sub_units = unmet_perishable * ratio
                if sub_units > 1e-6:
                    pid_deficits[to_sku] = pid_deficits.get(to_sku, 0.0) + sub_units
                    substitutions.append({
                        "post_id": pid, "from_sku": sku, "to_sku": to_sku,
                        "units_from": round(unmet_perishable, 3),
                        "units_to": round(sub_units, 3), "note": spec["note"],
                    })
            if deficit > 1e-6:
                pid_deficits[sku] = pid_deficits.get(sku, 0.0) + deficit

        if not pid_deficits:
            continue
        skus_at_post[pid] = sorted(pid_deficits.keys())
        for sku, dv in pid_deficits.items():
            deficit_units[(pid, sku)] = dv
        prow = rh[rh["post_id"] == pid]
        post_status[pid] = max(prow["predicted_status_worstcase"], key=lambda s: sev_rank.get(s, 0))
        isolation_prob[pid] = float(prow["isolation_probability"].iloc[0])

    in_scope = [p for p in in_scope if p in skus_at_post]

    # ── Depot stock available as supply ──────────────────────────────────────
    depot_rows = risk[(risk["horizon_days"] == H) & (risk["post_id"].isin(depot_ids))]
    depot_stock = {(r.post_id, r.sku): float(r.current_stock) for r in depot_rows.itertuples()}

    # ── Eligible fleet ───────────────────────────────────────────────────────
    used_depots = sorted({legs[p].depot_id for p in in_scope})
    pdl = veh_rel[veh_rel["horizon_days"] == cfg.VEHICLE_HORIZON_DAYS] if "horizon_days" in veh_rel else veh_rel
    pdl_map = dict(zip(pdl["vehicle_id"], pdl["p_deadline"]))
    veh_list = []
    for r in vehicles[vehicles["home_depot_id"].isin(used_depots)].itertuples():
        veh_list.append({
            "vehicle_id": r.vehicle_id, "vehicle_class": r.vehicle_class,
            "depot_id": str(r.home_depot_id), "payload_tons": float(r.payload_tons),
            "p_deadline": float(pdl_map.get(r.vehicle_id, 0.0)),
        })
    veh_list.sort(key=lambda v: v["vehicle_id"])
    veh = {v["vehicle_id"]: v for v in veh_list}
    vehicles_by_depot: dict[str, list] = {}
    for v in veh_list:
        vehicles_by_depot.setdefault(v["depot_id"], []).append(v["vehicle_id"])

    # ── Diagnostics ──────────────────────────────────────────────────────────
    deficit_by_head: dict[str, float] = {}
    for (p, s), q in deficit_units.items():
        h_ = sku_meta[s]["head"]
        deficit_by_head[h_] = deficit_by_head.get(h_, 0.0) + q * sku_weight[s]
    diagnostics = {
        "snapshot_date": snap_date, "rate_horizon_days": H, "route_horizon_used": rh_route,
        "isolation_gate": cfg.ISOLATION_GATE,
        "isolation_duration_days": cfg.ISOLATION_DURATION_DAYS, "reserve_days": cfg.RESERVE_DAYS,
        "n_in_scope_posts": len(in_scope),
        "n_gated_by_isolation": len(gated_posts - depot_ids),
        "n_in_scope_by_alert_only": len((alert_posts - gated_posts) & set(in_scope)),
        "n_no_road_posts": len(no_road), "no_road_posts": no_road,
        "n_isolated_legs": sum(1 for p in in_scope if not legs[p].feasible),
        "isolated_legs": [{"post_id": p, "path_availability": round(legs[p].path_availability, 4),
                           "has_air_resupply": legs[p].has_air_resupply}
                          for p in in_scope if not legs[p].feasible],
        "days_to_closure_by_post": {p: legs[p].days_to_closure for p in in_scope},
        "stocking_window_by_post": {p: post_window[p] for p in in_scope},
        "n_deficit_pairs": len(deficit_units),
        "n_substitutions": len(substitutions),
        "substituted_tonnes": round(sum(
            s["units_to"] * sku_weight.get(s["to_sku"], 1.0) for s in substitutions) / 1000.0, 2),
        "deficit_tonnes_by_head": {k: round(v / 1000.0, 2) for k, v in sorted(deficit_by_head.items())},
        "total_deficit_tonnes": round(sum(
            deficit_units[(p, s)] * sku_weight[s]
            for p in in_scope for s in skus_at_post[p]) / 1000.0, 2),
        "eligible_vehicles": len(veh_list),
        "depots_in_play": used_depots,
        "passes_path_open_prob": {k: round(v, 4) for k, v in sorted(ppass_open.items())},
    }

    return Bundle(
        snapshot_date=snap_date, planning_horizon=H, posts=in_scope,
        skus_at_post=skus_at_post, deficit_units=deficit_units,
        sku_weight_kg=sku_weight, sku_meta=sku_meta, post_status=post_status,
        isolation_prob=isolation_prob, post_window=post_window, legs=legs,
        depot_stock=depot_stock, post_axis=post_axis, road_dist=road_dist,
        substitutions=substitutions,
        vehicles=veh_list, vehicles_by_depot=vehicles_by_depot, veh=veh,
        schedule_slots=slots, depot_axis_peers=depot_axis_peers,
        diagnostics=diagnostics,
    )
