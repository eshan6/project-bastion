"""
Project Bastion — Stage 2 Generator: Vehicle Deadline Events (v2.0)

v2.0 change (#1 from audit): PERSISTENT PER-VEHICLE MISSION-BAND MIX.

v1 sampled each mission-day's altitude band i.i.d. with identical weights
[0.30, 0.30, 0.40] for every vehicle. That made every vehicle's hazard
process statistically exchangeable — there was nothing for a reliability
model to learn, and the Stage 3 scorer's Brier skill was ~0 by construction.

v2 derives a persistent band mix per vehicle from its home depot's axis:
a vehicle homed at Durbuk (DBO axis) spends most mission-days on forward
hauls above 4500m; a Karu (Rear) vehicle mostly shuttles between depots.
A small per-vehicle Dirichlet jitter around the axis mix adds within-axis
heterogeneity (driver/route assignment variation). The mix is drawn ONCE
per vehicle and reused for its whole 3-year history — persistent, hence
learnable.

Realism anchor: convoys on the DS-DBO road and Chushul approaches operate
at 4500-5500m where engine stress, brake wear, and cold-start damage are
documented as the dominant VOR drivers (CAG audits on HA vehicle
serviceability). Mix shares are SYNTHETIC-INFERRED; the axis→altitude
structure is the anchored part.

Everything else is unchanged from v1: Weibull(shape, scale) class priors,
Exp(1) cumulative-hazard thresholds, winter ×1.6, closed-pass ×2.4, repair
cycles with post-repair fragility ×0.85.

Outputs:
  events_df: (vehicle_id, deadline_date, return_date, root_cause_flags,
              repair_location)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from config import (
    VEHICLE_HAZARD_ALTITUDE_MULT, VEHICLE_HAZARD_WINTER_MULT,
    VEHICLE_HAZARD_DISRUPTION_MULT,
    MISSIONS_PER_MONTH_OPEN, MISSIONS_PER_MONTH_WINTER,
    REPAIR_TIME_DEPOT_DAYS, REPAIR_TIME_FIELD_DAYS,
    DEADLINE_REQUIRES_DEPOT_PROB,
    START_DATE, END_DATE, N_DAYS,
    VEHICLE_FAILURE_SUBSYSTEMS, SUBSYSTEM_PARTS, SPARES_CATALOGUE,
    COLD_START_PARTS_MULT_AT_MAX,
    AXIS_MISSION_BAND_MIX, VEHICLE_MIX_DIRICHLET_CONCENTRATION,
    VEHICLE_DUTY_INTENSITY_SIGMA,
)

# v3.5: nominal one-way mission distance (km) by band — used only to accumulate
# an OBSERVABLE cumulative-altitude-km odometer per vehicle (a covariate the
# scorer can train on). Magnitudes are SYNTHETIC-INFERRED; the point is the
# per-vehicle SPREAD, which is what makes risk learnable.
BAND_MISSION_KM = {"depot": 40.0, "mid": 90.0, "forward": 150.0}
# Altitude-km only counts mid+forward (the wearing kind). Cold-starts accrue on
# winter mid/forward mission-days.
from world import World


# ─────────────────────────────────────────────────────────────────────────────
# v2: persistent mission-band mixes by home-depot axis
# ─────────────────────────────────────────────────────────────────────────────
# (depot, mid, forward) shares of a vehicle's mission-days, by the modal axis
# its home depot serves. SYNTHETIC-INFERRED shares; structure anchored to the
# fact that DS-DBO / Chushul convoy legs run at 4500-5500m while Karu/Leh
# rear shuttles stay near 3500m.

def depot_axis_map(posts_df: pd.DataFrame) -> Dict[str, str]:
    """Map each depot to the modal axis of the non-depot posts it serves.
    Same logic the Stage 3 scorer uses, kept here independently so the
    generator has no import edge into Stage 3."""
    non_depots = posts_df[~posts_df["is_depot"]]
    mode = non_depots.groupby("serving_depot_id")["axis"].agg(
        lambda s: s.value_counts().index[0] if len(s) else "Rear")
    out = {d: "Rear" for d in posts_df[posts_df["is_depot"]]["id"]}
    for depot_id, axis in mode.items():
        out[depot_id] = axis
    return out


def draw_vehicle_band_mixes(rng: np.random.Generator, vehicles_df: pd.DataFrame,
                             posts_df: pd.DataFrame) -> Dict[str, np.ndarray]:
    """Draw ONE persistent (depot, mid, forward) mix per vehicle:
    Dirichlet around its home-depot axis mix. Iteration order is the
    vehicles table order (V0000, V0001, ...) — deterministic for a seed."""
    d2a = depot_axis_map(posts_df)
    mixes: Dict[str, np.ndarray] = {}
    for _, v in vehicles_df.iterrows():
        axis = d2a.get(v["home_depot_id"], "Rear")
        base = np.asarray(AXIS_MISSION_BAND_MIX.get(axis, AXIS_MISSION_BAND_MIX["Rear"]))
        mix = rng.dirichlet(base * VEHICLE_MIX_DIRICHLET_CONCENTRATION)
        mixes[v["vehicle_id"]] = mix
    return mixes


def draw_duty_intensities(rng: np.random.Generator,
                           vehicles_df: pd.DataFrame) -> Dict[str, float]:
    """ONE persistent duty-intensity multiplier per vehicle: lognormal with
    mean exactly 1 (mu = -sigma^2/2). Scales the per-mission-day hazard —
    a heavily-used vehicle wears proportionally faster."""
    s = VEHICLE_DUTY_INTENSITY_SIGMA
    out: Dict[str, float] = {}
    for _, v in vehicles_df.iterrows():
        out[v["vehicle_id"]] = float(rng.lognormal(mean=-0.5 * s * s, sigma=s))
    return out


def sample_event_threshold(rng: np.random.Generator) -> float:
    """Cumulative-hazard threshold at event time ~ Exp(1) — standard
    survival-analysis identity."""
    return float(rng.exponential(1.0))


def daily_hazard_increment(rng: np.random.Generator, dt: date,
                            pass_status_lookup: dict,
                            relevant_passes: List[str],
                            scale: float,
                            band_mix: np.ndarray) -> float:
    """Hazard contribution for one mission-day. A neutral (depot, summer,
    open) mission day contributes 1/scale_days. v2: the band is sampled from
    THIS vehicle's persistent mix, not a fleet-wide constant."""
    base_hazard_per_mission_day = 1.0 / scale

    band = rng.choice(["depot", "mid", "forward"], p=band_mix)
    mult = VEHICLE_HAZARD_ALTITUDE_MULT[band]

    if dt.month in (11, 12, 1, 2, 3):
        mult *= VEHICLE_HAZARD_WINTER_MULT

    any_closed = any(not pass_status_lookup.get((p, dt), True) for p in relevant_passes)
    if any_closed:
        mult *= VEHICLE_HAZARD_DISRUPTION_MULT

    return base_hazard_per_mission_day * mult


def _draw_spares_for_event(rng: np.random.Generator, vehicle_id: str,
                           vehicle_class: str, deadline_date: date,
                           cold_start_exposure: float) -> tuple:
    """v3.5: pick a failure subsystem then its consumed spare SKUs. Returns
    (subsystem, [spare rows]). Deterministic given RNG state. Cold-start
    exposure (0..1) raises electrical/cooling part probability — the
    'winter kills batteries and radiators' pattern."""
    subs = list(VEHICLE_FAILURE_SUBSYSTEMS.keys())
    probs = np.array([VEHICLE_FAILURE_SUBSYSTEMS[s] for s in subs], dtype=float)
    probs = probs / probs.sum()
    subsystem = subs[int(rng.choice(len(subs), p=probs))]
    cold_mult = 1.0
    if subsystem in ("electrical", "engine_cooling"):
        cold_mult = 1.0 + (COLD_START_PARTS_MULT_AT_MAX - 1.0) * cold_start_exposure
    rows = []
    for sku, p_consume, (qmin, qmax) in SUBSYSTEM_PARTS[subsystem]:
        if rng.random() < min(1.0, p_consume * cold_mult):
            qty = int(rng.integers(qmin, qmax + 1))
            if qty > 0:
                rows.append({
                    "vehicle_id": vehicle_id, "vehicle_class": vehicle_class,
                    "deadline_date": deadline_date, "subsystem": subsystem,
                    "sku": sku, "qty": qty,
                    "weight_kg": round(SPARES_CATALOGUE[sku]["weight_kg"] * qty, 1),
                    "provenance": "synthetic-arbitrary",
                })
    return subsystem, rows


def simulate_vehicle(rng: np.random.Generator, vehicle: dict,
                      pass_status_lookup: dict,
                      relevant_passes: List[str],
                      band_mix: np.ndarray,
                      duty_intensity: float = 1.0) -> tuple:
    """Simulate one vehicle over the 3yr horizon. Tracks cumulative hazard
    until threshold breach → deadline → repair → resume.

    v3.5: also accumulates two OBSERVABLE odometers — cumulative altitude-km
    (mid+forward mission distance) and cold-start count (winter mid/forward
    mission-days) — written onto every event so the Stage 3 scorer can train on
    per-vehicle wear instead of axis averages. Emits spares consumption per
    event. Returns (events, spares)."""
    scale = vehicle["weibull_scale_days"]
    threshold = sample_event_threshold(rng)
    initial_age = vehicle["initial_age_days"]
    cum_hazard = 0.5 * (initial_age / scale)

    cum_alt_km = 0.0          # observable odometer (mid+forward km)
    cold_starts = 0           # observable odometer (winter mid/fwd starts)
    events, spares = [], []
    d = START_DATE
    in_repair = False
    repair_until = START_DATE

    while d <= END_DATE:
        if in_repair:
            if d >= repair_until:
                in_repair = False
            else:
                d += timedelta(days=1)
                continue

        winter = d.month in (11, 12, 1, 2, 3)
        mission_p = (MISSIONS_PER_MONTH_WINTER if winter else MISSIONS_PER_MONTH_OPEN) / 30.0

        if rng.random() < mission_p:
            band = rng.choice(["depot", "mid", "forward"], p=band_mix)
            # accumulate observable wear odometers
            cum_alt_km += duty_intensity * BAND_MISSION_KM[band] * (band != "depot")
            if winter and band != "depot":
                cold_starts += 1
            # hazard increment (same math as v2, band already drawn above)
            mult = VEHICLE_HAZARD_ALTITUDE_MULT[band]
            if winter:
                mult *= VEHICLE_HAZARD_WINTER_MULT
            if any(not pass_status_lookup.get((p, d), True) for p in relevant_passes):
                mult *= VEHICLE_HAZARD_DISRUPTION_MULT
            cum_hazard += duty_intensity * (1.0 / scale) * mult

            if cum_hazard >= threshold:
                if rng.random() < DEADLINE_REQUIRES_DEPOT_PROB:
                    repair_days = int(rng.integers(*REPAIR_TIME_DEPOT_DAYS)); repair_loc = "depot"
                else:
                    repair_days = int(rng.integers(*REPAIR_TIME_FIELD_DAYS)); repair_loc = "field"
                return_date = d + timedelta(days=repair_days)
                # cold-start exposure proxy in [0,1]: saturating in accumulated
                # cold-starts (≈full exposure by ~120 winter starts)
                cold_exp = min(1.0, cold_starts / 120.0)
                subsystem, spare_rows = _draw_spares_for_event(
                    rng, vehicle["vehicle_id"], vehicle["vehicle_class"], d, cold_exp)
                events.append({
                    "vehicle_id": vehicle["vehicle_id"],
                    "vehicle_class": vehicle["vehicle_class"],
                    "deadline_date": d, "return_date": return_date,
                    "repair_days": repair_days, "repair_location": repair_loc,
                    "winter_flag": winter,
                    "subsystem": subsystem,
                    # observable covariates AT failure time
                    "age_days_at_event": initial_age + (d - START_DATE).days,
                    "cum_altitude_km": round(cum_alt_km, 1),
                    "cold_starts": cold_starts,
                    "n_spare_skus": len(spare_rows),
                })
                spares.extend(spare_rows)
                in_repair = True
                repair_until = return_date
                cum_hazard = 0.0
                threshold = sample_event_threshold(rng) * 0.85
        d += timedelta(days=1)

    return events, spares


def generate_vehicle_events(world: World, pass_status_df: pd.DataFrame,
                              seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pass_status_df = pass_status_df.copy()
    pass_status_df["date"] = pd.to_datetime(pass_status_df["date"]).dt.date
    pass_status_lookup = pass_status_df.set_index(["pass_name", "date"])["is_open"].to_dict()
    all_passes = list(pass_status_df["pass_name"].unique())

    # v3.5: band mix + duty intensity are now PERSISTED on the vehicles table
    # (drawn in world.build_vehicles, same RNG order). Read them here so the
    # generated events are consistent with the observable covariates the scorer
    # trains on. Backward-compatible: fall back to redrawing if columns absent.
    have_cols = {"band_mix_depot", "band_mix_mid", "band_mix_forward",
                 "duty_intensity"}.issubset(world.vehicles.columns)
    if not have_cols:
        band_mixes = draw_vehicle_band_mixes(rng, world.vehicles, world.posts)
        duty = draw_duty_intensities(rng, world.vehicles)

    all_events, all_spares = [], []
    for _, v in world.vehicles.iterrows():
        vd = v.to_dict()
        if have_cols:
            mix = np.array([vd["band_mix_depot"], vd["band_mix_mid"], vd["band_mix_forward"]])
            di = float(vd["duty_intensity"])
        else:
            mix = band_mixes[vd["vehicle_id"]]; di = duty[vd["vehicle_id"]]
        events, spares = simulate_vehicle(rng, vd, pass_status_lookup, all_passes, mix, di)
        all_events.extend(events)
        all_spares.extend(spares)
    events_df = pd.DataFrame(all_events)
    spares_df = pd.DataFrame(all_spares)
    return events_df, spares_df


def validate_vehicles(events_df: pd.DataFrame, world: World) -> dict:
    """Sanity checks on vehicle event distribution. v2 adds the axis-rate
    spread — the whole point of the change."""
    if len(events_df) == 0:
        return {"error": "No deadline events generated — hazard model under-firing"}

    events_per_vehicle = len(events_df) / len(world.vehicles)
    winter_share = events_df["winter_flag"].mean()
    depot_share = (events_df["repair_location"] == "depot").mean()
    mean_repair = events_df["repair_days"].mean()
    daily_rate = len(events_df) / N_DAYS

    # v2 check: per-axis event rate spread (events per vehicle, by home axis)
    d2a = depot_axis_map(world.posts)
    vmap = world.vehicles.set_index("vehicle_id")["home_depot_id"].map(d2a)
    ev = events_df.copy()
    ev["axis"] = ev["vehicle_id"].map(vmap)
    veh_axis = world.vehicles.assign(axis=world.vehicles["home_depot_id"].map(d2a))
    axis_rate = {}
    for axis, n_veh in veh_axis["axis"].value_counts().items():
        n_ev = (ev["axis"] == axis).sum()
        axis_rate[axis] = round(float(n_ev / n_veh), 2)

    return {
        "events_per_vehicle_3yr": round(float(events_per_vehicle), 2),
        "events_per_vehicle_prior": "1-3 deadlines per vehicle over 3yr at HA conditions",
        "winter_event_share": round(float(winter_share), 2),
        "winter_event_share_prior": "≈0.50 (3.2x base hazard in winter, with 5/12 winter months ≈ 0.57)",
        "depot_repair_share": round(float(depot_share), 2),
        "depot_repair_share_prior": 0.35,
        "mean_repair_days": round(float(mean_repair), 1),
        "deadlines_per_day_brigade": round(float(daily_rate), 2),
        "fleet_size": len(world.vehicles),
        "events_per_vehicle_by_home_axis": axis_rate,
        "axis_rate_note": "v2: spread across axes is the learnable signal (#1). "
                          "Forward-axis fleets (DBO) should run ~1.4-1.6x the Rear rate.",
    }


if __name__ == "__main__":
    from world import build_world
    from weather import generate_weather
    from disruption import generate_pass_closures
    w = build_world(seed=42)
    wx, _ = generate_weather(w, seed=42)
    _, status = generate_pass_closures(w, wx, seed=42)
    ev, spares = generate_vehicle_events(w, status, seed=42)
    print(f"Vehicle deadline events: {len(ev)}  |  spares rows: {len(spares)}")
    print()
    if len(ev):
        print(ev.head().to_string(index=False))
        print()
    v = validate_vehicles(ev, w)
    for k, val in v.items():
        print(f"  {k}: {val}")
