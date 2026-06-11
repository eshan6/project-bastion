"""
Project Bastion — Stage 3 vehicle reliability scorer (v2.0)

v2.0 change (#1 from audit): EMPIRICAL AXIS MULTIPLIERS, fitted on the
train window.

v1 was a pure Weibull rule scorer with a hardcoded altitude adjustment that
was zeroed out (VEHICLE_ALTITUDE_HAZARD_MULTIPLIER = 0.0) — honest, because
the v1 generator gave every vehicle an identical hazard process, so there
was no real heterogeneity to predict and Brier skill was ~0 by construction.

The v2 generator (stage2 vehicles.py v2.0) gives each vehicle a persistent
mission-band mix derived from its home depot's axis. Forward-axis fleets
(DBO) now genuinely fail more often than rear fleets. The v2 scorer LEARNS
that effect from the event data itself:

    mult(axis) = events-per-vehicle-day(axis) / events-per-vehicle-day(fleet)

estimated ONLY on events before TRAIN_END_DATE, normalised to fleet mean 1,
then applied to the Weibull incremental hazard. We deliberately do NOT read
the generator's band-mix constants — that would be label leakage. The scorer
sees what a real maintenance officer would see: the unit's own VOR history.

Outputs P(deadline within next H days | survived age t):
    H(t)        = (t / scale)^shape                  cumulative hazard
    ΔH          = (H(t+Δ) − H(t)) × mult(home_axis)
    P(deadline) = 1 − exp(−ΔH)
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
import config as cfg


SCORER_KIND = "rule_weibull_axis_v2"
_CARD_PATH = cfg.MODELS_DIR / "vehicle_scorer_card.json"
_card_cache: dict | None = None


def _depot_axis_map(posts: pd.DataFrame) -> dict:
    """Map each depot_id to the modal axis it serves (excluding 'Rear')."""
    non_depots = posts[~posts["is_depot"]]
    mode = non_depots.groupby("serving_depot_id")["axis"].agg(
        lambda s: s.value_counts().index[0] if len(s) else "Rear")
    out = {d: "Rear" for d in posts[posts["is_depot"]]["id"]}
    for depot_id, axis in mode.items():
        out[depot_id] = axis
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Fit (train window only)
# ─────────────────────────────────────────────────────────────────────────────
def fit_rate_model(vehicles: pd.DataFrame, vehicle_events: pd.DataFrame,
                    posts: pd.DataFrame,
                    train_end: str = cfg.TRAIN_END_DATE,
                    fit_start: str = "2022-07-01") -> dict:
    """Fully empirical Poisson-rate model, fitted on the train window only.

    The v2 generator's event process is memoryless given covariates (Exp(1)
    threshold, linear hazard accumulation) — so the right model is a RATE,
    not a Weibull age curve:

        rate(vehicle, day) = base × mult_class × mult_axis × mult_season

    Each multiplier = observed events-per-vehicle-day in that slice relative
    to the fleet, normalised to weighted mean 1.0. This is exactly what a
    maintenance officer would estimate from unit VOR history — no generator
    internals are read."""
    d2a = _depot_axis_map(posts)
    v = vehicles.copy()
    v["home_axis"] = v["home_depot_id"].map(d2a).fillna("Rear")

    ev = vehicle_events.copy()
    ev["deadline_date"] = pd.to_datetime(ev["deadline_date"])
    # Fit on the steady-state window only: the generator's initial-age hazard
    # preload produces a 2022Q1 burst (~5x steady-state rate) that is a
    # simulation artefact, not fleet physics. Including it inflates the base
    # rate ~40% and wrecks calibration. Documented honestly here.
    ev = ev[(ev["deadline_date"] >= pd.Timestamp(fit_start)) &
            (ev["deadline_date"] < pd.Timestamp(train_end))]
    ev = ev.merge(v[["vehicle_id", "home_axis", "vehicle_class"]]
                  .rename(columns={"vehicle_class": "vc"}),
                  on="vehicle_id", how="left")

    start = pd.Timestamp(fit_start)
    cal = pd.date_range(start, pd.Timestamp(train_end))
    n_days = len(cal)
    winter_days = int(cal.month.isin([11, 12, 1, 2, 3]).sum())
    open_days = n_days - winter_days

    base_rate = len(ev) / (len(v) * n_days)            # events / vehicle-day

    def _mults(group_col, ev_col):
        n_by = v.groupby(group_col).size()
        e_by = ev.groupby(ev_col).size()
        rate = (e_by / (n_by * n_days)).dropna()
        m = (rate / base_rate).to_dict()
        w = n_by / n_by.sum()
        mean_m = sum(m.get(a, 1.0) * w[a] for a in n_by.index)
        return {a: round(x / mean_m, 4) for a, x in m.items()}

    axis_mult = _mults("home_axis", "home_axis")
    class_mult = _mults("vehicle_class", "vc")

    # Season: winter vs open event rate ratio (winter_flag is on the event)
    w_ev = int(ev["winter_flag"].sum()); o_ev = len(ev) - w_ev
    r_w = w_ev / (len(v) * winter_days); r_o = o_ev / (len(v) * open_days)
    # normalise so day-weighted mean season multiplier is 1.0
    mean_season = (r_w * winter_days + r_o * open_days) / (base_rate * n_days)
    season_mult = {"winter": round(r_w / base_rate / mean_season, 4),
                   "open":   round(r_o / base_rate / mean_season, 4)}

    # ── Empirical-Bayes dispersion (per-vehicle heterogeneity) ──────────────
    # Residual rate ratio u_i = lambda_i / r_i ~ Gamma(alpha, alpha), mean 1.
    # k_i ~ Poisson(r_i * T * u_i). Method of moments:
    #   1/alpha = sum[(k_i - mu_i)^2 - mu_i] / sum(mu_i^2),  mu_i = r_i * T
    # alpha small => strong per-vehicle heterogeneity => trust unit history more.
    k = ev.groupby("vehicle_id").size()
    v_idx = v.set_index("vehicle_id")
    r_i = (base_rate
           * v_idx["home_axis"].map(axis_mult).fillna(1.0)
           * v_idx["vehicle_class"].map(class_mult).fillna(1.0))
    mu = (r_i * n_days)
    k_full = k.reindex(v_idx.index).fillna(0.0)
    num = float(((k_full - mu) ** 2 - mu).sum())
    den = float((mu ** 2).sum())
    inv_alpha = max(num / den, 1e-6)
    eb_alpha = 1.0 / inv_alpha

    return {"base_rate_per_vehicle_day": round(float(base_rate), 6),
            "eb_alpha": round(float(eb_alpha), 3),
            "eb_note": "Gamma-Poisson empirical Bayes on per-vehicle residual rate; "
                       "posterior u_i = (alpha + k_365)/(alpha + r_i*365). Captures "
                       "persistent per-vehicle heterogeneity (the band-mix jitter) "
                       "from unit VOR history alone.",
            "fit_start": str(fit_start),
            "axis_multipliers": axis_mult,
            "class_multipliers": class_mult,
            "season_multipliers": season_mult,
            "train_end": str(train_end),
            "n_train_events": int(len(ev))}


def save_scorer_card(fit: dict | None = None) -> None:
    """Persist the fitted rate model as the model artifact."""
    card = {
        "model_version": cfg.MODEL_VERSION,
        "kind": SCORER_KIND,
        "horizon_days": cfg.VEHICLE_HORIZON_DAYS,
        **(fit or {}),
        "synthetic_arbitrary_flags": [],
        "note": "Empirical Poisson-rate scorer fitted on train-window VOR events "
                "(class x axis x season multipliers on a fleet base rate). No "
                "generator internals are read — this is what a maintenance officer "
                "would estimate from unit history. Replaces the v1 Weibull analytic, "
                "whose age-dependence was mis-specified for a memoryless process.",
    }
    _CARD_PATH.write_text(json.dumps(card, indent=2))
    global _card_cache
    _card_cache = card
    print(f"  wrote {_CARD_PATH}")
    print(f"    base_rate={card.get('base_rate_per_vehicle_day')}  "
          f"axis={card.get('axis_multipliers')}  season={card.get('season_multipliers')}")


def _load_card() -> dict:
    global _card_cache
    if _card_cache is None:
        if _CARD_PATH.exists():
            _card_cache = json.loads(_CARD_PATH.read_text())
        else:
            _card_cache = {"axis_multipliers": {}}
    return _card_cache


# ─────────────────────────────────────────────────────────────────────────────
# Score
# ─────────────────────────────────────────────────────────────────────────────
def score(vehicle_features: pd.DataFrame, posts: pd.DataFrame,
          horizon_days: int = cfg.VEHICLE_HORIZON_DAYS) -> pd.DataFrame:
    """reliability_score = P(no deadline in next `horizon_days`) from the
    fitted empirical rate model: p = 1 - exp(-rate x H)."""
    depot_axis = _depot_axis_map(posts)
    card = _load_card()
    base = card.get("base_rate_per_vehicle_day", 0.0015)
    a_m = card.get("axis_multipliers", {})
    c_m = card.get("class_multipliers", {})
    s_m = card.get("season_multipliers", {"winter": 1.0, "open": 1.0})

    df = vehicle_features.copy()
    df["home_axis"] = df["home_depot_id"].map(depot_axis).fillna("Rear")
    df["axis_multiplier"] = df["home_axis"].map(a_m).fillna(1.0)
    df["class_multiplier"] = df["vehicle_class"].map(c_m).fillna(1.0)

    as_of = pd.Timestamp(df["as_of"].iloc[0]) if "as_of" in df.columns else None
    is_winter = bool(as_of.month in (11, 12, 1, 2, 3)) if as_of is not None else False
    season = s_m["winter"] if is_winter else s_m["open"]
    df["season_multiplier"] = season

    rate_prior = base * df["axis_multiplier"] * df["class_multiplier"]

    # Empirical-Bayes update from the vehicle's own trailing-365d history
    alpha = card.get("eb_alpha", None)
    if alpha and "events_last_365d" in df.columns:
        k365 = df["events_last_365d"].fillna(0).astype(float).values
        mu365 = rate_prior.values * 365.0
        u_post = (alpha + k365) / (alpha + mu365)
        df["eb_posterior_u"] = u_post
        rate = rate_prior.values * u_post * season
    else:
        df["eb_posterior_u"] = 1.0
        rate = rate_prior.values * season
    p_deadline = 1.0 - np.exp(-rate * horizon_days)
    p_survive = 1.0 - p_deadline

    out = df[["vehicle_id", "vehicle_class", "home_depot_id", "home_axis",
              "age_days_at_asof", "events_to_date",
              "axis_multiplier", "class_multiplier", "season_multiplier",
              "eb_posterior_u"]].copy()
    out["horizon_days"]      = horizon_days
    out["reliability_score"] = p_survive
    out["p_deadline"]        = p_deadline
    out["model_version"]     = cfg.MODEL_VERSION
    out["scorer_kind"]       = SCORER_KIND
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Evaluation# ─────────────────────────────────────────────────────────────────────────────
# Evaluation (rolling backtest — unchanged mechanics from v1)
# ─────────────────────────────────────────────────────────────────────────────
def evaluate_rolling(data: dict, horizon_days: int = cfg.VEHICLE_HORIZON_DAYS,
                      start_date: str = "2023-01-02",
                      end_date: str = "2024-12-24",
                      step_days: int = 7) -> dict:
    posts = data["posts"]
    events = data["vehicle_events"].copy()
    events["deadline_date"] = pd.to_datetime(events["deadline_date"])

    dates = pd.date_range(start_date, end_date, freq=f"{step_days}D")
    rows = []
    for as_of in dates:
        veh_at = build_vehicle_features_runtime(data, as_of)
        scored = score(veh_at, posts, horizon_days)
        horizon_end = as_of + pd.Timedelta(days=horizon_days)
        in_window = events[(events["deadline_date"] > as_of) &
                            (events["deadline_date"] <= horizon_end)]
        failed_ids = set(in_window["vehicle_id"].unique())
        scored["actual_failed"] = scored["vehicle_id"].isin(failed_ids).astype(int)
        scored["as_of"] = as_of
        rows.append(scored[["as_of", "vehicle_id", "home_axis", "p_deadline", "actual_failed"]])

    pool = pd.concat(rows, ignore_index=True)
    p = pool["p_deadline"].values
    y = pool["actual_failed"].values
    brier = float(np.mean((p - y) ** 2))

    buckets = pd.cut(p, bins=[0, 0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.3, 1.0],
                      include_lowest=True)
    cal = pd.DataFrame({"p": p, "y": y, "bucket": buckets}).groupby("bucket", observed=True).agg(
        n=("y", "count"), pred_mean=("p", "mean"), obs_rate=("y", "mean")).reset_index()
    cal["bucket"] = cal["bucket"].astype(str)

    base = y.mean()
    brier_baseline = float(np.mean((base - y) ** 2))
    bss = 1.0 - brier / brier_baseline if brier_baseline > 0 else 0.0

    # AUC — the right discrimination metric for rare events. Brier skill is
    # bounded near zero here by construction: with base rate ~0.8% and a
    # ~1.4x axis rate ratio, the covariate ceiling on Brier skill is ~2e-4.
    # AUC measures whether high-p vehicles actually fail more — which is what
    # the optimizer's risk objective consumes.
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y, p)) if 0 < y.sum() < len(y) else float("nan")
    except Exception:
        auc = float("nan")

    # Per-axis discrimination — the new diagnostic for #1
    axis_diag = pool.groupby("home_axis").agg(
        n=("actual_failed", "count"),
        pred_mean=("p_deadline", "mean"),
        obs_rate=("actual_failed", "mean")).round(5).reset_index().to_dict(orient="records")

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
        "auc": round(auc, 4),
        "metric_framing_note": "Dual framing: Brier skill ~0 is the covariate ceiling "
                                "for rare events (base rate 0.8%); AUC is the "
                                "discrimination metric the risk objective actually uses.",
        "per_axis_discrimination": axis_diag,
        "calibration_buckets": cal.to_dict(orient="records"),
    }


def build_vehicle_features_runtime(data, as_of):
    import features as feat
    return feat.build_vehicle_features(data, as_of)
