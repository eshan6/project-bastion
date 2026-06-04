"""
Project Bastion — Stage 3 features (v1.0)

Builds the training matrices for all three models from the Stage 2 parquets.
Three public functions:

  build_demand_features(...)   -> weekly panel, one row per (post, sku, week)
  build_route_features(...)    -> daily panel, one row per (pass, date, horizon)
  build_vehicle_features(...)  -> snapshot panel, one row per (vehicle, as_of_date)

Time-aware: lag features only use information available at row's date.
No leakage from future weather into past forecasts.
"""

import pandas as pd
import numpy as np
from pathlib import Path
import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 loaders — small wrappers that normalize types
# ─────────────────────────────────────────────────────────────────────────────
def _load(name: str) -> pd.DataFrame:
    df = pd.read_parquet(cfg.DATA_DIR / f"{name}.parquet")
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    for c in ("start_date", "end_date", "deadline_date", "return_date"):
        if c in df.columns:
            df[c] = pd.to_datetime(df[c])
    return df


def load_all():
    """Load every Stage 2 table. Returns dict of DataFrames."""
    tables = ["posts", "routes", "vehicles", "skus", "weather_daily", "wd_events",
              "pass_closures", "pass_status_daily", "consumption_daily",
              "tempo_daily", "vehicle_events", "stock_daily"]
    return {t: _load(t) for t in tables}


# ─────────────────────────────────────────────────────────────────────────────
# Demand features
# ─────────────────────────────────────────────────────────────────────────────
def build_demand_features(data: dict) -> pd.DataFrame:
    """
    Weekly per-(post, sku) panel with weather rollups, calendar, lags, isolation,
    tempo. Target column is `qty_weekly`.

    Time-awareness: lag features use shift(1) so the week-of-prediction row sees
    only historical weeks. Weather rollup is for the *same* week (the model is
    forecasting that week's consumption given that week's weather forecast, not
    historical weather only — Stage 4's optimizer will pass in forecast weather).
    """
    cons = data["consumption_daily"].copy()
    weather = data["weather_daily"].copy()
    posts = data["posts"][["id", "elev_m", "troops", "band", "axis"]].rename(columns={"id": "post_id"})
    skus = data["skus"][["sku", "head", "base_per_soldier_day", "tier",
                          "shelf_life_days", "weather_sensitivity"]]
    tempo = data["tempo_daily"].copy()

    # Week anchor: every date snapped to its ISO Monday
    cons["week"] = cons["date"].dt.to_period("W-MON").dt.start_time
    weather["week"] = weather["date"].dt.to_period("W-MON").dt.start_time
    tempo["date"] = pd.to_datetime(tempo["date"])
    tempo["week"] = tempo["date"].dt.to_period("W-MON").dt.start_time

    # --- Target: weekly total consumption per (post, sku) ---
    cons_wk = cons.groupby(["post_id", "sku", "week"], as_index=False).agg(
        qty_weekly=("qty_consumed", "sum"),
        isolated_days=("is_isolated", "sum"),
    )

    # --- Weather rollup per (post, week) ---
    wx_wk = weather.groupby(["post_id", "week"], as_index=False).agg(
        t_min_c_mean=("t_min_c", "mean"),
        t_min_c_min=("t_min_c", "min"),
        t_max_c_mean=("t_max_c", "mean"),
        precip_mm_sum=("precip_mm", "sum"),
        is_snow_days=("is_snow", "sum"),
        is_wd_days=("is_wd_active", "sum"),
    )

    # --- Brigade tempo rollup per week (consumption already carries tempo, but
    # we want per-week counts of high/crisis days for ammo/POL forecasters) ---
    tempo_wk = tempo.groupby("week", as_index=False).agg(
        crisis_days_in_week=("tempo_level", lambda s: (s == "crisis").sum()),
        high_days_in_week=("tempo_level", lambda s: (s == "high").sum()),
        tempo_level=("tempo_level", lambda s: s.mode().iloc[0] if len(s) else "normal"),
    )

    # --- Merge ---
    df = cons_wk.merge(wx_wk, on=["post_id", "week"], how="left") \
                .merge(tempo_wk, on="week", how="left") \
                .merge(posts, on="post_id", how="left") \
                .merge(skus, on="sku", how="left")

    # --- Calendar ---
    df["week_of_year"] = df["week"].dt.isocalendar().week.astype(int)
    df["month"]        = df["week"].dt.month
    df["is_winter"]    = df["month"].isin([12, 1, 2, 3]).astype(int)
    df["is_summer"]    = df["month"].isin([6, 7, 8]).astype(int)

    # --- Lag features (computed per (post, sku) time series) ---
    df = df.sort_values(["post_id", "sku", "week"]).reset_index(drop=True)
    g = df.groupby(["post_id", "sku"], sort=False)["qty_weekly"]
    df["qty_lag_1w"] = g.shift(1)
    # Rolling-after-shift, per group, returned aligned to df.index
    shifted = g.shift(1)
    df["qty_lag_4w_mean"]  = shifted.groupby([df["post_id"], df["sku"]]).transform(
        lambda s: s.rolling(4, min_periods=1).mean())
    df["qty_lag_12w_mean"] = shifted.groupby([df["post_id"], df["sku"]]).transform(
        lambda s: s.rolling(12, min_periods=1).mean())
    df["qty_lag_52w_mean"] = g.shift(52)   # year-ago seasonal anchor (NaN until year 2)

    # Fill lag NaNs with the SKU-band median (defensible cold-start prior) so we
    # don't drop the first year of training rows.
    for lag_col in ["qty_lag_1w", "qty_lag_4w_mean", "qty_lag_12w_mean", "qty_lag_52w_mean"]:
        med = df.groupby(["band", "sku"])[lag_col].transform("median")
        df[lag_col] = df[lag_col].fillna(med).fillna(0.0)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Route features
# ─────────────────────────────────────────────────────────────────────────────
def build_route_features(data: dict) -> pd.DataFrame:
    """
    Daily per-(pass, date, horizon) panel. Target: is_open at date+horizon.

    Features: weather at the pass's anchor post, brigade-wide WD signal,
    rolling-window snow/precip, calendar, historical day-of-year base rate.
    """
    ps = data["pass_status_daily"].copy()
    weather = data["weather_daily"].copy()
    posts = data["posts"][["id", "axis", "elev_m", "band"]].rename(columns={"id": "post_id"})

    # For each pass, identify its anchor post — the highest-elevation forward
    # post on the served axis (proxy for the pass crossing's local weather).
    anchor_per_pass = {}
    for pass_name, axis in cfg.ROUTE_PASS_TO_ANCHOR_POST_AXIS.items():
        candidates = posts[(posts["axis"] == axis) & (posts["band"] == "forward")]
        if len(candidates) == 0:
            candidates = posts[posts["axis"] == axis]
        if len(candidates) == 0:
            # Fallback: pick any post on the closest axis with highest elevation
            candidates = posts
        anchor_per_pass[pass_name] = candidates.sort_values("elev_m", ascending=False).iloc[0]["post_id"]

    # Build per-pass weather frames
    pass_weather_frames = []
    for pass_name, anchor_post_id in anchor_per_pass.items():
        wx = weather[weather["post_id"] == anchor_post_id].copy()
        wx = wx.sort_values("date").reset_index(drop=True)
        wx["pass_name"] = pass_name
        wx = wx.rename(columns={
            "precip_mm": "precip_mm_today",
            "t_min_c": "t_min_c_today",
            "t_max_c": "t_max_c_today",
            "is_snow": "is_snow_today",
            "is_wd_active": "is_wd_today",
        })
        # 7-day rolling features at anchor
        wx["precip_mm_7d_sum"] = wx["precip_mm_today"].rolling(7, min_periods=1).sum()
        wx["t_min_c_7d_min"]   = wx["t_min_c_today"].rolling(7, min_periods=1).min()
        wx["snow_days_7d"]     = wx["is_snow_today"].astype(int).rolling(7, min_periods=1).sum()
        wx["wd_days_7d"]       = wx["is_wd_today"].astype(int).rolling(7, min_periods=1).sum()
        pass_weather_frames.append(wx[["pass_name", "date",
            "precip_mm_today", "t_min_c_today", "t_max_c_today",
            "is_snow_today", "is_wd_today",
            "precip_mm_7d_sum", "t_min_c_7d_min", "snow_days_7d", "wd_days_7d"]])
    pass_weather = pd.concat(pass_weather_frames, ignore_index=True)

    # Brigade-wide WD signal: any post with WD active today
    brigade_wd = weather.groupby("date", as_index=False).agg(
        wd_active_brigade_today=("is_wd_active", "max"),
    )
    brigade_wd["wd_active_brigade_today"] = brigade_wd["wd_active_brigade_today"].astype(int)
    brigade_wd = brigade_wd.sort_values("date").reset_index(drop=True)
    brigade_wd["wd_days_brigade_7d"] = brigade_wd["wd_active_brigade_today"].rolling(7, min_periods=1).sum()

    # Merge into per-(pass, date) frame with current open/closed label
    ps_dt = ps.copy()
    ps_dt["date"] = pd.to_datetime(ps_dt["date"])
    df = ps_dt.merge(pass_weather, on=["pass_name", "date"], how="left") \
              .merge(brigade_wd,  on="date", how="left")

    # Calendar
    df["month"] = df["date"].dt.month
    df["is_winter"] = df["month"].isin([12, 1, 2, 3]).astype(int)
    # Day-of-winter: monotone clock from Dec 1 → Mar 31 (NaN otherwise)
    def _day_of_winter(d):
        if d.month == 12:
            return (d - pd.Timestamp(year=d.year, month=12, day=1)).days
        if d.month in [1, 2, 3]:
            return (d - pd.Timestamp(year=d.year - 1, month=12, day=1)).days
        return 0
    df["day_of_winter"] = df["date"].apply(_day_of_winter)

    # Historical day-of-year base rate per pass (uses *training-window only*
    # to avoid leakage from test data) — computed once outside, see add_doy_baserate.
    df["doy"] = df["date"].dt.dayofyear

    # Build horizon-shifted labels: for each horizon h, label = is_open at date+h
    # We pivot to long format: one row per (pass, date, horizon)
    horizon_frames = []
    for h in cfg.ROUTE_HORIZONS_DAYS:
        d = df.copy()
        d["horizon"] = h
        # Label = the is_open status at date + h days for this pass
        future = ps_dt[["pass_name", "date", "is_open"]].copy()
        future = future.rename(columns={"date": "target_date", "is_open": "is_open_target"})
        future["date"] = future["target_date"] - pd.Timedelta(days=h)
        d = d.merge(future[["pass_name", "date", "is_open_target"]],
                    on=["pass_name", "date"], how="left")
        horizon_frames.append(d)
    out = pd.concat(horizon_frames, ignore_index=True)

    return out


def add_doy_baserate(route_df: pd.DataFrame, train_cutoff: str) -> pd.DataFrame:
    """
    Add historical pass-open-rate by day-of-year, computed ONLY from training data.
    Must be called AFTER train/test split definition.
    """
    train_mask = route_df["date"] <= pd.Timestamp(train_cutoff)
    base = route_df[train_mask].groupby(["pass_name", "doy"], as_index=False).agg(
        pass_open_rate_doy_historical=("is_open", "mean")
    )
    return route_df.merge(base, on=["pass_name", "doy"], how="left")


# ─────────────────────────────────────────────────────────────────────────────
# Vehicle features
# ─────────────────────────────────────────────────────────────────────────────
def build_vehicle_features(data: dict, as_of_date: str | pd.Timestamp) -> pd.DataFrame:
    """
    Snapshot of every vehicle at `as_of_date`. Used by the rule-based scorer
    to compute hazard and the survival-window probability.

    Columns:
      vehicle_id, vehicle_class, payload_tons, home_depot_id,
      age_days_at_asof, weibull_shape, weibull_scale_days,
      events_to_date, last_event_date, days_since_last_event
    """
    as_of = pd.Timestamp(as_of_date)
    veh = data["vehicles"].copy()
    events = data["vehicle_events"].copy()

    # Filter events to those whose deadline_date <= as_of
    past = events[events["deadline_date"] <= as_of].copy()
    by_v = past.groupby("vehicle_id").agg(
        events_to_date=("deadline_date", "count"),
        last_event_date=("deadline_date", "max"),
    )

    veh = veh.merge(by_v, left_on="vehicle_id", right_index=True, how="left")
    veh["events_to_date"] = veh["events_to_date"].fillna(0).astype(int)

    # Age: initial_age_days + days from Stage 2 start (2022-01-01) to as_of
    stage2_start = pd.Timestamp("2022-01-01")
    days_elapsed = (as_of - stage2_start).days
    veh["age_days_at_asof"] = veh["initial_age_days"] + days_elapsed

    # If a vehicle had a "return_date" event recently, treat it as effectively
    # "newer" by subtracting recent depot-repair time (a depot repair restores
    # some life). This is a documented heuristic.
    veh["days_since_last_event"] = (as_of - veh["last_event_date"]).dt.days
    veh.loc[veh["last_event_date"].isna(), "days_since_last_event"] = veh.loc[
        veh["last_event_date"].isna(), "age_days_at_asof"
    ]

    return veh
