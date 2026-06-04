"""
Project Bastion — Stage 3 vehicle reliability scorer (v1.0)

Decision 3 (locked): Rule-based scorer, no ML training.

Rationale
─────────
Stage 2 ships each vehicle with Weibull(shape, scale) parameters from
CAG-anchored class priors. The deadline-event process IS the Weibull, with
optional repair cycles. Training a survival forest on the resulting events
would just be learning what the generator already encodes — circular.

A documented analytic scorer is more honest in the synthetic-data setting:
we evaluate the survival function with the same parameters the generator used
to produce the events, plus a small altitude-exposure adjustment.

The scorer still emits `Vehicle.reliability_score` as an ontology row, so the
Stage 4 optimizer's interface is unchanged. The lineage is intact: every score
is tagged with model_version, the rule's coefficients, and the date snapshot.

Outputs P(deadline within next H days | survived age t):
    H(t)        = (t / scale)^shape                  cumulative hazard
    P(survive ≥ t+Δ | survive ≥ t) = exp(H(t) − H(t+Δ))
    P(deadline within Δ)           = 1 − that

Altitude adjustment: vehicles assigned to forward axes are assumed to spend
~50% of days above 4500m. Scaling hazard by (1 + α·frac_high_altitude) where
α is documented in config.py.
"""

import json
import pickle
import pandas as pd
import numpy as np
from pathlib import Path
import config as cfg


# Axis → assumed fraction of days above 4500m for a vehicle home-depoted to
# a depot that primarily serves that axis. SYNTHETIC-INFERRED — placeholder
# until real fleet utilization data is available.
AXIS_ALTITUDE_EXPOSURE = {
    "Pangong":     0.35,
    "DBO":         0.65,
    "Chushul":     0.45,
    "Demchok":     0.50,
    "Hot_Springs": 0.55,
    "Rear":        0.05,
}


def _depot_axis_map(posts: pd.DataFrame) -> dict:
    """Map each depot_id to the modal axis it serves (excluding 'Rear')."""
    # Group non-depot posts by their serving_depot_id, pick modal axis
    non_depots = posts[~posts["is_depot"]]
    mode = non_depots.groupby("serving_depot_id")["axis"].agg(
        lambda s: s.value_counts().index[0] if len(s) else "Rear"
    )
    # Depots themselves are 'Rear' by default
    depots = posts[posts["is_depot"]]
    out = {d: "Rear" for d in depots["id"]}
    for depot_id, axis in mode.items():
        out[depot_id] = axis
    return out


def score(vehicle_features: pd.DataFrame, posts: pd.DataFrame,
          horizon_days: int = cfg.VEHICLE_HORIZON_DAYS) -> pd.DataFrame:
    """
    Compute reliability_score = P(no deadline in next `horizon_days`)
    plus P(deadline) = 1 - reliability_score.

    Inputs:
      vehicle_features:  from features.build_vehicle_features(...)
      posts:             stage 2 posts.parquet — for axis assignment via home_depot
    """
    depot_axis = _depot_axis_map(posts)

    df = vehicle_features.copy()
    df["home_axis"] = df["home_depot_id"].map(depot_axis).fillna("Rear")
    df["frac_high_altitude"] = df["home_axis"].map(AXIS_ALTITUDE_EXPOSURE).fillna(0.1)

    # Weibull cumulative hazard at current age and at (age + horizon).
    # Critical: vehicles that have been deadlined and returned have effectively
    # reset their wear clock — Stage 2's generator models this by restarting
    # the hazard process after each event. So "effective age" is days since
    # the last event (or full initial_age + elapsed if no events yet).
    raw_age = df["age_days_at_asof"].clip(lower=1).astype(float)
    days_since_event = df["days_since_last_event"].fillna(raw_age).astype(float).values
    raw_age = raw_age.values
    # Effective age = if there was an event, time since it; else full age
    has_event = df["events_to_date"].fillna(0).astype(int).values > 0
    eff_age = np.where(has_event, days_since_event, raw_age)
    eff_age = np.maximum(eff_age, 1.0)

    age = eff_age
    age_h = age + horizon_days
    shape = df["weibull_shape"].astype(float).values
    scale = df["weibull_scale_days"].astype(float).values

    H_now    = (age / scale) ** shape
    H_future = (age_h / scale) ** shape

    # Altitude adjustment: scale incremental hazard (currently 0 in synthetic regime)
    altitude_factor = 1.0 + cfg.VEHICLE_ALTITUDE_HAZARD_MULTIPLIER * df["frac_high_altitude"].values
    delta_H = (H_future - H_now) * altitude_factor

    # P(survive H more days | survived to age)  =  exp(-delta_H)
    p_survive = np.exp(-delta_H)
    p_deadline = 1.0 - p_survive

    out = df[["vehicle_id", "vehicle_class", "home_depot_id", "home_axis",
              "age_days_at_asof", "events_to_date", "frac_high_altitude"]].copy()
    out["effective_age_days"] = eff_age
    out["horizon_days"]      = horizon_days
    out["reliability_score"] = p_survive
    out["p_deadline"]        = p_deadline
    out["model_version"]     = cfg.MODEL_VERSION
    out["scorer_kind"]       = "rule_weibull_altitude_v1"

    return out


def save_scorer_card() -> None:
    """Persist the scorer's coefficients as a JSON 'model artifact' for lineage."""
    card = {
        "model_version": cfg.MODEL_VERSION,
        "kind": "rule_weibull_altitude_v1",
        "horizon_days": cfg.VEHICLE_HORIZON_DAYS,
        "altitude_hazard_multiplier": cfg.VEHICLE_ALTITUDE_HAZARD_MULTIPLIER,
        "axis_altitude_exposure": AXIS_ALTITUDE_EXPOSURE,
        "synthetic_arbitrary_flags": [
            "altitude_hazard_multiplier (0.4 placeholder)",
            "axis_altitude_exposure fractions (operationally plausible)",
        ],
        "note": "Weibull shape and scale are read at runtime from the vehicles table; "
                "the scorer does not retrain them — it evaluates the analytic survival "
                "function with the parameters Stage 2 generated.",
    }
    path = cfg.MODELS_DIR / "vehicle_scorer_card.json"
    path.write_text(json.dumps(card, indent=2))
    print(f"  wrote {path}")


def evaluate_rolling(data: dict, horizon_days: int = cfg.VEHICLE_HORIZON_DAYS,
                      start_date: str = "2023-01-02",
                      end_date: str = "2024-12-24",
                      step_days: int = 7) -> dict:
    """
    Rolling backtest: score every `step_days` from start_date to end_date,
    count actual failures in (as_of, as_of + horizon], accumulate predictions
    and outcomes, then compute Brier and a real calibration curve over the
    full pool of (vehicle, as_of) observations.
    """
    posts = data["posts"]
    events = data["vehicle_events"].copy()
    events["deadline_date"] = pd.to_datetime(events["deadline_date"])

    dates = pd.date_range(start_date, end_date, freq=f"{step_days}D")
    rows = []
    for as_of in dates:
        veh_at = build_vehicle_features_runtime(data, as_of)  # see below
        scored = score(veh_at, posts, horizon_days)
        horizon_end = as_of + pd.Timedelta(days=horizon_days)
        in_window = events[(events["deadline_date"] > as_of) &
                            (events["deadline_date"] <= horizon_end)]
        failed_ids = set(in_window["vehicle_id"].unique())
        scored["actual_failed"] = scored["vehicle_id"].isin(failed_ids).astype(int)
        scored["as_of"] = as_of
        rows.append(scored[["as_of", "vehicle_id", "p_deadline", "actual_failed"]])

    pool = pd.concat(rows, ignore_index=True)
    p = pool["p_deadline"].values
    y = pool["actual_failed"].values

    brier = float(np.mean((p - y) ** 2))

    buckets = pd.cut(p, bins=[0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.3, 1.0],
                      include_lowest=True)
    cal = pd.DataFrame({"p": p, "y": y, "bucket": buckets}).groupby("bucket", observed=True).agg(
        n=("y", "count"), pred_mean=("p", "mean"), obs_rate=("y", "mean")
    ).reset_index()
    cal["bucket"] = cal["bucket"].astype(str)

    # Brier skill score vs the constant-rate baseline
    base = y.mean()
    brier_baseline = float(np.mean((base - y) ** 2))
    bss = 1.0 - brier / brier_baseline if brier_baseline > 0 else 0.0

    return {
        "backtest_window": [str(dates[0].date()), str(dates[-1].date())],
        "step_days": step_days,
        "horizon_days": horizon_days,
        "n_snapshots": len(dates),
        "n_observations": int(len(pool)),
        "n_actual_failures": int(y.sum()),
        "actual_failure_rate": round(float(y.mean()), 5),
        "predicted_failure_rate_mean": round(float(p.mean()), 5),
        "brier": round(brier, 6),
        "brier_baseline_constant_rate": round(brier_baseline, 6),
        "brier_skill_score_vs_baseline": round(bss, 4),
        "calibration_buckets": cal.to_dict(orient="records"),
    }


# Avoid circular import by referencing features lazily
def build_vehicle_features_runtime(data, as_of):
    import features as feat
    return feat.build_vehicle_features(data, as_of)


def evaluate(vehicle_features_atdate: pd.DataFrame, vehicle_events: pd.DataFrame,
             posts: pd.DataFrame, as_of_date: str | pd.Timestamp,
             horizon_days: int = cfg.VEHICLE_HORIZON_DAYS) -> dict:
    """
    Honest backtest: at `as_of_date`, score every vehicle, then check whether
    a deadline_date actually fell within (as_of_date, as_of_date + horizon].

    Reports Brier score and a calibration table (predicted bucket → observed rate).
    """
    as_of = pd.Timestamp(as_of_date)
    horizon_end = as_of + pd.Timedelta(days=horizon_days)

    scored = score(vehicle_features_atdate, posts, horizon_days)

    # Ground truth: any deadline in (as_of, as_of+horizon]
    events = vehicle_events.copy()
    events["deadline_date"] = pd.to_datetime(events["deadline_date"])
    in_window = events[(events["deadline_date"] > as_of) &
                       (events["deadline_date"] <= horizon_end)]
    actual_fail_ids = set(in_window["vehicle_id"].unique())
    scored["actual_failed"] = scored["vehicle_id"].isin(actual_fail_ids).astype(int)

    # Brier
    p = scored["p_deadline"].values
    y = scored["actual_failed"].values
    brier = float(np.mean((p - y) ** 2))

    # Calibration buckets
    buckets = pd.cut(p, bins=[0, 0.001, 0.005, 0.01, 0.05, 0.1, 0.3, 1.0], include_lowest=True)
    cal = pd.DataFrame({"p": p, "y": y, "bucket": buckets}).groupby("bucket", observed=True).agg(
        n=("y", "count"), pred_mean=("p", "mean"), obs_rate=("y", "mean")
    ).reset_index()
    cal["bucket"] = cal["bucket"].astype(str)

    out = {
        "as_of": str(as_of.date()),
        "horizon_days": horizon_days,
        "n_vehicles": int(len(scored)),
        "n_actual_failures": int(y.sum()),
        "actual_failure_rate": round(float(y.mean()), 4),
        "predicted_failure_rate_mean": round(float(p.mean()), 4),
        "brier": round(brier, 5),
        "calibration_buckets": cal.to_dict(orient="records"),
    }
    return out
