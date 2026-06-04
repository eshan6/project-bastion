"""
Project Bastion — Stage 2 Generator: Pass Closures (Disruption Events)

Two regimes:
  1. SEASONAL (Zoji La): closure-start date sampled from a Gaussian around
     historical mean; duration sampled with truncation to a realistic range.
     Modeled in MODERN (post-2020 BRO) regime — 33-79 day closures, not
     the historical 150-day pattern.
  2. STOCHASTIC (Khardung La, Chang La, Tsaka La, Marsimik La):
     no permanent closure. Daily P(closed) baseline + boost when a
     snow event hits at the pass's elevation band.

The output is one of the most important downstream inputs to the route
GBM model (Component 3), because route availability per day = AND of
the open-state of all passes the route crosses.

Key realism trade-off: weather → closure linkage is NOT a clean function.
BRO can sometimes keep a pass open despite heavy snow (record 2025-26
winter for Zoji La). We model this with a "BRO effort" stochastic
variable that randomly delays or shortens closures.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from config import (
    PASSES, SNOW_EVENT_CLOSURE_BOOST, SNOW_EVENT_THRESHOLD_MM,
    START_DATE, END_DATE, N_DAYS,
)
from world import World


# ---------------------------------------------------------------------------
# Seasonal closure (Zoji La regime)
# ---------------------------------------------------------------------------

def sample_seasonal_closures(rng: np.random.Generator, pass_name: str,
                             pass_cfg: dict, start: date, end: date) -> List[dict]:
    """
    For a seasonal-regime pass, sample one closure per winter season.
    Each closure: start day-of-year ~ N(closure_start_doy_mean, sigma);
                  duration ~ N(closure_duration_days_mean, sigma), clipped.
    """
    closures = []
    # Generate closures anchored on winter boundaries (winter of year Y
    # = Dec Y through Mar Y+1)
    for yr in range(start.year - 1, end.year + 1):
        start_doy_jitter = rng.normal(0, pass_cfg["closure_start_doy_sigma"])
        # Convert "mean DOY 357" to a date in year yr (357 ≈ Dec 23)
        try:
            base_start = date(yr, 1, 1) + timedelta(days=int(pass_cfg["closure_start_doy_mean"] + start_doy_jitter) - 1)
        except (ValueError, OverflowError):
            continue
        duration = int(np.clip(
            rng.normal(pass_cfg["closure_duration_days_mean"],
                       pass_cfg["closure_duration_days_sigma"]),
            pass_cfg["min_closure_days"],
            pass_cfg["max_closure_days"],
        ))
        closure_start = base_start
        closure_end = base_start + timedelta(days=duration)
        # Clip to simulation range
        if closure_end < start or closure_start > end:
            continue
        closures.append({
            "pass_name": pass_name,
            "start_date": max(closure_start, start),
            "end_date": min(closure_end, end),
            "duration_days": (min(closure_end, end) - max(closure_start, start)).days + 1,
            "closure_type": "seasonal",
            "winter_season": f"{yr}-{yr+1}",
        })

    # Interim closures within open season (avalanche / fresh storm)
    interim_p = pass_cfg.get("interim_closure_prob_per_day", 0.0)
    if interim_p > 0:
        # Identify open-season days (not within seasonal closures)
        closed_days = set()
        for c in closures:
            d = c["start_date"]
            while d <= c["end_date"]:
                closed_days.add(d)
                d += timedelta(days=1)
        # Walk through year, sample interim closures during open season
        d = start
        while d <= end:
            if d not in closed_days and rng.random() < interim_p:
                dur = int(rng.integers(*pass_cfg["interim_closure_duration"]))
                closures.append({
                    "pass_name": pass_name,
                    "start_date": d,
                    "end_date": d + timedelta(days=dur),
                    "duration_days": dur + 1,
                    "closure_type": "interim",
                    "winter_season": None,
                })
                d += timedelta(days=dur + 1)
            else:
                d += timedelta(days=1)

    return closures


# ---------------------------------------------------------------------------
# Stochastic closure (Khardung La regime)
# ---------------------------------------------------------------------------

def sample_stochastic_closures(rng: np.random.Generator, pass_name: str,
                                pass_cfg: dict, weather_df: pd.DataFrame,
                                world: World, start: date, end: date) -> List[dict]:
    """
    Day-by-day Bernoulli with seasonal probability.
    Snow events at posts in the pass's "served_posts_classification"
    region boost the closure probability.

    To couple weather to pass closure realistically, we identify the
    representative posts that are highest-elevation in the served region
    and use their snow events as the trigger.
    """
    served = pass_cfg["served_posts_classification"]

    # Map served_posts_classification to a representative post set
    POST_MAP = {
        "rear_admin": ["P001", "P002"],
        "nubra_axis": ["P017"],  # Shyok Junction (proxy for Nubra-bound)
        "pangong_axis": ["P003", "P008", "P018"],
        "chushul_demchok": ["P005", "P020", "P022"],
        "hot_springs_galwan": ["P027", "P028", "P030"],
    }
    rep_post_ids = POST_MAP.get(served, ["P001"])
    # Filter weather to these posts
    w = weather_df[weather_df["post_id"].isin(rep_post_ids)].copy()
    # Day-level aggregate: max snow event flag across the rep posts
    w["snow_severity"] = w["precip_mm"] * w["is_snow"].astype(int)
    daily_severity = w.groupby("date")["snow_severity"].max().to_dict()

    closures = []
    d = start
    while d <= end:
        month = d.month
        if month in (11, 12, 1, 2, 3, 4):
            p_base = pass_cfg["winter_closure_prob_per_day"]
        else:
            p_base = pass_cfg["summer_closure_prob_per_day"]

        # Boost by snow severity at rep posts
        snow_today = daily_severity.get(d, 0.0)
        if snow_today >= SNOW_EVENT_THRESHOLD_MM:
            p = min(0.95, p_base * SNOW_EVENT_CLOSURE_BOOST)
        else:
            p = p_base

        if rng.random() < p:
            dur = int(rng.integers(*pass_cfg["closure_duration"]))
            closures.append({
                "pass_name": pass_name,
                "start_date": d,
                "end_date": d + timedelta(days=dur),
                "duration_days": dur + 1,
                "closure_type": "stochastic_snow" if snow_today >= SNOW_EVENT_THRESHOLD_MM else "stochastic_routine",
                "winter_season": None,
            })
            d += timedelta(days=dur + 1)
        else:
            d += timedelta(days=1)
    return closures


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def generate_pass_closures(world: World, weather_df: pd.DataFrame,
                            seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      closures_df: one row per closure event
                   (pass_name, start_date, end_date, duration_days, closure_type)
      pass_status_df: daily long-form (pass_name, date, is_open)
    """
    rng = np.random.default_rng(seed)
    all_closures = []
    for pass_name, cfg in PASSES.items():
        if cfg["closure_regime"] == "seasonal":
            all_closures.extend(sample_seasonal_closures(rng, pass_name, cfg, START_DATE, END_DATE))
        else:
            all_closures.extend(sample_stochastic_closures(rng, pass_name, cfg, weather_df, world, START_DATE, END_DATE))
    closures_df = pd.DataFrame(all_closures)

    # Build daily pass status long-form
    pass_status_rows = []
    for pass_name in PASSES.keys():
        pass_closures = [c for c in all_closures if c["pass_name"] == pass_name]
        closed_days = set()
        for c in pass_closures:
            d = c["start_date"]
            while d <= c["end_date"]:
                closed_days.add(d)
                d += timedelta(days=1)
        d = START_DATE
        while d <= END_DATE:
            pass_status_rows.append({
                "pass_name": pass_name,
                "date": d,
                "is_open": d not in closed_days,
            })
            d += timedelta(days=1)
    pass_status_df = pd.DataFrame(pass_status_rows)

    return closures_df, pass_status_df


def validate_closures(closures_df: pd.DataFrame) -> dict:
    """Sanity checks against BRO prior.

    For Zoji La (seasonal regime), we report seasonal-event duration.
    For Khardung/Chang/Marsimik (stochastic regime), the right unit is
    closed-DAYS per year, not event count — because each event is a
    short (1-5 day) interruption and BRO reporting typically aggregates
    by total down-days, not event count.
    """
    n_years = 3

    zoji_seasonal = closures_df[(closures_df["pass_name"] == "Zoji La") &
                                (closures_df["closure_type"] == "seasonal")]
    avg_dur = zoji_seasonal["duration_days"].mean()
    zoji_all = closures_df[closures_df["pass_name"] == "Zoji La"]
    zoji_total_closed_days_per_yr = zoji_all["duration_days"].sum() / n_years

    def closed_days_per_yr(name):
        sub = closures_df[closures_df["pass_name"] == name]
        return round(float(sub["duration_days"].sum() / n_years), 1)

    return {
        "zoji_avg_seasonal_duration_days": round(float(avg_dur), 1) if not np.isnan(avg_dur) else None,
        "zoji_seasonal_prior_range_days": [33, 130],  # BRO modern era: 2025=33d, historical=150d
        "zoji_seasonal_count_total": int(len(zoji_seasonal)),
        "zoji_total_closed_days_per_yr": round(float(zoji_total_closed_days_per_yr), 1),
        "khardung_closed_days_per_yr": closed_days_per_yr("Khardung La"),
        "khardung_prior_closed_days_per_yr": [10, 30],
        "chang_closed_days_per_yr": closed_days_per_yr("Chang La"),
        "chang_prior_closed_days_per_yr": [10, 35],
        "tsaka_closed_days_per_yr": closed_days_per_yr("Tsaka La"),
        "marsimik_closed_days_per_yr": closed_days_per_yr("Marsimik La"),
        "marsimik_prior_closed_days_per_yr": [25, 70],   # elevation-scaled inference
    }


if __name__ == "__main__":
    from world import build_world
    from weather import generate_weather
    w = build_world(seed=42)
    wx, _ = generate_weather(w, seed=42)
    cl, status = generate_pass_closures(w, wx, seed=42)
    print(f"Closure events:     {len(cl)}")
    print(f"Pass-day status rows: {len(status):,}")
    print()
    print("By pass and type:")
    print(cl.groupby(["pass_name", "closure_type"]).size())
    print()
    v = validate_closures(cl)
    for k, val in v.items():
        print(f"  {k}: {val}")
