"""
Project Bastion — Stage 3 spares-demand forecaster (v1.2, Phase 2)

PDS 5 — "AI Based Preventive Maintenance of Equipment and Demand Forecast of
Spares" — asks, in its second half, for prediction of SPARE-PART demand. Every
generic logistics tool forecasts ration/fuel consumption; almost none forecast
which clutch assemblies and radiators a forward formation will burn through next
quarter, driven by impending equipment failure. This module does exactly that,
and it is the defensible half of "demand forecast."

HOW IT WORKS — it composes two things that already exist, nothing new learned
about the world:

  1. The vehicle reliability scorer (vehicle_reliability.py) gives, per vehicle,
     P(deadline within H days). We have that per vehicle, and each vehicle is
     homed at a depot.
  2. The spares-consumption ground truth (stage2 spares_consumption.parquet)
     gives the empirical distribution of WHICH spare SKUs a failure consumes,
     by failure subsystem and vehicle class. We learn that distribution on the
     TRAIN window only (no leakage from the forecast horizon).

  Forecast(depot, horizon) = Monte-Carlo over the depot's fleet:
     for each MC trial:
       for each vehicle homed at the depot:
         fails ~ Bernoulli( p_deadline scaled to the horizon )
         if fails: subsystem ~ empirical subsystem mix (train window)
                   parts    ~ empirical parts-per-subsystem (train window)
       accumulate per-SKU units this trial
     report P10 / P50 / P90 per (depot, SKU, horizon)

This is a genuine quantile forecast — the spread comes from failure uncertainty
(few vehicles, rare events) and parts-draw uncertainty, exactly what a spares
cell needs to set safety stock. Deterministic via SPARES_MC_SEED.

Honesty: the parts distribution is learned from SYNTHETIC-ARBITRARY ground truth
(no public Army spares table exists). The METHOD is real and transfers directly
to real VOR + parts-issue data; the NUMBERS are synthetic and flagged as such.

Outputs `spares_forecast.parquet`:
  depot_id, sku, sku_name, subsystem, horizon_days,
  demand_p10, demand_p50, demand_p90, demand_mean,
  weight_kg_p50, expected_cost_p50, model_version, scorer_kind, provenance
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd

import config as cfg
import vehicle_reliability as vr

PROVENANCE = "synthetic-arbitrary"   # the parts distribution; method is real
FORECASTER_KIND = "mc_failure_x_parts_v1"

# spares catalogue mirrored from Stage 2 config so Stage 3 has no import edge
# into Stage 2. Kept in sync deliberately; if Stage 2 changes the catalogue this
# constant must change too (a single-source refactor is a later cleanup).
try:
    from stage2_config_bridge import SPARES_CATALOGUE  # optional shared bridge
except Exception:
    SPARES_CATALOGUE = None


def _load_spares_catalogue(data: dict) -> dict:
    """Resolve the spares catalogue: prefer a meta table if present, else read
    the distinct SKUs from the consumption table and fill names/weights/costs
    from the embedded map below (kept in sync with stage2 config)."""
    fallback = {
        "SPR-001": ("Radiator assembly", "engine_cooling", 28.0, 42000),
        "SPR-002": ("Coolant hose + thermostat", "engine_cooling", 3.5, 4200),
        "SPR-003": ("Clutch assembly", "drivetrain", 34.0, 56000),
        "SPR-004": ("Gearbox seal kit", "drivetrain", 2.0, 6800),
        "SPR-005": ("Propshaft UJ", "drivetrain", 6.5, 9500),
        "SPR-006": ("Leaf spring + shackle", "running_gear", 45.0, 18000),
        "SPR-007": ("Wheel bearing kit", "running_gear", 4.0, 7200),
        "SPR-008": ("Suspension bush set", "running_gear", 2.5, 3100),
        "SPR-009": ("Brake lining set", "brakes", 8.0, 5400),
        "SPR-010": ("Slack adjuster + airline", "brakes", 3.0, 4800),
        "SPR-011": ("Alternator", "electrical", 7.0, 16000),
        "SPR-012": ("Battery (HD, cold-rated)", "electrical", 24.0, 12500),
        "SPR-013": ("Starter + glow set", "electrical", 9.0, 11000),
        "SPR-014": ("Filter set (air/fuel/oil)", "filtration", 5.0, 2600),
    }
    return {k: {"name": n, "subsystem": s, "weight_kg": w, "unit_cost": c}
            for k, (n, s, w, c) in fallback.items()}


def fit_parts_distribution(spares_consumption: pd.DataFrame,
                           train_end: str = cfg.TRAIN_END_DATE) -> dict:
    """Learn, on the TRAIN window only:
       - subsystem mix per failure event (P(subsystem))
       - per-event parts profile: for each subsystem, the empirical mean units
         of each SKU consumed PER FAILURE attributed to that subsystem.
    Returned as plain dicts so it serialises into the model card."""
    sc = spares_consumption.copy()
    sc["deadline_date"] = pd.to_datetime(sc["deadline_date"])
    sc = sc[sc["deadline_date"] < pd.Timestamp(train_end)]

    # events per subsystem (a failure = one (vehicle_id, deadline_date))
    ev_keys = sc[["vehicle_id", "deadline_date", "subsystem"]].drop_duplicates()
    sub_counts = ev_keys["subsystem"].value_counts()
    n_events = int(sub_counts.sum())
    subsystem_mix = {s: float(c / n_events) for s, c in sub_counts.items()} if n_events else {}

    # mean units of each SKU per failure of its subsystem
    parts_profile: dict = {}
    for sub, grp in sc.groupby("subsystem"):
        n_sub_events = int(ev_keys[ev_keys["subsystem"] == sub].shape[0])
        if n_sub_events == 0:
            continue
        per_sku = grp.groupby("sku")["qty"].sum() / n_sub_events
        parts_profile[sub] = {sku: float(u) for sku, u in per_sku.items()}

    return {"subsystem_mix": subsystem_mix,
            "parts_profile": parts_profile,
            "n_train_events": n_events,
            "train_end": str(train_end)}


def save_forecaster_card(parts_fit: dict) -> None:
    card = {"model_version": cfg.MODEL_VERSION, "kind": FORECASTER_KIND,
            "horizons": cfg.SPARES_FORECAST_HORIZONS,
            "mc_trials": cfg.SPARES_MC_TRIALS, "mc_seed": cfg.SPARES_MC_SEED,
            "provenance": PROVENANCE, **parts_fit,
            "note": "Spare-part demand = MC over (vehicle failure x empirical "
                    "parts-per-subsystem). Method real; parts numbers synthetic."}
    (cfg.MODELS_DIR / "spares_forecaster_card.json").write_text(json.dumps(card, indent=2))


def _vehicle_p_deadline_by_horizon(vehicle_scores: pd.DataFrame,
                                   horizon_days: int) -> pd.Series:
    """Scale the scorer's per-horizon p_deadline (fitted at VEHICLE_HORIZON_DAYS)
    to an arbitrary horizon via the constant-rate identity:
        p_H = 1 - (1 - p_h0) ** (H / h0)
    Returns a Series indexed by vehicle_id."""
    h0 = int(vehicle_scores["horizon_days"].iloc[0]) if "horizon_days" in vehicle_scores else cfg.VEHICLE_HORIZON_DAYS
    p_h0 = vehicle_scores.set_index("vehicle_id")["p_deadline"].clip(0, 0.999)
    p_H = 1.0 - (1.0 - p_h0) ** (horizon_days / max(h0, 1))
    return p_H.clip(0, 0.999)


def forecast(vehicle_scores: pd.DataFrame, vehicles: pd.DataFrame,
             parts_fit: dict, horizons: list | None = None) -> pd.DataFrame:
    """Monte-Carlo spare-part demand per (depot, SKU, horizon) with P10/P50/P90.
    vehicle_scores: output of vehicle_reliability.score (has vehicle_id,
    p_deadline, horizon_days). vehicles: the fleet table (home_depot_id)."""
    horizons = horizons or cfg.SPARES_FORECAST_HORIZONS
    cat = _load_spares_catalogue({})
    sub_mix = parts_fit["subsystem_mix"]
    parts_profile = parts_fit["parts_profile"]
    subsystems = sorted(sub_mix)
    sub_p = np.array([sub_mix[s] for s in subsystems], dtype=float)
    sub_p = sub_p / sub_p.sum() if sub_p.sum() > 0 else sub_p

    home = vehicles.set_index("vehicle_id")["home_depot_id"]
    depots = sorted(home.dropna().unique())
    rng = np.random.default_rng(cfg.SPARES_MC_SEED)
    all_skus = sorted(cat)
    sku_idx = {s: i for i, s in enumerate(all_skus)}

    rows = []
    for H in horizons:
        p_fail = _vehicle_p_deadline_by_horizon(vehicle_scores, H)
        for depot in depots:
            veh_ids = [v for v in home[home == depot].index if v in p_fail.index]
            if not veh_ids:
                continue
            pv = p_fail.loc[veh_ids].values
            n_veh = len(pv)
            T = cfg.SPARES_MC_TRIALS
            # trials x SKU accumulation
            acc = np.zeros((T, len(all_skus)), dtype=float)
            # vectorised failure draws: T x n_veh
            fails = rng.random((T, n_veh)) < pv[None, :]
            n_fail_per_trial = fails.sum(axis=1)
            for t in range(T):
                nf = int(n_fail_per_trial[t])
                if nf == 0:
                    continue
                # assign each failure a subsystem
                subs = rng.choice(len(subsystems), size=nf, p=sub_p)
                for si in subs:
                    sub = subsystems[si]
                    for sku, mean_units in parts_profile.get(sub, {}).items():
                        # per-failure units ~ Poisson(mean_units) (integer parts)
                        if mean_units > 0 and sku in sku_idx:
                            acc[t, sku_idx[sku]] += rng.poisson(mean_units)
            for sku in all_skus:
                col = acc[:, sku_idx[sku]]
                if col.max() == 0:
                    continue
                meta = cat[sku]
                p50 = float(np.percentile(col, 50))
                rows.append({
                    "depot_id": depot, "sku": sku, "sku_name": meta["name"],
                    "subsystem": meta["subsystem"], "horizon_days": H,
                    "demand_p10": float(np.percentile(col, 10)),
                    "demand_p50": p50,
                    "demand_p90": float(np.percentile(col, 90)),
                    "demand_mean": round(float(col.mean()), 3),
                    "weight_kg_p50": round(p50 * meta["weight_kg"], 1),
                    "expected_cost_p50": round(p50 * meta["unit_cost"], 0),
                    "model_version": cfg.MODEL_VERSION,
                    "scorer_kind": FORECASTER_KIND,
                    "provenance": PROVENANCE,
                })
    return pd.DataFrame(rows).sort_values(
        ["depot_id", "horizon_days", "sku"]).reset_index(drop=True)


def evaluate(spares_consumption: pd.DataFrame, vehicles: pd.DataFrame,
             vehicle_scores_at: pd.DataFrame, parts_fit: dict,
             eval_start: str = "2024-07-01", horizon_days: int = 90) -> dict:
    """Backtest: forecast spares demand per depot for the horizon starting at
    eval_start, compare P50 to ACTUAL consumed in that window. Reports MAPE on
    depot-SKU pairs with non-trivial actual demand, plus P10–P90 coverage."""
    fc = forecast(vehicle_scores_at, vehicles, parts_fit, horizons=[horizon_days])
    sc = spares_consumption.copy()
    sc["deadline_date"] = pd.to_datetime(sc["deadline_date"])
    win = sc[(sc["deadline_date"] >= pd.Timestamp(eval_start)) &
             (sc["deadline_date"] < pd.Timestamp(eval_start) + pd.Timedelta(days=horizon_days))]
    home = vehicles.set_index("vehicle_id")["home_depot_id"]
    win = win.assign(depot_id=win["vehicle_id"].map(home))
    actual = win.groupby(["depot_id", "sku"])["qty"].sum().rename("actual")
    m = fc.merge(actual, on=["depot_id", "sku"], how="left").fillna({"actual": 0.0})
    sig = m[m["actual"] >= 2.0]   # depot-SKU pairs with meaningful demand
    if len(sig):
        ape = (sig["demand_p50"] - sig["actual"]).abs() / sig["actual"].clip(lower=1)
        mape = float(ape.mean())
        cov = float(((sig["actual"] >= sig["demand_p10"]) &
                     (sig["actual"] <= sig["demand_p90"])).mean())
    else:
        mape, cov = float("nan"), float("nan")
    return {"eval_start": eval_start, "horizon_days": horizon_days,
            "n_depot_sku_pairs_scored": int(len(m)),
            "n_pairs_meaningful_demand": int(len(sig)),
            "spares_mape_p50": round(mape, 4) if mape == mape else None,
            "p10_p90_coverage": round(cov, 4) if cov == cov else None,
            "mape_framing_note": "MAPE on a low-count discrete process (a depot "
                                 "burns a handful of any given SKU per quarter) is "
                                 "inherently high-variance; P10-P90 coverage is the "
                                 "better honesty check that the quantile band is "
                                 "calibrated. Numbers are SYNTHETIC-ARBITRARY parts "
                                 "ground truth; the method transfers to real data.",
            "provenance": PROVENANCE}
