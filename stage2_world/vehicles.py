"""
Project Bastion — Stage 2 Generator: Vehicle Deadline Events

For each vehicle, simulates daily mission cycles and accumulating
"hazard exposure" toward a Weibull-distributed deadline event.

Approach:
  Each vehicle has a Weibull(shape, scale) survival prior (per class).
  Each day, we add hazard contribution proportional to:
    - mission altitude band exposure (forward × 2.1, mid × 1.4)
    - winter season (Nov-Mar × 1.6)
    - mission across disruption (closed-pass route × 2.4)
  When cumulative hazard exceeds a Weibull-sampled threshold, the
  vehicle goes "deadline" (VOR — Vehicle Off-Road).

Outputs:
  events_df: (vehicle_id, deadline_date, return_date, root_cause_flags,
              repair_location)

This is the WEAKEST module in terms of empirical anchoring (no public
survival data exists). Marked accordingly. The Weibull priors come from
CAG-cited reliability shortfalls but the shape/scale are SYNTHETIC-INFERRED.
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
)
from world import World


def sample_event_threshold(rng: np.random.Generator) -> float:
    """
    Sample a cumulative hazard threshold from Exp(1).
    H(T) at event time ~ Exp(1) — standard survival analysis identity.
    """
    return float(rng.exponential(1.0))


def determine_mission_axis_band(vehicle_home_depot: str, world: World) -> str:
    """
    Most missions out of a depot go to forward posts on that depot's axis.
    We return an aggregate band weighting: assume 30% depot, 30% mid, 40% forward
    for forward-supplying depots; depots vary in their mix.
    Simplification: each mission day samples one band.
    """
    return "weighted"  # use weighted sampling per-day


def daily_hazard_increment(rng: np.random.Generator, dt: date,
                            pass_status_lookup: dict,
                            relevant_passes: List[str],
                            shape: float, scale: float) -> float:
    """
    Hazard contribution for one mission-day. Calibrated as a small
    fraction of the natural Weibull-implied daily hazard at mid-life.
    A neutral (depot, summer, open) mission day contributes ~1/scale_days,
    so an unmodified vehicle would natural-deadline after ~scale_days
    of consecutive missions. Modifiers stack multiplicatively.
    """
    base_hazard_per_mission_day = 1.0 / scale   # normalised to scale_days

    # Sample mission altitude band
    band = rng.choice(["depot", "mid", "forward"], p=[0.30, 0.30, 0.40])
    mult = VEHICLE_HAZARD_ALTITUDE_MULT[band]

    if dt.month in (11, 12, 1, 2, 3):
        mult *= VEHICLE_HAZARD_WINTER_MULT

    any_closed = any(not pass_status_lookup.get((p, dt), True) for p in relevant_passes)
    if any_closed:
        mult *= VEHICLE_HAZARD_DISRUPTION_MULT

    return base_hazard_per_mission_day * mult


def simulate_vehicle(rng: np.random.Generator, vehicle: dict,
                      pass_status_lookup: dict,
                      relevant_passes: List[str]) -> List[dict]:
    """
    Simulate one vehicle over the 3yr horizon. Tracks cumulative hazard
    until threshold breach → deadline → repair → resume.
    Returns list of deadline events.
    """
    shape = vehicle["weibull_shape"]
    scale = vehicle["weibull_scale_days"]

    # Sample initial threshold from Exp(1) — cumulative hazard at event
    threshold = sample_event_threshold(rng)
    # Pre-load some hazard from initial age — older vehicles have already
    # accumulated some hazard before the simulation starts
    initial_age = vehicle["initial_age_days"]
    cum_hazard = 0.5 * (initial_age / scale)   # crude age pre-load

    events = []
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

        # Mission probability today (lower in winter)
        if d.month in (11, 12, 1, 2, 3):
            mission_p = MISSIONS_PER_MONTH_WINTER / 30.0
        else:
            mission_p = MISSIONS_PER_MONTH_OPEN / 30.0

        if rng.random() < mission_p:
            cum_hazard += daily_hazard_increment(rng, d, pass_status_lookup, relevant_passes,
                                                  shape, scale)
            if cum_hazard >= threshold:
                # Deadline event
                if rng.random() < DEADLINE_REQUIRES_DEPOT_PROB:
                    repair_days = int(rng.integers(*REPAIR_TIME_DEPOT_DAYS))
                    repair_loc = "depot"
                else:
                    repair_days = int(rng.integers(*REPAIR_TIME_FIELD_DAYS))
                    repair_loc = "field"
                return_date = d + timedelta(days=repair_days)
                events.append({
                    "vehicle_id": vehicle["vehicle_id"],
                    "vehicle_class": vehicle["vehicle_class"],
                    "deadline_date": d,
                    "return_date": return_date,
                    "repair_days": repair_days,
                    "repair_location": repair_loc,
                    "winter_flag": d.month in (11, 12, 1, 2, 3),
                })
                in_repair = True
                repair_until = return_date
                # Reset cycle. Post-repair vehicles are slightly more
                # fragile (15% lower next-event threshold).
                cum_hazard = 0.0
                threshold = sample_event_threshold(rng) * 0.85

        d += timedelta(days=1)

    return events


def generate_vehicle_events(world: World, pass_status_df: pd.DataFrame,
                              seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    pass_status_df = pass_status_df.copy()
    pass_status_df["date"] = pd.to_datetime(pass_status_df["date"]).dt.date
    pass_status_lookup = pass_status_df.set_index(["pass_name", "date"])["is_open"].to_dict()
    all_passes = list(pass_status_df["pass_name"].unique())

    all_events = []
    for _, v in world.vehicles.iterrows():
        events = simulate_vehicle(rng, v.to_dict(), pass_status_lookup, all_passes)
        all_events.extend(events)
    return pd.DataFrame(all_events)


def validate_vehicles(events_df: pd.DataFrame, world: World) -> dict:
    """Sanity checks on vehicle event distribution."""
    if len(events_df) == 0:
        return {"error": "No deadline events generated — hazard model under-firing"}

    # Events per vehicle (mean)
    events_per_vehicle = len(events_df) / len(world.vehicles)
    # Winter share
    winter_share = events_df["winter_flag"].mean()
    # Depot vs field repairs
    depot_share = (events_df["repair_location"] == "depot").mean()
    # Mean repair days
    mean_repair = events_df["repair_days"].mean()
    # Average daily deadline rate
    daily_rate = len(events_df) / N_DAYS

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
    }


if __name__ == "__main__":
    from world import build_world
    from weather import generate_weather
    from disruption import generate_pass_closures
    w = build_world(seed=42)
    wx, _ = generate_weather(w, seed=42)
    _, status = generate_pass_closures(w, wx, seed=42)
    ev = generate_vehicle_events(w, status, seed=42)
    print(f"Vehicle deadline events: {len(ev)}")
    print()
    if len(ev):
        print(ev.head().to_string(index=False))
        print()
    v = validate_vehicles(ev, w)
    for k, val in v.items():
        print(f"  {k}: {val}")
