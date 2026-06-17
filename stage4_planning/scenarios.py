"""
Project Bastion — Stage 4 scenario engine (what-if wargaming, v3.2)

Applies commander-editable world modifications to an input Bundle and runs the
frontier planner (or a custom user manifest) against the modified world.
Every knob below is a request parameter — nothing is hard-coded doctrine:

  pass_closures       {pass_name: factor 0.0–1.0}  multiply P(open) of every
                      dispatch slot on every leg crossing that pass.
                      0.0 = demolished / interdicted; 0.5 = half availability.
  demand_multiplier   float, or {post_id: float}. Force accretion: doubling a
                      post's strength ≈ 2.0 (Galwan-2020-style build-up).
  depot_stock_factor  {depot_id: factor}. 0.0 = depot destroyed / captured.
  vehicle_loss_pct    0–100: fraction of each depot's fleet unavailable
                      (battle damage / tasked elsewhere). Deterministic cull:
                      oldest (highest p_deadline) vehicles first.
  mode                "peacetime" | "wartime". Wartime applies config.WARTIME:
                      ammunition treated as Tier-1, exposure tolerance up,
                      max_tempo plan replaces min_cost, strong earliness in
                      its dispatch schedule. All overridable via mode_overrides.

The engine deep-copies nothing it doesn't touch and mutates only the copy —
the baseline Bundle stays valid for diffing. Deterministic by construction.
"""
from __future__ import annotations
import copy
from dataclasses import replace as dc_replace
import config as cfg
import optimizer
from inputs import Bundle, load_bundle


def apply_scenario(b: Bundle, scenario: dict | None) -> Bundle:
    sc = scenario or {}
    nb = copy.copy(b)                      # shallow; replace touched members below

    # ── pass closures → per-slot availability, refreshed feasibility ──────
    closures = {k: max(0.0, min(1.0, float(v)))
                for k, v in (sc.get("pass_closures") or {}).items()}
    if closures:
        legs = {}
        for pid, leg in b.legs.items():
            f = 1.0
            for pn in leg.passes:
                if pn in closures:
                    f *= closures[pn]
            if f >= 1.0:
                legs[pid] = leg
                continue
            pa_slots = tuple(p * f for p in leg.pa_by_slot)
            pa_best = max(pa_slots) if pa_slots else leg.path_availability * f
            legs[pid] = dc_replace(leg, pa_by_slot=pa_slots,
                                   path_availability=pa_best,
                                   pa_horizon=leg.pa_horizon * f,
                                   feasible=pa_best >= cfg.PATH_FEASIBILITY_MIN)
        nb.legs = legs

    # ── demand surge ───────────────────────────────────────────────────────
    dm = sc.get("demand_multiplier")
    if dm:
        if isinstance(dm, dict):
            mult = {p: max(0.0, float(f)) for p, f in dm.items()}
            get = lambda p: mult.get(p, 1.0)
        else:
            g = max(0.0, float(dm)); get = lambda p: g
        nb.deficit_units = {pk: round(q * get(pk[0]))
                            for pk, q in b.deficit_units.items()}

    # ── depot stock knockout / drawdown ────────────────────────────────────
    ds = sc.get("depot_stock_factor") or {}
    if ds:
        nb.depot_stock = {dk: q * max(0.0, float(ds.get(dk[0], 1.0)))
                          for dk, q in b.depot_stock.items()}

    # ── fleet attrition: cull least-reliable first, per depot, deterministic ─
    loss = float(sc.get("vehicle_loss_pct") or 0)
    if loss > 0:
        keep_frac = max(0.0, 1.0 - loss / 100.0)
        vbd = {}
        for depot, pool in b.vehicles_by_depot.items():
            ranked = sorted(pool, key=lambda v: (b.veh[v]["p_deadline"], v))
            vbd[depot] = ranked[:max(0, int(round(len(ranked) * keep_frac)))]
        nb.vehicles_by_depot = vbd
        kept = {v for pool in vbd.values() for v in pool}
        nb.vehicles = [v for v in b.vehicles
                       if (v.get("vehicle_id") if isinstance(v, dict) else v) in kept]
    return nb


def _mode_cfg(mode: str, overrides: dict | None) -> dict | None:
    mc = dict(cfg.WARTIME) if str(mode).lower() == "wartime" else None
    if overrides:
        mc = {**(mc or {}), **overrides}
    return mc


def run_whatif(snapshot_dir, scenario: dict | None = None, mode: str = "peacetime",
               mode_overrides: dict | None = None,
               time_limit: float | None = None) -> dict:
    """Solve the full plan frontier under a scenario. Returns plans plus a
    per-objective diff against the unmodified baseline world (same solver
    settings, so the diff isolates the scenario's effect)."""
    tl = time_limit or cfg.SOLVER_TIME_LIMIT_SERVICE_S
    base_b = load_bundle(snapshot_dir)
    mc = _mode_cfg(mode, mode_overrides)
    baseline = optimizer.solve_all(base_b, mode_cfg=None, time_limit=tl)
    world = apply_scenario(base_b, scenario)
    plans = optimizer.solve_all(world, mode_cfg=mc, time_limit=tl)
    diffs = {}
    base_ref = baseline.get("full_coverage") or next(iter(baseline.values()))
    for o, r in plans.items():
        ref = baseline.get(o, base_ref)
        diffs[o] = {k: round(r[k] - ref[k], 2) for k in
                    ("coverage_reachable_pct", "covered_tonnes", "total_cost",
                     "expected_loss_tonnes", "convoys", "risky_sorties")
                    if k in r and k in ref}
    return {"mode": mode, "scenario": scenario or {},
            "plans": plans, "baseline": baseline, "diff_vs_baseline": diffs}


def run_custom(snapshot_dir, items: list, scenario: dict | None = None,
               mode: str = "peacetime", mode_overrides: dict | None = None,
               name: str = "custom",
               time_limit: float | None = None) -> dict:
    """Re-optimize routing/vehicles/schedule for a user-edited manifest.
    items: [{post_id, sku_id, qty}]. Returns the re-optimized plan; user
    quantities are final except clamping to depot stock and road feasibility
    (clamps itemised in 'clamped_requests')."""
    tl = time_limit or cfg.SOLVER_TIME_LIMIT_SERVICE_S
    world = apply_scenario(load_bundle(snapshot_dir), scenario)
    manifest = {}
    for it in items:
        key = (str(it["post_id"]), str(it["sku_id"]))
        manifest[key] = manifest.get(key, 0.0) + float(it["qty"])
    return optimizer.solve_manifest(world, manifest, objective=name,
                                    mode_cfg=_mode_cfg(mode, mode_overrides),
                                    time_limit=tl)
