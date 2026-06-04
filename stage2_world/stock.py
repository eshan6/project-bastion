"""
Project Bastion — Stage 2 Generator: Stock Dynamics

Runs the forward accounting identity per (post, SKU, day):

    closing_stock = opening_stock
                    + aws_receipt          (Advance Winter Stocking bulk push)
                    + routine_receipt      (trickle convoys when not isolated)
                    - consumption          (from the consumption module)
                    - spoilage             (perishables only)

This is the layer that makes a stockout *predictable* — without a running
stock balance there is no days-to-stockout, and the FSP has nothing to
forecast.

Design decisions (locked with founder, 2026-05-14):

  1. AWS success rate ~85-90%. CAG-documented shortfalls are audit-flagged
     exceptions, not the steady state. A generator where forward posts
     stock out every winter would be thin synthetic dressed as thick — the
     model would learn "winter => stockout" and never do real work.

  2. Shortfalls concentrate in kerosene + perishables, and they do so
     *emergently*: the AWS attainment shortfall, applied to the SKUs with
     the steepest winter demand ramp (kerosene) and the shortest shelf
     life (perishables), opens the deepest relative gaps. We additionally
     apply a mild attainment drag to POL (hardest to bulk-pre-position by
     volume) consistent with the Tribune's "colossal" fuel framing.
     Clothing/medical are kept reliable at post level — the CAG shortfalls
     there were procurement-cycle problems UPSTREAM of the post, a
     different mechanism we are deliberately not modelling as AWS failure.

  3. Opening balances come from a discarded WARM-UP YEAR (2021). We
     prepend a synthetic year of consumption (resampled from the real
     consumption distribution, preserving per-(post,SKU) seasonality),
     run the full stock dynamics through it, then discard it. Jan 1 2022
     therefore opens at whatever mid-winter-drawdown level the sawtooth
     actually produced — no hand-seeded artifact.

The warm-up year is resampled rather than fully re-simulated upstream:
weather/disruption/consumption are not re-run for 2021. The warm-up only
has to wash out the seed artifact, not be physically perfect — and a
month-matched resample of the real consumption distribution preserves the
seasonal shape that matters for that purpose. The discarded year never
reaches the model.

Outputs:
  stock_df: (post_id, sku, date, opening_stock, aws_receipt,
             routine_receipt, consumption, spoilage, closing_stock,
             days_of_cover, status)  -- status in {ok, rationing, stockout}
  aws_plan_df: (post_id, sku, winter_year, post_max_isolation_run_days,
                planning_days, tier_safety_mult, winter_daily_rate_p80,
                winter_daily_rate_mean, attainment_fraction,
                aws_target_qty)  -- the lineage record of what each post
                planned to pre-position and how well it did
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

from config import (
    START_DATE, END_DATE, N_DAYS,
    AWS_SEASON_MONTHS,
    AWS_ISOLATION_PLANNING_MARGIN_DAYS, AWS_TIER_MIN_PLANNING_DAYS,
    AWS_TIER_SAFETY_MULT,
    AWS_PLANNING_HORIZON_NOISE_FRAC, AWS_PLANNING_MARGIN_NOISE_DAYS,
    AWS_AMMO_TEMPO_MISESTIMATE_HEADS,
    AWS_AMMO_TEMPO_BETA_A, AWS_AMMO_TEMPO_BETA_B,
    AWS_AMMO_TEMPO_MISESTIMATE_MEAN,
    AWS_AMMO_TEMPO_MISESTIMATE_MIN, AWS_AMMO_TEMPO_MISESTIMATE_MAX,
    AWS_ATTAINMENT_BETA_A, AWS_ATTAINMENT_BETA_B,
    AWS_ATTAINMENT_MIN, AWS_ATTAINMENT_MAX, AWS_ATTAINMENT_MEAN_TARGET,
    AWS_HARD_TO_STOCK_HEADS, AWS_HARD_TO_STOCK_PENALTY,
    AWS_POL_ATTAINMENT_MIN,
    AWS_PERISHABLE_SHELF_LIFE_CUTOFF_DAYS, AWS_PERISHABLE_MAX_COVERAGE_DAYS,
    ROUTINE_RECEIPT_REFILL_TO_COVERAGE_DAYS,
    ROUTINE_RECEIPT_CONVOY_LATENCY_DAYS,
    ROUTINE_CONVOY_MIN_GAP_DAYS, ROUTINE_CONVOY_DISPATCH_GAP_DAYS,
    POL_CONVOY_MIN_GAP_DAYS, POL_CONVOY_MAX_REFILL_COVERAGE_DAYS,
    PERISHABLE_SUBSTITUTION_ENABLED, PERISHABLE_GAP_GRACE_DAYS,
    PERISHABLE_DEMAND_DECAY_RATE, PERISHABLE_DEMAND_RESIDUAL_FLOOR,
    PERISHABLE_SUBSTITUTE_MAP,
    EMERGENCY_PERISHABLE_RESUPPLY_ENABLED, EMERGENCY_PERISHABLE_DISPATCH_PROB,
    EMERGENCY_PERISHABLE_REFILL_COVERAGE_DAYS,
    EMERGENCY_PERISHABLE_WEATHER_BLOCK_TMIN_C,
    SPOILAGE_DAILY_FRACTION_PERISHABLE, SPOILAGE_SHELF_LIFE_PERISHABLE_CUTOFF,
    WARMUP_YEAR, WARMUP_SEED_COVERAGE_FRACTION,
    STOCKOUT_RATIONING_THRESHOLD_DAYS,
)
from world import World
from consumption import compute_isolation_per_post_day


# ---------------------------------------------------------------------------
# Warm-up year construction
# ---------------------------------------------------------------------------

def build_warmup_consumption(consumption_df: pd.DataFrame,
                              rng: np.random.Generator) -> pd.DataFrame:
    """
    Build a synthetic 2021 warm-up year by month-matched resampling of the
    real consumption distribution, per (post, SKU).

    For each (post, SKU, calendar-month), we take the pool of real daily
    consumption values from that month across the 3 real years, and draw
    one value per day in the corresponding 2021 month. This preserves the
    seasonal shape (a January day looks like a January day) without
    pretending to re-simulate 2021's specific weather.

    The warm-up year is discarded after stock dynamics run through it; its
    only job is to wash out the opening-balance seed artifact.
    """
    cons = consumption_df.copy()
    cons["date"] = pd.to_datetime(cons["date"])
    cons["month"] = cons["date"].dt.month

    # Pool of real daily consumption values, keyed (post_id, sku, month).
    pools: Dict[Tuple[str, str, int], np.ndarray] = {}
    for (pid, sku, mth), grp in cons.groupby(["post_id", "sku", "month"]):
        pools[(pid, sku, mth)] = grp["qty_consumed"].to_numpy()

    warmup_start = date(WARMUP_YEAR, 1, 1)
    warmup_end = date(WARMUP_YEAR, 12, 31)
    warmup_days = (warmup_end - warmup_start).days + 1

    rows = []
    posts = cons["post_id"].unique()
    skus = cons["sku"].unique()
    for pid in posts:
        for sku in skus:
            for d in range(warmup_days):
                dt = warmup_start + timedelta(days=d)
                pool = pools.get((pid, sku, dt.month))
                if pool is None or len(pool) == 0:
                    qty = 0.0
                else:
                    qty = float(rng.choice(pool))
                rows.append({
                    "post_id": pid, "sku": sku, "date": dt,
                    "qty_consumed": qty,
                })
    return pd.DataFrame(rows)


def _build_warmup_weather(weather_df: pd.DataFrame,
                           rng: np.random.Generator) -> pd.DataFrame:
    """
    Build a synthetic 2021 warm-up-year weather frame (t_min_c only — the
    one field the stock layer's emergency-resupply weather gate needs) by
    month-matched resampling of the real weather distribution per post.

    Like the warm-up consumption, this is discarded after the stock
    dynamics run through it; it only has to be seasonally plausible so the
    warm-up year's emergency-resupply behaviour is not absurd.
    """
    wx = weather_df.copy()
    wx["date"] = pd.to_datetime(wx["date"])
    wx["month"] = wx["date"].dt.month

    pools: Dict[Tuple[str, int], np.ndarray] = {}
    for (pid, mth), grp in wx.groupby(["post_id", "month"]):
        pools[(pid, mth)] = grp["t_min_c"].to_numpy()

    warmup_start = date(WARMUP_YEAR, 1, 1)
    warmup_end = date(WARMUP_YEAR, 12, 31)
    warmup_days = (warmup_end - warmup_start).days + 1

    rows = []
    for pid in wx["post_id"].unique():
        for d in range(warmup_days):
            dt = warmup_start + timedelta(days=d)
            pool = pools.get((pid, dt.month))
            tmin = float(rng.choice(pool)) if pool is not None and len(pool) else 0.0
            rows.append({"post_id": pid, "date": dt, "t_min_c": tmin})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# AWS plan: how much each post pre-positions before each winter
# ---------------------------------------------------------------------------

def _max_isolation_window(iso_series: pd.Series) -> int:
    """Longest consecutive run of isolated days in a boolean series."""
    longest = cur = 0
    for v in iso_series:
        if v:
            cur += 1
            longest = max(longest, cur)
        else:
            cur = 0
    return longest


def build_aws_plan(world: World,
                    full_consumption_df: pd.DataFrame,
                    pass_status_df: pd.DataFrame,
                    winter_years: List[int],
                    rng: np.random.Generator) -> pd.DataFrame:
    """
    For each (post, SKU, winter_year), compute the AWS pre-positioning
    target.

    The target is sized off the POST'S ACTUAL TOPOLOGY, not an abstract
    doctrine number. A post's logistics staff plan AWS to outlast being
    cut off, so the target is:

        aws_target_qty = planning_days
                         * winter_rate_p80
                         * tier_safety_multiplier
                         * attainment_fraction

    where `planning_days` is the post's longest observed consecutive
    isolation run (derived from the pass-status data) plus a margin,
    floored at a tier-dependent minimum. This makes the target naturally
    responsive: a Chushul post cut off for 120 days gets a deeper buffer
    than a Pangong post cut off for 40, with no per-post hand-tuning.

    Rates:
      - winter_rate_p80  : planning rate — the post stocks for a winter
                           worse than 80% of winters (winter consumption
                           is right-skewed by cold-coupling + tempo).
      - winter_rate_mean : carried for the downstream days-of-cover metric
                           (cover should reflect expected, not worst-case,
                           burn).

    `attainment_fraction` (Beta, mean ~0.93) is what makes ~10-15% of
    post-SKUs enter winter genuinely short — the stockout-risk signal the
    forecaster has to learn. POL gets a mild extra attainment drag (bulk
    volume is hard to pre-position).
    """
    cons = full_consumption_df.copy()
    cons["date"] = pd.to_datetime(cons["date"])
    cons["month"] = cons["date"].dt.month
    winter_mask = cons["month"].isin([10, 11, 12, 1, 2, 3, 4])

    winter_rate_p80 = (cons[winter_mask]
                       .groupby(["post_id", "sku"])["qty_consumed"]
                       .quantile(0.80)
                       .to_dict())
    winter_rate_mean = (cons[winter_mask]
                        .groupby(["post_id", "sku"])["qty_consumed"]
                        .mean()
                        .to_dict())

    posts = world.posts.set_index("id")
    skus = world.skus.set_index("sku")

    # Per-post longest isolation run, from the pass-status data. This is
    # the planning horizon AWS must outlast.
    iso_df = compute_isolation_per_post_day(world, pass_status_df)
    iso_df["date"] = pd.to_datetime(iso_df["date"])
    iso_df = iso_df.sort_values(["post_id", "date"])
    max_iso_window = (iso_df.groupby("post_id")["is_isolated"]
                      .apply(_max_isolation_window)
                      .to_dict())

    raw_mean = AWS_ATTAINMENT_BETA_A / (AWS_ATTAINMENT_BETA_A + AWS_ATTAINMENT_BETA_B)
    ammo_tempo_raw_mean = AWS_AMMO_TEMPO_BETA_A / (
        AWS_AMMO_TEMPO_BETA_A + AWS_AMMO_TEMPO_BETA_B)

    rows = []
    for pid, post in posts.iterrows():
        post_max_iso = int(max_iso_window.get(pid, 0))
        for sku_id, sku in skus.iterrows():
            tier = int(sku["tier"])
            head = sku["head"]
            shelf = int(sku["shelf_life_days"])

            # The post's TRUE isolation exposure (longest-ever run) is the
            # anchor — but the post does not plan against a god's-eye
            # all-time max. It plans against a noisy estimate of it, and
            # that estimate is redrawn every winter (see below).
            base_planning_days = max(
                post_max_iso + AWS_ISOLATION_PLANNING_MARGIN_DAYS,
                AWS_TIER_MIN_PLANNING_DAYS[tier],
            )
            tier_mult = AWS_TIER_SAFETY_MULT[tier]
            is_perishable_sku = shelf <= AWS_PERISHABLE_SHELF_LIFE_CUTOFF_DAYS
            is_ammo = head in AWS_AMMO_TEMPO_MISESTIMATE_HEADS

            for wy in winter_years:
                # --- Per-winter planning horizon (decorrelates winters) ---
                # The post plans off recent, imperfect experience: a noisy
                # estimate of its isolation exposure plus a margin that is
                # itself a judgement call. Some winters it over-plans, some
                # it under-plans. THIS is what makes a stockout a function
                # of (this winter's severity) vs (this winter's plan).
                horizon_noise = rng.normal(1.0, AWS_PLANNING_HORIZON_NOISE_FRAC)
                horizon_noise = float(np.clip(horizon_noise, 0.55, 1.45))
                margin_jitter = rng.integers(-AWS_PLANNING_MARGIN_NOISE_DAYS,
                                             AWS_PLANNING_MARGIN_NOISE_DAYS + 1)
                planning_days = base_planning_days * horizon_noise + margin_jitter
                planning_days = max(
                    AWS_TIER_MIN_PLANNING_DAYS[tier] * 0.6,
                    planning_days,
                )
                # Perishables cannot be deep-stocked regardless — they spoil.
                if is_perishable_sku:
                    planning_days = min(planning_days,
                                        AWS_PERISHABLE_MAX_COVERAGE_DAYS)
                planning_days = round(float(planning_days), 1)

                # --- Attainment draw (per winter) ---
                raw = rng.beta(AWS_ATTAINMENT_BETA_A, AWS_ATTAINMENT_BETA_B)
                attain = raw + (AWS_ATTAINMENT_MEAN_TARGET - raw_mean)
                if head in AWS_HARD_TO_STOCK_HEADS:
                    attain *= AWS_HARD_TO_STOCK_PENALTY
                    # POL gets a floor BELOW the global floor — bulk fuel
                    # is the SKU most likely to enter winter genuinely
                    # short, which is exactly the signal the FSP needs.
                    attain = float(np.clip(attain, AWS_POL_ATTAINMENT_MIN,
                                           AWS_ATTAINMENT_MAX))
                else:
                    attain = float(np.clip(attain, AWS_ATTAINMENT_MIN,
                                           AWS_ATTAINMENT_MAX))

                # --- Ammo tempo misestimate (per winter, episodic) ---
                # A brigade cannot perfectly forecast next winter's tempo.
                # Most winters the pre-positioned ammo is sized about
                # right; occasionally a hot winter the staff did not see
                # coming leaves ammo (sized off a normal-tempo forecast)
                # short. Episodic, a minority of post-winters — not a wall.
                tempo_factor = 1.0
                if is_ammo:
                    t_raw = rng.beta(AWS_AMMO_TEMPO_BETA_A, AWS_AMMO_TEMPO_BETA_B)
                    tempo_factor = t_raw + (
                        AWS_AMMO_TEMPO_MISESTIMATE_MEAN - ammo_tempo_raw_mean)
                    tempo_factor = float(np.clip(
                        tempo_factor,
                        AWS_AMMO_TEMPO_MISESTIMATE_MIN,
                        AWS_AMMO_TEMPO_MISESTIMATE_MAX))

                rate_p80 = winter_rate_p80.get((pid, sku_id), 0.0)
                rate_mean = winter_rate_mean.get((pid, sku_id), 0.0)
                aws_target_qty = (planning_days * rate_p80 * tier_mult
                                  * attain * tempo_factor)

                rows.append({
                    "post_id": pid,
                    "sku": sku_id,
                    "winter_year": wy,
                    "post_max_isolation_run_days": post_max_iso,
                    "planning_days": planning_days,
                    "tier_safety_mult": tier_mult,
                    "ammo_tempo_factor": round(tempo_factor, 4),
                    "winter_daily_rate_p80": round(rate_p80, 4),
                    "winter_daily_rate_mean": round(rate_mean, 4),
                    "attainment_fraction": round(attain, 4),
                    "aws_target_qty": round(aws_target_qty, 2),
                })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Forward stock simulation
# ---------------------------------------------------------------------------

def _is_perishable(shelf_life_days: int) -> bool:
    return shelf_life_days <= SPOILAGE_SHELF_LIFE_PERISHABLE_CUTOFF


def _simulate_perishables(
        world: World,
        full_consumption_df: pd.DataFrame,
        pass_status_df: pd.DataFrame,
        weather_df: pd.DataFrame,
        aws_plan_df: pd.DataFrame,
        all_dates: List[date],
        rng: np.random.Generator,
) -> Tuple[List[dict], Dict[Tuple[str, str, date], float]]:
    """
    Authoritative simulator for PERISHABLE SKU series.

    Perishables (7-day-shelf fresh meat) need different receipt and demand
    physics than boxed stores, and the displaced demand has to be written
    onto a DIFFERENT (substitute) series — neither of which the main
    one-series-at-a-time loop can do. So perishables are simulated here in
    full, and the main loop skips them entirely and just appends these rows.

    Behavioural model (per the locked design decision: keep perishable
    shortfalls labelled `stockout`, but stop them being a deterministic
    98-day wall):

      1. Each perishable series runs a forward accounting identity with:
         - a small (~14-day-capped) AWS buffer,
         - daily spoilage,
         - routine perishable convoys whenever the post is REACHABLE
           (these top the series back toward its small buffer — note the
           main loop's convoy logic cannot serve perishables because their
           14-day planning horizon is below the convoy dispatch-gap
           threshold, which is exactly why perishables are simulated here),
         - intermittent, weather-gated emergency air-drops while ISOLATED,
           but only for posts that carry the `has_air_resupply` flag (just
           1 of 18 forward posts — most genuinely cannot get fresh rations
           during a long cutoff).
      2. Once a series has been at zero stock for PERISHABLE_GAP_GRACE_DAYS
         consecutive days, the post is treated as having ADAPTED — it stops
         drawing fresh meat it knows is not there. Effective demand decays
         multiplicatively toward a residual floor. The stockout event is
         therefore the SHORT depletion gap at the onset of an isolation
         run, not the whole run.
      3. The demand removed from the perishable is rate-converted into
         ADDED demand on the substitute SKU (tinned rations) — a real,
         learnable cross-SKU substitution signal.

    Returns:
      perishable_rows: ledger rows (same schema as the main loop) for the
        perishable SKUs, real + warm-up horizon (warm-up sliced later).
      demand_delta: {(post_id, sku, date) -> signed qty delta} — the
        POSITIVE half (substitute SKU absorbs displaced demand) is what the
        main loop consumes; the negative half is already baked into the
        perishable rows here.
    """
    perishable_rows: List[dict] = []
    demand_delta: Dict[Tuple[str, str, date], float] = {}
    if not PERISHABLE_SUBSTITUTION_ENABLED:
        return perishable_rows, demand_delta

    cons = full_consumption_df.copy()
    cons["date"] = pd.to_datetime(cons["date"]).dt.date
    cons_lookup = cons.set_index(["post_id", "sku", "date"])["qty_consumed"].to_dict()

    iso_df = compute_isolation_per_post_day(world, pass_status_df)
    iso_df["date"] = pd.to_datetime(iso_df["date"]).dt.date
    iso_lookup = iso_df.set_index(["post_id", "date"])["is_isolated"].to_dict()

    wx = weather_df.copy()
    wx["date"] = pd.to_datetime(wx["date"]).dt.date
    tmin_lookup = wx.set_index(["post_id", "date"])["t_min_c"].to_dict()

    posts = world.posts.set_index("id")
    skus = world.skus.set_index("sku")

    aws_lookup = aws_plan_df.set_index(
        ["post_id", "sku", "winter_year"])["aws_target_qty"].to_dict()
    rate_lookup = aws_plan_df.set_index(
        ["post_id", "sku", "winter_year"])["winter_daily_rate_mean"].to_dict()

    # Only the SKUs that are both perishable AND have a substitute mapping.
    perishable_skus = [s for s in PERISHABLE_SUBSTITUTE_MAP
                       if s in skus.index
                       and _is_perishable(int(skus.loc[s, "shelf_life_days"]))]

    for pid, post in posts.iterrows():
        has_air = bool(post.get("has_air_resupply", False))
        for sku_id in perishable_skus:
            sub_id = PERISHABLE_SUBSTITUTE_MAP[sku_id]
            tier = int(skus.loc[sku_id, "tier"])
            # base-rate ratio: how much substitute replaces one unit of
            # the perishable (calorie/quantity-sensible conversion).
            base_per = float(skus.loc[sku_id, "base_per_soldier_day"])
            base_sub = float(skus.loc[sub_id, "base_per_soldier_day"]) \
                if sub_id in skus.index else base_per
            sub_ratio = (base_sub / base_per) if base_per > 0 else 1.0

            first_wy = all_dates[0].year
            stock = WARMUP_SEED_COVERAGE_FRACTION * aws_lookup.get(
                (pid, sku_id, first_wy), 0.0)
            if stock <= 0:
                stock = 1.0
            zero_run = 0  # consecutive days at zero stock

            for dt in all_dates:
                opening = stock
                is_iso = iso_lookup.get((pid, dt), False)
                nominal = cons_lookup.get((pid, sku_id, dt), 0.0)
                rate = rate_lookup.get((pid, sku_id, dt.year), 0.0)
                if rate <= 0:
                    rate = max(nominal, 1e-6)

                # Effective demand: if the post has ADAPTED (zero stock for
                # more than the grace period), it stops drawing fresh meat.
                if zero_run > PERISHABLE_GAP_GRACE_DAYS:
                    decay_steps = zero_run - PERISHABLE_GAP_GRACE_DAYS
                    factor = max(
                        PERISHABLE_DEMAND_RESIDUAL_FLOOR,
                        (1.0 - PERISHABLE_DEMAND_DECAY_RATE) ** decay_steps,
                    )
                    effective = nominal * factor
                else:
                    effective = nominal

                # --- Receipts ---
                # routine perishable convoy when reachable; emergency
                # air-drop when isolated (air-resupply posts only).
                routine_rx = 0.0
                aws_rx = 0.0
                if not is_iso:
                    target_qty = AWS_PERISHABLE_MAX_COVERAGE_DAYS * rate
                    if stock < target_qty:
                        routine_rx = target_qty - stock
                elif EMERGENCY_PERISHABLE_RESUPPLY_ENABLED and has_air:
                    tmin = tmin_lookup.get((pid, dt), 0.0)
                    weather_ok = tmin > EMERGENCY_PERISHABLE_WEATHER_BLOCK_TMIN_C
                    if weather_ok and rng.random() < EMERGENCY_PERISHABLE_DISPATCH_PROB:
                        routine_rx = EMERGENCY_PERISHABLE_REFILL_COVERAGE_DAYS * rate

                spoil = opening * SPOILAGE_DAILY_FRACTION_PERISHABLE
                available = opening + routine_rx - spoil
                if available >= effective:
                    closing = available - effective
                    unmet = 0.0
                else:
                    closing = 0.0
                    unmet = effective - available

                # zero-run tracking for the adaptation logic
                if closing <= 1e-6:
                    zero_run += 1
                else:
                    zero_run = 0

                doc = closing / rate if rate > 0 else 0.0
                ration_thresh = STOCKOUT_RATIONING_THRESHOLD_DAYS[tier]
                if unmet > 0 or closing <= 0:
                    status = "stockout"
                elif doc < ration_thresh:
                    status = "rationing"
                else:
                    status = "ok"

                # Demand delta: the suppressed quantity is absorbed
                # (rate-converted) by the substitute SKU. Only the POSITIVE
                # half is exported — the perishable's own reduced demand is
                # already reflected in `consumption` on its ledger row.
                suppressed = nominal - effective
                if suppressed > 1e-9:
                    demand_delta[(pid, sub_id, dt)] = \
                        demand_delta.get((pid, sub_id, dt), 0.0) \
                        + suppressed * sub_ratio

                perishable_rows.append({
                    "post_id": pid,
                    "sku": sku_id,
                    "date": dt,
                    "opening_stock": round(opening, 3),
                    "aws_receipt": round(aws_rx, 3),
                    "routine_receipt": round(routine_rx, 3),
                    "nominal_consumption": round(nominal, 3),
                    "consumption": round(effective, 3),
                    "spoilage": round(spoil, 3),
                    "unmet_demand": round(unmet, 3),
                    "closing_stock": round(closing, 3),
                    "days_of_cover": round(doc, 2),
                    "status": status,
                })

                stock = closing

    return perishable_rows, demand_delta


def simulate_stock(world: World,
                    full_consumption_df: pd.DataFrame,
                    pass_status_df: pd.DataFrame,
                    weather_df: pd.DataFrame,
                    aws_plan_df: pd.DataFrame,
                    sim_start: date,
                    sim_end: date,
                    rng: np.random.Generator) -> pd.DataFrame:
    """
    Run the forward accounting identity day by day across the whole
    horizon (warm-up year included), per (post, SKU).

    Receipts:
      - AWS receipts: push-to-target across the road-open season (May-Sep
        + an October catch-up tail), delivered only on days the post is
        reachable; a bad-route summer therefore yields a thin winter
        buffer because the redistribution is over fewer open days.
      - Routine receipts: anticipatory convoy top-ups toward the post's
        topology-sized planning horizon whenever the post is reachable,
        throttled to a sane cadence. POL (bulk fuel) runs on a slower
        cadence with a capped per-convoy volume — it cannot be trickled
        in as freely as boxed stores.

    Perishable demand substitution: before the main loop, a pre-pass
    (`_compute_perishable_demand_adjustment`) simulates perishable series,
    finds isolation-driven gaps, and returns a demand-delta dictionary.
    Once a post has adapted to a fresh-meat gap it stops drawing fresh
    meat (demand decays toward a residual floor) and the displaced demand
    is absorbed by the substitute SKU (tinned rations). The main loop
    applies these deltas on top of nominal consumption.

    Spoilage: perishable SKUs lose SPOILAGE_DAILY_FRACTION_PERISHABLE of
    opening stock each day.
    """
    cons = full_consumption_df.copy()
    cons["date"] = pd.to_datetime(cons["date"]).dt.date
    cons_lookup = cons.set_index(["post_id", "sku", "date"])["qty_consumed"].to_dict()

    sim_days = (sim_end - sim_start).days + 1
    all_dates = [sim_start + timedelta(days=i) for i in range(sim_days)]

    # --- Perishable simulation pass ---
    # Perishables (fresh meat) need different receipt/demand physics and
    # write displaced demand onto a SUBSTITUTE series, neither of which the
    # main one-series-at-a-time loop can do. They are simulated in full
    # here; the main loop skips perishable SKUs and just appends these rows.
    #   perishable_rows : finished ledger rows for perishable SKUs
    #   demand_delta    : {(post, substitute_sku, date) -> +qty} the main
    #                     loop adds onto the substitute SKU's nominal demand
    perishable_rows, demand_delta = _simulate_perishables(
        world, full_consumption_df, pass_status_df, weather_df,
        aws_plan_df, all_dates, rng)
    perishable_sku_set = set(PERISHABLE_SUBSTITUTE_MAP.keys())

    # Isolation per (post, date) — reuse the consumption module's logic so
    # stock and consumption see the SAME isolation truth.
    iso_df = compute_isolation_per_post_day(world, pass_status_df)
    iso_df["date"] = pd.to_datetime(iso_df["date"]).dt.date
    iso_lookup = iso_df.set_index(["post_id", "date"])["is_isolated"].to_dict()

    posts = world.posts.set_index("id")
    skus = world.skus.set_index("sku")

    # AWS plan lookup: (post_id, sku, winter_year) -> aws_target_qty
    aws_lookup = aws_plan_df.set_index(
        ["post_id", "sku", "winter_year"])["aws_target_qty"].to_dict()
    # Winter daily rate lookup — MEAN rate, used for days-of-cover and
    # routine refill sizing (days-of-cover should reflect expected burn,
    # not the worst-case P80 the AWS target was sized against).
    rate_lookup = aws_plan_df.set_index(
        ["post_id", "sku", "winter_year"])["winter_daily_rate_mean"].to_dict()
    # Planning-days lookup: the topology-sized horizon for this (post, SKU).
    # Routine convoys refill toward THIS, not a flat 75 days — so a deeply
    # isolated post is kept topped up to a deeper buffer between the big
    # AWS pushes, consistent with how it was provisioned in the first place.
    planning_lookup = aws_plan_df.set_index(
        ["post_id", "sku", "winter_year"])["planning_days"].to_dict()

    # AWS delivery model: PUSH-TO-TARGET, not fixed installments.
    #
    # The Army's AWS is a push toward a stocking target across the
    # road-open season — if convoys can't run one week, they run heavier
    # the next. Modelling it as fixed daily installments that evaporate
    # when a post is isolated is wrong: it permanently writes off winter
    # stock for any post that loses its route mid-summer, which is not how
    # the doctrine works.
    #
    # Instead: on each AWS-season day the post is NOT isolated, deliver
    #   remaining_target / max(estimated_remaining_open_days, 1)
    # so missed days are absorbed by heavier delivery on the open days.
    # A late catch-up tail (first 10 days of October) is permitted if the
    # post is still short — the very end of the road-open window.
    #
    # We pre-compute, per (post, calendar-year), the set of AWS-delivery
    # candidate days (May-Sep + Oct 1-10) and the running count.
    iso_by_post_date = iso_lookup  # (post_id, date) -> bool

    def aws_candidate_days(pid: str, year: int) -> List[date]:
        days = []
        for m in AWS_SEASON_MONTHS:
            for dd in range(1, _days_in_month(year, m) + 1):
                days.append(date(year, m, dd))
        # October catch-up tail
        for dd in range(1, 11):
            days.append(date(year, 10, dd))
        return days

    rows = []
    for pid, post in posts.iterrows():
        for sku_id, sku in skus.iterrows():
            # Perishable SKUs are simulated authoritatively by
            # _simulate_perishables (different receipt/demand physics);
            # skip them here and append their rows after the main loop.
            if sku_id in perishable_sku_set:
                continue
            shelf = int(sku["shelf_life_days"])
            tier = int(sku["tier"])
            perishable = _is_perishable(shelf)

            # --- Opening seed at the very start of the warm-up year ---
            # Seed at the warm-up coverage fraction of the first winter's
            # AWS target. Washed out by the time the warm-up is discarded.
            first_wy = sim_start.year
            seed_target = aws_lookup.get((pid, sku_id, first_wy), 0.0)
            stock = WARMUP_SEED_COVERAGE_FRACTION * seed_target
            if stock <= 0:
                stock = 1.0

            # Pre-compute AWS delivery candidate days per year, and track
            # how much of each year's target remains to be delivered.
            years_in_sim = sorted({d.year for d in all_dates})
            aws_remaining: Dict[int, float] = {}
            aws_candidates: Dict[int, List[date]] = {}
            aws_open_remaining: Dict[int, int] = {}
            for yr in years_in_sim:
                tgt = aws_lookup.get((pid, sku_id, yr), 0.0)
                aws_remaining[yr] = max(0.0, tgt)
                cand = aws_candidate_days(pid, yr)
                aws_candidates[yr] = cand
                # estimate of open candidate days (we'll decrement as we go)
                aws_open_remaining[yr] = sum(
                    1 for d in cand if not iso_by_post_date.get((pid, d), False))

            # Pending routine-convoy deliveries: list of (arrival_date, qty)
            pending: List[Tuple[date, float]] = []
            # Last routine-convoy dispatch date — throttles convoy cadence.
            last_convoy_date: date | None = None

            for dt in all_dates:
                opening = stock
                is_iso = iso_lookup.get((pid, dt), False)

                # --- AWS receipt: push-to-target on open candidate days ---
                aws_rx = 0.0
                yr = dt.year
                is_aws_candidate = (
                    dt.month in AWS_SEASON_MONTHS
                    or (dt.month == 10 and dt.day <= 10)
                )
                if is_aws_candidate and aws_remaining.get(yr, 0.0) > 0:
                    if not is_iso:
                        open_rem = max(aws_open_remaining.get(yr, 1), 1)
                        aws_rx = aws_remaining[yr] / open_rem
                        aws_rx = min(aws_rx, aws_remaining[yr])
                        aws_remaining[yr] -= aws_rx
                        aws_open_remaining[yr] = max(0, aws_open_remaining[yr] - 1)
                    # if isolated on a candidate day, that day is simply
                    # not an open day — the remaining target redistributes
                    # over the open days that are left (open_rem already
                    # excluded it in the pre-count).

                # --- Routine convoy arrivals scheduled for today ---
                routine_rx = 0.0
                still_pending = []
                for arr_date, qty in pending:
                    if arr_date == dt:
                        routine_rx += qty
                    elif arr_date > dt:
                        still_pending.append((arr_date, qty))
                pending = still_pending

                # --- Consumption (from the consumption module) ---
                # nominal: the raw draw from the consumption module.
                # consumed: nominal + perishable-substitution delta. For a
                # perishable SKU mid-gap the delta is negative (the post
                # adapted, stopped drawing fresh meat); for a substitute
                # SKU it is positive (tinned rations absorb the displaced
                # demand). Both are recorded so the substitution is visible
                # in the ledger lineage.
                nominal = cons_lookup.get((pid, sku_id, dt), 0.0)
                delta = demand_delta.get((pid, sku_id, dt), 0.0)
                consumed = max(0.0, nominal + delta)

                # --- Spoilage (perishables only, on opening stock) ---
                spoil = 0.0
                if perishable:
                    spoil = opening * SPOILAGE_DAILY_FRACTION_PERISHABLE

                # --- Balance ---
                available = opening + aws_rx + routine_rx - spoil
                if available >= consumed:
                    closing = available - consumed
                    unmet = 0.0
                else:
                    closing = 0.0
                    unmet = consumed - available

                # --- Days of cover (forward-looking, uses winter rate) ---
                rate = rate_lookup.get((pid, sku_id, dt.year), 0.0)
                if rate <= 0:
                    rate = max(consumed, 1e-6)
                doc = closing / rate if rate > 0 else 0.0

                # --- Status classification ---
                ration_thresh = STOCKOUT_RATIONING_THRESHOLD_DAYS[tier]
                if unmet > 0 or closing <= 0:
                    status = "stockout"
                elif doc < ration_thresh:
                    status = "rationing"
                else:
                    status = "ok"

                # --- Routine convoy dispatch decision ---
                # ANTICIPATORY top-up, not emergency-triggered. Whenever a
                # post is reachable (passes open) and its cover sits below
                # its topology-sized planning horizon, a convoy tops it up.
                # This mirrors real road-open-season logistics: every time
                # a convoy CAN run to a post, it does — you don't wait for
                # a near-stockout to reorder when you know the route will
                # close. A post bleeds down only when it is genuinely cut
                # off; the moment it is reachable again it is refilled.
                #
                # Convoy cadence is throttled so a post is not topped up
                # every single day — a convoy is dispatched at most once
                # per ROUTINE_CONVOY_MIN_GAP_DAYS, and only if cover is
                # below the planning horizon by a meaningful margin.
                plan_days = planning_lookup.get(
                    (pid, sku_id, dt.year),
                    ROUTINE_RECEIPT_REFILL_TO_COVERAGE_DAYS,
                )
                # POL (bulk fuel) runs on a slower convoy cadence and a
                # capped per-run volume — a tanker run, not a general-
                # stores top-up. This is what lets a forward post that
                # entered winter short on kerosene STAY short: routine
                # convoys cannot fully rescue it mid-season.
                is_pol = str(sku_id).startswith("POL")
                min_gap = POL_CONVOY_MIN_GAP_DAYS if is_pol else ROUTINE_CONVOY_MIN_GAP_DAYS
                days_since_last = (dt - last_convoy_date).days if last_convoy_date else 9999
                cover_gap = plan_days - doc
                if (not is_iso
                        and len(pending) == 0
                        and rate > 0
                        and days_since_last >= min_gap
                        and cover_gap > ROUTINE_CONVOY_DISPATCH_GAP_DAYS):
                    # Refill toward the planning horizon — but for POL,
                    # one convoy carries at most POL_CONVOY_MAX_REFILL
                    # coverage-days of fuel, so deep gaps take multiple
                    # slow convoys to close.
                    refill_qty = max(0.0, (plan_days * rate) - closing)
                    if is_pol:
                        refill_qty = min(refill_qty,
                                         POL_CONVOY_MAX_REFILL_COVERAGE_DAYS * rate)
                    if refill_qty > 0:
                        lat = int(rng.integers(ROUTINE_RECEIPT_CONVOY_LATENCY_DAYS[0],
                                               ROUTINE_RECEIPT_CONVOY_LATENCY_DAYS[1] + 1))
                        pending.append((dt + timedelta(days=lat), refill_qty))
                        last_convoy_date = dt

                rows.append({
                    "post_id": pid,
                    "sku": sku_id,
                    "date": dt,
                    "opening_stock": round(opening, 3),
                    "aws_receipt": round(aws_rx, 3),
                    "routine_receipt": round(routine_rx, 3),
                    "nominal_consumption": round(nominal, 3),
                    "consumption": round(consumed, 3),
                    "spoilage": round(spoil, 3),
                    "unmet_demand": round(unmet, 3),
                    "closing_stock": round(closing, 3),
                    "days_of_cover": round(doc, 2),
                    "status": status,
                })

                stock = closing

    # Combine non-perishable rows (main loop) with perishable rows
    # (authoritative _simulate_perishables pass).
    rows.extend(perishable_rows)
    return pd.DataFrame(rows)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    return (nxt - date(year, month, 1)).days


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------

def generate_stock(world: World,
                    consumption_df: pd.DataFrame,
                    pass_status_df: pd.DataFrame,
                    weather_df: pd.DataFrame,
                    seed: int = 42) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Returns:
      stock_df:   the real-horizon (warm-up discarded) stock ledger
      aws_plan_df: the AWS plan lineage record (real winters only)

    Pipeline:
      1. Build a warm-up-year (2021) consumption frame by month-matched
         resampling of the real consumption distribution, and a matching
         warm-up weather frame (needed for the emergency-resupply weather
         gate during the warm-up year).
      2. Build the AWS plan for all winters incl. warm-up.
      3. Run the forward stock simulation across [warm-up start, real end].
      4. Slice off the warm-up year and return only the real horizon.
    """
    rng = np.random.default_rng(seed + 7)  # offset so we don't reuse consumption's stream

    # 1. Warm-up consumption + warm-up weather
    warmup_cons = build_warmup_consumption(consumption_df, rng)
    warmup_wx = _build_warmup_weather(weather_df, rng)

    # Stitch warm-up + real consumption into one continuous frame
    cons_real = consumption_df[["post_id", "sku", "date", "qty_consumed"]].copy()
    cons_real["date"] = pd.to_datetime(cons_real["date"]).dt.date
    warmup_cons["date"] = pd.to_datetime(warmup_cons["date"]).dt.date
    full_cons = pd.concat([warmup_cons, cons_real], ignore_index=True)

    # Stitch warm-up + real weather (only the columns the stock layer needs)
    wx_real = weather_df[["post_id", "date", "t_min_c"]].copy()
    wx_real["date"] = pd.to_datetime(wx_real["date"]).dt.date
    warmup_wx["date"] = pd.to_datetime(warmup_wx["date"]).dt.date
    full_wx = pd.concat([warmup_wx, wx_real], ignore_index=True)

    # 2. AWS plan: winters covered are the warm-up year + every real year
    real_years = sorted({d.year for d in
                         pd.to_datetime(cons_real["date"]).tolist()
                         if isinstance(d, (date,))} |
                        set(pd.to_datetime(consumption_df["date"]).dt.year.unique()))
    winter_years = [WARMUP_YEAR] + [y for y in real_years if y != WARMUP_YEAR]
    winter_years = sorted(set(winter_years))
    aws_plan_df = build_aws_plan(world, full_cons, pass_status_df,
                                 winter_years, rng)

    # 3. Forward simulation across warm-up start -> real end
    sim_start = date(WARMUP_YEAR, 1, 1)
    sim_end = END_DATE
    stock_full = simulate_stock(world, full_cons, pass_status_df, full_wx,
                                aws_plan_df, sim_start, sim_end, rng)

    # 4. Discard the warm-up year
    stock_full["date"] = pd.to_datetime(stock_full["date"])
    stock_df = stock_full[stock_full["date"].dt.year != WARMUP_YEAR].copy()
    stock_df["date"] = stock_df["date"].dt.date
    stock_df = stock_df.reset_index(drop=True)

    # AWS plan: return only the real winters (warm-up plan was internal)
    aws_plan_df = aws_plan_df[aws_plan_df["winter_year"] != WARMUP_YEAR].reset_index(drop=True)

    return stock_df, aws_plan_df


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_stock(stock_df: pd.DataFrame, aws_plan_df: pd.DataFrame,
                    world: World) -> dict:
    """Sanity checks on the stock ledger against the locked design decisions."""
    df = stock_df.copy()
    df["date"] = pd.to_datetime(df["date"])

    posts = world.posts.set_index("id")
    skus = world.skus.set_index("sku")

    # --- Decision 1: ~85-90% of forward post-SKUs survive winter ---
    # Measure: fraction of (post, SKU, winter) that NEVER hit stockout
    # status during the Oct-Apr window.
    df["month"] = df["date"].dt.month
    df["winter_label"] = df["date"].apply(
        lambda d: d.year if d.month >= 10 else d.year - 1)
    winter_rows = df[df["month"].isin([10, 11, 12, 1, 2, 3, 4])].copy()

    forward_posts = posts[posts["band"] == "forward"].index.tolist()
    fwd = winter_rows[winter_rows["post_id"].isin(forward_posts)]
    grp = fwd.groupby(["post_id", "sku", "winter_label"])["status"]
    had_stockout = grp.apply(lambda s: (s == "stockout").any())
    survive_rate = 1.0 - had_stockout.mean() if len(had_stockout) else None

    # --- Decision 2: shortfalls concentrate in kerosene + perishables ---
    stockout_rows = df[df["status"] == "stockout"].copy()
    stockout_rows = stockout_rows.merge(
        skus[["head", "shelf_life_days"]], left_on="sku", right_index=True, how="left")
    if len(stockout_rows):
        head_share = (stockout_rows.groupby("head").size()
                      / len(stockout_rows)).round(3).to_dict()
        perishable_share = round(
            float((stockout_rows["shelf_life_days"]
                   <= SPOILAGE_SHELF_LIFE_PERISHABLE_CUTOFF).mean()), 3)
    else:
        head_share = {}
        perishable_share = 0.0

    pol_share = head_share.get("POL", 0.0)

    # --- AWS attainment distribution sanity ---
    attain_mean = round(float(aws_plan_df["attainment_fraction"].mean()), 3)
    attain_p10 = round(float(aws_plan_df["attainment_fraction"].quantile(0.10)), 3)
    attain_p90 = round(float(aws_plan_df["attainment_fraction"].quantile(0.90)), 3)

    # --- Sawtooth check: kerosene at a deep forward post ---
    # closing stock should peak ~Sep-Oct and trough ~Mar-Apr.
    ker = df[(df["sku"] == "POL-001") & (df["post_id"] == "P034")].copy()
    ker_monthly = ker.groupby(ker["date"].dt.month)["closing_stock"].mean()
    peak_month = int(ker_monthly.idxmax()) if len(ker_monthly) else None
    trough_month = int(ker_monthly.idxmin()) if len(ker_monthly) else None

    # --- Overall status mix ---
    status_mix = (df.groupby("status").size() / len(df)).round(4).to_dict()

    # --- Accounting identity check: opening + rx - cons - spoil == closing
    #     (within rounding) on a random sample ---
    sample = df.sample(min(5000, len(df)), random_state=1)
    identity_resid = (sample["opening_stock"] + sample["aws_receipt"]
                      + sample["routine_receipt"] - sample["consumption"]
                      - sample["spoilage"] - sample["closing_stock"]
                      + sample["unmet_demand"])
    max_resid = round(float(identity_resid.abs().max()), 4)

    return {
        "forward_postsku_winter_survival_rate": round(float(survive_rate), 3) if survive_rate is not None else None,
        "forward_survival_target": [0.85, 0.90],
        "stockout_head_share": head_share,
        "stockout_pol_share": pol_share,
        "stockout_perishable_share": perishable_share,
        "stockout_concentration_note": "Decision 2: shortfalls should concentrate in POL + perishables.",
        "aws_attainment_mean": attain_mean,
        "aws_attainment_mean_target": AWS_ATTAINMENT_MEAN_TARGET,
        "aws_attainment_p10_p90": [attain_p10, attain_p90],
        "kerosene_P034_stock_peak_month": peak_month,
        "kerosene_P034_stock_trough_month": trough_month,
        "sawtooth_note": "Expect peak ~9-10 (post-AWS), trough ~3-4 (pre-thaw).",
        "status_mix": status_mix,
        "accounting_identity_max_residual": max_resid,
        "rows": len(df),
    }


if __name__ == "__main__":
    from world import build_world
    from weather import generate_weather
    from disruption import generate_pass_closures
    from consumption import generate_consumption

    w = build_world(seed=42)
    wx, _ = generate_weather(w, seed=42)
    cl, status = generate_pass_closures(w, wx, seed=42)
    cons, tempo = generate_consumption(w, wx, status, seed=42)
    stock, aws = generate_stock(w, cons, status, wx, seed=42)
    print(f"Stock ledger rows: {len(stock):,}")
    print(f"AWS plan rows:     {len(aws):,}")
    print()
    v = validate_stock(stock, aws, w)
    for k, val in v.items():
        print(f"  {k}: {val}")
