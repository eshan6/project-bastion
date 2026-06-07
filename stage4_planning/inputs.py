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
    path_availability: float
    feasible: bool
    has_air_resupply: bool
    days_to_closure: int            # v1.1: how long the inbound path stays usable


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
        pavail = _path_availability(passes, ppass_open)
        d2c = _days_to_closure(passes, routes_pred, snap_ts)
        post_axis[pid] = str(rrow["axis"]) if "axis" in rrow else "?"
        legs[pid] = Leg(
            post_id=pid, depot_id=str(rrow["origin_id"]), route_id=str(rrow["route_id"]),
            distance_km=float(rrow["distance_km"]), passes=passes,
            path_availability=pavail, feasible=pavail >= cfg.PATH_FEASIBILITY_MIN,
            has_air_resupply=bool(has_air.get(pid, False)), days_to_closure=d2c,
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
        diagnostics=diagnostics,
    )
