"""
Project Bastion — Stage 4 input assembly (v1.0)

Reads ONE Stage 3 snapshot output dir + Stage 2 topology and assembles the
typed bundle the optimizer consumes. This is the "interrogate, don't describe"
layer: it resolves each at-risk post to a source depot + inbound route + path
availability, computes worst-case (P90) deficits, scopes the eligible fleet, and
caps supply by real depot inventory. Everything downstream is pure optimization.

Contract (from stage3_models/predict_service.py):
  Stage 4 reads stockout_risk.parquet + route_predictions.parquet +
  vehicle_reliability.parquet. Plus Stage 2 posts/routes/vehicles/skus for
  topology and weights. Nothing else.
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
    """A candidate depot->post road leg (one per at-risk post)."""
    post_id: str
    depot_id: str
    route_id: str
    distance_km: float
    passes: list
    path_availability: float       # P(all passes on the leg open) at planning horizon
    feasible: bool                 # path_availability >= PATH_FEASIBILITY_MIN
    has_air_resupply: bool


@dataclass
class Bundle:
    snapshot_date: str
    planning_horizon: int
    posts: list                    # at-risk post_ids (sorted)
    skus_at_post: dict             # post_id -> sorted [sku_id] with deficit>0
    deficit_units: dict            # (post_id, sku_id) -> units to top up (P90)
    sku_weight_kg: dict            # sku_id -> kg/unit
    sku_meta: dict                 # sku_id -> {head, tier}
    post_status: dict              # post_id -> worst predicted_status_worstcase among its skus
    isolation_prob: dict           # post_id -> isolation_probability at planning horizon
    legs: dict                     # post_id -> Leg
    depot_stock: dict              # (depot_id, sku_id) -> available units
    vehicles: list                 # [{vehicle_id, vehicle_class, depot_id, payload_tons, p_deadline}]
    vehicles_by_depot: dict        # depot_id -> sorted [vehicle_id]
    veh: dict                      # vehicle_id -> the vehicle dict
    diagnostics: dict = field(default_factory=dict)


def _nearest_route_horizon(h: int) -> int:
    return min(cfg.ROUTE_HORIZONS_DAYS, key=lambda x: abs(x - h))


def _path_availability(passes: list, ppass_open: dict) -> float:
    """P(all passes on the leg open) under independence (same conservative
    assumption Stage 3's isolation_probability uses, opposite direction here:
    product of P(open) UNDER-estimates joint openness, i.e. we are pessimistic
    about reachability -> we plan earlier. Documented."""
    if not passes:
        return 1.0
    p = 1.0
    for pn in passes:
        p *= float(ppass_open.get(pn, 0.5))   # unknown pass -> coin flip
    return p


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

    sku_meta = {r.sku: {"head": r.head, "tier": int(r.tier)} for r in skus.itertuples()}
    sku_weight = {s: cfg.SKU_WEIGHT_KG.get(
                      s, cfg.HEAD_WEIGHT_FALLBACK_KG.get(sku_meta[s]["head"], 1.0))
                  for s in sku_meta}

    serving_depot = dict(zip(posts["id"], posts["serving_depot_id"]))
    has_air = dict(zip(posts["id"], posts["has_air_resupply"]))
    depot_ids = set(posts.loc[posts["is_depot"], "id"])

    # ── Risk rows at the planning horizon ────────────────────────────────────
    # Stage 3 produces horizons [7,14,30,90]; pick the one matching H (default 14).
    if H not in set(risk["horizon_days"].unique()):
        H = int(min(risk["horizon_days"].unique(), key=lambda x: abs(x - H)))
    rh = risk[risk["horizon_days"] == H].copy()

    # Daily P90 rate (weekly forecast / 7), worst-case target cover & deficit.
    rh["daily_p90"] = rh["p90"] / 7.0
    rh["target_units"] = rh["daily_p90"] * (H + cfg.RESERVE_DAYS)
    rh["deficit_units"] = (rh["target_units"] - rh["current_stock"]).clip(lower=0.0)

    # At-risk posts: any sku fired a tier alert OR worst-case status is bad.
    bad = rh["tier_alert_fired"] | rh["predicted_status_worstcase"].isin(cfg.ACTIONABLE_WORSTCASE_STATUSES)
    at_risk_posts = sorted(set(rh.loc[bad & ~rh["band"].eq("depot"), "post_id"]))

    # ── Route path availability at the planning horizon ──────────────────────
    routes_pred = routes_pred.copy()
    routes_pred["date"] = pd.to_datetime(routes_pred["date"])
    rh_route = _nearest_route_horizon(H)
    snap_ts = pd.to_datetime(snap_date)
    rp = routes_pred[routes_pred["horizon"] == rh_route]
    rp_at = rp[rp["date"] == snap_ts]
    if len(rp_at) == 0:  # fall back to latest <= snapshot
        latest = rp[rp["date"] <= snap_ts]["date"].max()
        rp_at = rp[rp["date"] == latest]
    ppass_open = dict(zip(rp_at["pass_name"], rp_at["p_open"]))

    # ── Resolve each at-risk post -> source depot + inbound route + leg ──────
    # Prefer the inbound route whose origin == serving_depot; else any inbound
    # route (and treat that route's origin as the source depot). 30/30 posts in
    # the seed-42 world have a direct inbound route (verified).
    legs: dict[str, Leg] = {}
    for pid in at_risk_posts:
        inbound = routes[routes["destination_id"] == pid]
        if len(inbound) == 0:
            continue  # no road route at all -> handled as full shortfall later
        dep = serving_depot.get(pid)
        pick = inbound[inbound["origin_id"] == dep]
        rrow = (pick.iloc[0] if len(pick) else inbound.iloc[0])
        passes = list(rrow["passes_crossed"]) if rrow["passes_crossed"] is not None else []
        pavail = _path_availability(passes, ppass_open)
        legs[pid] = Leg(
            post_id=pid, depot_id=str(rrow["origin_id"]), route_id=str(rrow["route_id"]),
            distance_km=float(rrow["distance_km"]), passes=passes,
            path_availability=pavail, feasible=pavail >= cfg.PATH_FEASIBILITY_MIN,
            has_air_resupply=bool(has_air.get(pid, False)),
        )

    # Keep only posts we resolved a leg for (others are recorded as no-road posts)
    no_road = [p for p in at_risk_posts if p not in legs]
    at_risk_posts = [p for p in at_risk_posts if p in legs]

    # ── Deficits + per-post sku lists + status/isolation ─────────────────────
    skus_at_post: dict[str, list] = {}
    deficit_units: dict[tuple, float] = {}
    post_status: dict[str, str] = {}
    isolation_prob: dict[str, float] = {}
    sev_rank = {"ok": 0, "rationing": 1, "stockout": 2}
    for pid in at_risk_posts:
        sub = rh[(rh["post_id"] == pid) & (rh["deficit_units"] > 1e-6)]
        sk = sorted(sub["sku"].tolist())
        if not sk:
            continue
        skus_at_post[pid] = sk
        for r in sub.itertuples():
            deficit_units[(pid, r.sku)] = float(r.deficit_units)
        prow = rh[rh["post_id"] == pid]
        post_status[pid] = max(prow["predicted_status_worstcase"], key=lambda s: sev_rank.get(s, 0))
        isolation_prob[pid] = float(prow["isolation_probability"].iloc[0])

    at_risk_posts = [p for p in at_risk_posts if p in skus_at_post]

    # ── Depot stock available as supply (depot-band current_stock) ───────────
    depot_rows = risk[(risk["horizon_days"] == H) & (risk["post_id"].isin(depot_ids))]
    depot_stock = {(r.post_id, r.sku): float(r.current_stock) for r in depot_rows.itertuples()}

    # ── Eligible fleet (one mission per vehicle; scoped to source depots used) ─
    used_depots = sorted({legs[p].depot_id for p in at_risk_posts})
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

    diagnostics = {
        "snapshot_date": snap_date, "planning_horizon_days": H, "route_horizon_used": rh_route,
        "n_at_risk_posts": len(at_risk_posts),
        "n_no_road_posts": len(no_road), "no_road_posts": no_road,
        "n_isolated_legs": sum(1 for p in at_risk_posts if not legs[p].feasible),
        "isolated_legs": [{"post_id": p, "path_availability": round(legs[p].path_availability, 4),
                           "has_air_resupply": legs[p].has_air_resupply}
                          for p in at_risk_posts if not legs[p].feasible],
        "n_deficit_pairs": len(deficit_units),
        "total_deficit_tonnes": round(sum(
            deficit_units[(p, s)] * sku_weight[s]
            for p in at_risk_posts for s in skus_at_post[p]) / 1000.0, 2),
        "eligible_vehicles": len(veh_list),
        "depots_in_play": used_depots,
        "passes_path_open_prob": {k: round(v, 4) for k, v in sorted(ppass_open.items())},
    }

    return Bundle(
        snapshot_date=snap_date, planning_horizon=H, posts=at_risk_posts,
        skus_at_post=skus_at_post, deficit_units=deficit_units,
        sku_weight_kg=sku_weight, sku_meta=sku_meta, post_status=post_status,
        isolation_prob=isolation_prob, legs=legs, depot_stock=depot_stock,
        vehicles=veh_list, vehicles_by_depot=vehicles_by_depot, veh=veh,
        diagnostics=diagnostics,
    )
