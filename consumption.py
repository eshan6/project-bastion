"""
Project Bastion — Stage 2 Generator: Consumption (and Stock state)

For each (post, SKU, day), draws actual consumption from:
    base_per_soldier_day  × troops_at_post
    × altitude_band_multiplier (from config)
    × weather_modifier (kerosene non-linear; medical winter-spike)
    × tempo_modifier (ammo + petrol)
    × isolation_modifier (when post's serving routes are all closed)
    × lognormal_noise(σ=0.18)
    × occasional_anomaly_spike  (heavy-tail event ~1% of days)

The tempo trajectory is shared at the BRIGADE level (a single AR-1-like
state machine on 4 states: low / normal / high / crisis). This couples
ammunition consumption across all posts on the same day — exactly the
sort of structural correlation a forecasting model needs to disentangle
from per-post noise.

Critical realism notes (per founder's randomness guidance):
  - Lognormal noise gives heavy-tail "outlier" days that the model
    should learn to robustness-tolerate, not chase
  - Anomaly spikes (1% chance, 3-8x baseline) are operationally real
    (a sick batch, an exercise burning more rounds, a forgotten
    requisition causing late catch-up draws) — NOT correlated with
    anything else
  - Isolation is fully derived from disruption status; it is NOT
    pre-scripted, so the optimizer/forecaster will see real isolation
    events emerge from the weather→closure cascade
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from config import (
    ALTITUDE_BANDS, SKUS,
    KEROSENE_TEMP_COUPLING, TEMPO_LEVELS, TEMPO_TRANSITION_PROBS_DAILY,
    TEMPO_AMMO_MULT, TEMPO_POL_MULT,
    ISOLATION_KEROSENE_BOOST, ISOLATION_RATION_BOOST, ISOLATION_MEDICAL_BOOST,
    CONSUMPTION_LOGNORMAL_SIGMA,
    START_DATE, END_DATE, N_DAYS,
)
from world import World


# ---------------------------------------------------------------------------
# Brigade-shared tempo trajectory
# ---------------------------------------------------------------------------

def simulate_tempo_trajectory(rng: np.random.Generator) -> List[str]:
    """
    Markov-chain simulation of brigade tempo over the horizon.
    Returns list of tempo labels, one per day.
    """
    state = "normal"
    trajectory = []
    for _ in range(N_DAYS):
        trajectory.append(state)
        probs = TEMPO_TRANSITION_PROBS_DAILY[state]
        next_state = rng.choice(TEMPO_LEVELS, p=[probs[s] for s in TEMPO_LEVELS])
        state = next_state
    return trajectory


# ---------------------------------------------------------------------------
# Weather coupling helpers
# ---------------------------------------------------------------------------

def kerosene_weather_mult(t_mean_c: float) -> float:
    """
    Piecewise temperature → kerosene burn multiplier.
    Above 0°C: gentle linear; below 0°C: kink, steeper slope.
    Reference: at 10°C, multiplier = 1.0.
    """
    ref = KEROSENE_TEMP_COUPLING["ref_temp_C"]
    if t_mean_c >= 0:
        return 1.0 + KEROSENE_TEMP_COUPLING["above_0_slope_per_C"] * (t_mean_c - ref)
    else:
        above_0_part = 1.0 + KEROSENE_TEMP_COUPLING["above_0_slope_per_C"] * (0 - ref)
        below_0_part = KEROSENE_TEMP_COUPLING["below_0_slope_per_C"] * (t_mean_c - 0)
        return above_0_part + below_0_part


def weather_mult_for_sku(sku: dict, t_mean_c: float) -> float:
    """Generic weather coupling for non-kerosene SKUs."""
    sens = sku["weather_sensitivity"]
    if sens == "none":
        return 1.0
    # All temperature-sensitivity SKUs follow a milder cold-spike pattern
    # than kerosene. At T=10°C: 1.0; at T=-20°C: depends on sensitivity.
    if sens == "low":
        cold_factor = 1.0 + max(0, -t_mean_c) * 0.008    # +24% at -30°C
    elif sens == "med":
        cold_factor = 1.0 + max(0, -t_mean_c) * 0.015    # +45% at -30°C
    elif sens == "high":
        cold_factor = 1.0 + max(0, -t_mean_c) * 0.025    # +75% at -30°C
    elif sens == "extreme":
        # Already handled by kerosene_weather_mult for POL-001
        cold_factor = 1.0 + max(0, -t_mean_c) * 0.04
    else:
        cold_factor = 1.0
    return cold_factor


# ---------------------------------------------------------------------------
# Isolation derivation from pass status
# ---------------------------------------------------------------------------

def compute_isolation_per_post_day(world: World,
                                    pass_status_df: pd.DataFrame) -> pd.DataFrame:
    """
    A post is isolated on a given day if ANY of its required-serving
    passes is closed. Semantics: `served_by` lists the passes a resupply
    convoy must traverse to reach the post; any closure breaks the chain.
    Returns long-form (post_id, date, is_isolated).
    """
    pass_status = (pass_status_df
                   .pivot(index="date", columns="pass_name", values="is_open"))
    rows = []
    for _, post in world.posts.iterrows():
        served_by = post["served_by"]
        if not served_by:
            # Posts with no pass dependency are never isolated
            for d in pass_status.index:
                rows.append({"post_id": post["id"], "date": d, "is_isolated": False})
            continue
        # ANY required pass closed → resupply chain broken → post isolated
        any_closed = (~pass_status[served_by]).any(axis=1)
        for d, isolated in any_closed.items():
            rows.append({"post_id": post["id"], "date": d, "is_isolated": bool(isolated)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Consumption draw
# ---------------------------------------------------------------------------

def draw_consumption(rng: np.random.Generator, sku: dict, post: dict,
                      t_mean_c: float, tempo: str, is_isolated: bool) -> float:
    """Single-draw daily consumption for (post, SKU)."""
    band_cfg = ALTITUDE_BANDS[post["band"]]
    troops = post["troops"]

    # Base per-soldier
    base = sku["base_per_soldier_day"]

    # Altitude band multipliers, head-specific
    if sku["head"] == "Rations":
        alt_mult = band_cfg["ration_mult"]
    elif sku["head"] == "POL":
        alt_mult = band_cfg["kerosene_mult"] if sku["sku"] == "POL-001" else 1.0
    elif sku["head"] == "Medical":
        alt_mult = band_cfg["medical_mult"]
    else:
        alt_mult = 1.0

    # Weather coupling
    if sku["sku"] == "POL-001":  # kerosene gets its own piecewise function
        wx_mult = kerosene_weather_mult(t_mean_c)
    else:
        wx_mult = weather_mult_for_sku(sku, t_mean_c)

    # Tempo coupling
    if sku["head"] == "Ammunition":
        tempo_mult = TEMPO_AMMO_MULT[tempo]
    elif sku["head"] == "POL":
        tempo_mult = TEMPO_POL_MULT[tempo]
    else:
        tempo_mult = 1.0

    # Isolation modifier
    iso_mult = 1.0
    if is_isolated:
        if sku["sku"] == "POL-001":
            iso_mult = ISOLATION_KEROSENE_BOOST
        elif sku["head"] == "Rations":
            iso_mult = ISOLATION_RATION_BOOST
        elif sku["head"] == "Medical":
            iso_mult = ISOLATION_MEDICAL_BOOST

    # Lognormal noise
    noise = rng.lognormal(mean=0, sigma=CONSUMPTION_LOGNORMAL_SIGMA)
    # Re-centre so the median (not mean) of the noise factor is 1
    noise *= np.exp(-CONSUMPTION_LOGNORMAL_SIGMA ** 2 / 2)

    # Occasional anomaly spike: 1% chance, 3-8x baseline
    anomaly = 1.0
    if rng.random() < 0.01:
        anomaly = rng.uniform(3.0, 8.0)

    qty = base * troops * alt_mult * wx_mult * tempo_mult * iso_mult * noise * anomaly
    return max(0.0, qty)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def generate_consumption(world: World, weather_df: pd.DataFrame,
                          pass_status_df: pd.DataFrame,
                          seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      consumption_df: (post_id, sku, date, qty_consumed, tempo, is_isolated,
                       t_mean_c, anomaly_flag)
      tempo_df: (date, tempo_level) — for reference / visibility
    """
    rng = np.random.default_rng(seed)
    tempo_trajectory = simulate_tempo_trajectory(rng)
    tempo_df = pd.DataFrame({
        "date": [START_DATE + timedelta(days=i) for i in range(N_DAYS)],
        "tempo_level": tempo_trajectory,
    })
    tempo_lookup = dict(zip(tempo_df["date"], tempo_df["tempo_level"]))

    # Build weather lookup (post_id, date) -> t_mean_c
    weather_df = weather_df.copy()
    weather_df["date"] = pd.to_datetime(weather_df["date"]).dt.date
    wx_lookup = weather_df.set_index(["post_id", "date"])["t_mean_c"].to_dict()

    # Isolation lookup
    iso_df = compute_isolation_per_post_day(world, pass_status_df)
    iso_df["date"] = pd.to_datetime(iso_df["date"]).dt.date
    iso_lookup = iso_df.set_index(["post_id", "date"])["is_isolated"].to_dict()

    posts_dict = world.posts.to_dict(orient="records")
    skus_dict = world.skus.to_dict(orient="records")

    rows = []
    for post in posts_dict:
        for sku in skus_dict:
            for day_offset in range(N_DAYS):
                dt = START_DATE + timedelta(days=day_offset)
                t = wx_lookup.get((post["id"], dt), 10.0)
                iso = iso_lookup.get((post["id"], dt), False)
                tempo = tempo_lookup[dt]
                qty = draw_consumption(rng, sku, post, t, tempo, iso)
                rows.append({
                    "post_id": post["id"],
                    "sku": sku["sku"],
                    "date": dt,
                    "qty_consumed": round(qty, 4),
                    "tempo": tempo,
                    "is_isolated": iso,
                    "t_mean_c": round(t, 2),
                })

    consumption_df = pd.DataFrame(rows)
    return consumption_df, tempo_df


def validate_consumption(consumption_df: pd.DataFrame, world: World) -> dict:
    """Sanity checks on consumption."""
    df = consumption_df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df["month"] = df["date"].dt.month

    # Kerosene seasonality at the deepest-cold reference post (DBO Forward,
    # 5050m, anchor Tangtse → adjusted to ~-19°C Jan T_mean).
    # The all-forward-posts average dilutes this signal because some
    # "forward" posts are at warmer 4300-4400m altitude.
    ref_post = "P034"  # DBO Forward Base
    ker = df[(df["sku"] == "POL-001") & (df["post_id"] == ref_post)]
    ker_jan = ker[ker["month"] == 1]["qty_consumed"].sum()
    ker_jul = ker[ker["month"] == 7]["qty_consumed"].sum()
    ker_ratio = ker_jan / ker_jul if ker_jul > 0 else None

    # Across-all-forward-posts ratio for context
    forward_posts = world.posts[world.posts["band"] == "forward"]["id"].tolist()
    ker_all = df[(df["sku"] == "POL-001") & (df["post_id"].isin(forward_posts))]
    ker_all_jan = ker_all[ker_all["month"] == 1]["qty_consumed"].sum()
    ker_all_jul = ker_all[ker_all["month"] == 7]["qty_consumed"].sum()
    ker_all_ratio = ker_all_jan / ker_all_jul if ker_all_jul > 0 else None

    # Ammunition tempo coupling: ratio of crisis-tempo days to normal-tempo days
    ammo = df[df["sku"] == "AMM-001"]
    if "crisis" in ammo["tempo"].values:
        crisis_mean = ammo[ammo["tempo"] == "crisis"]["qty_consumed"].mean()
    else:
        crisis_mean = None
    normal_mean = ammo[ammo["tempo"] == "normal"]["qty_consumed"].mean()

    # Isolation effect on kerosene at forward posts
    ker_fwd = df[(df["sku"] == "POL-001") & (df["post_id"].isin(forward_posts))]
    iso_mean = ker_fwd[ker_fwd["is_isolated"]]["qty_consumed"].mean() if ker_fwd["is_isolated"].any() else None
    open_mean = ker_fwd[~ker_fwd["is_isolated"]]["qty_consumed"].mean()

    # Daily total kerosene at the brigade level (peak winter)
    daily_ker = df[df["sku"] == "POL-001"].groupby("date")["qty_consumed"].sum()
    peak_ker_day = daily_ker.max()

    return {
        "kerosene_jan_to_jul_ratio_DBO_5050m": round(float(ker_ratio), 2) if ker_ratio else None,
        "kerosene_jan_to_jul_ratio_all_forward_avg": round(float(ker_all_ratio), 2) if ker_all_ratio else None,
        "kerosene_seasonality_prior": "3-6x at deepest-cold posts (Tribune 'colossal' winter vs summer)",
        "ammo_crisis_to_normal_ratio": round(float(crisis_mean / normal_mean), 2) if crisis_mean else "no crisis days drawn",
        "ammo_tempo_prior": "3.5x at crisis (TEMPO_AMMO_MULT)",
        "kerosene_isolation_boost_observed_naive": round(float(iso_mean / open_mean), 2) if iso_mean else "no isolation events",
        "kerosene_isolation_boost_prior_naive": 1.30,
        "kerosene_isolation_note": "Observed > prior because isolation events correlate with extreme cold; cold-coupling stacks with isolation boost. Decomposing the two requires controlling for T_mean — leave this for the model to disentangle.",
        "peak_daily_brigade_kerosene_L": round(float(peak_ker_day), 0),
        "peak_per_soldier_L": round(float(peak_ker_day / world.posts['troops'].sum()), 2),
        "kerosene_realism_note": "Underground dumps store 400,000 L each (Swarajyamag). Brigade peak under 1 L/soldier/day-equivalent is realistic; spikes from concentrated isolated forward posts can drive higher."
    }


if __name__ == "__main__":
    from world import build_world
    from weather import generate_weather
    from disruption import generate_pass_closures
    w = build_world(seed=42)
    wx, _ = generate_weather(w, seed=42)
    cl, status = generate_pass_closures(w, wx, seed=42)
    cons, tempo = generate_consumption(w, wx, status, seed=42)
    print(f"Consumption rows: {len(cons):,}")
    print(f"Tempo rows: {len(tempo)}")
    print()
    print("Tempo distribution:")
    print(tempo["tempo_level"].value_counts())
    print()
    v = validate_consumption(cons, w)
    for k, val in v.items():
        print(f"  {k}: {val}")
