"""
Project Bastion — Stage 3 route classifier (v1.0)

Trains 5 passes × 4 horizons = 20 binary GBM classifiers predicting P(open at date+h)
given weather at the pass's anchor post, brigade-wide WD signal, calendar, and
the historical day-of-year base rate.

Why pass-level (not RouteSegment-level): Stage 2 models closure at the pass.
RouteSegment openness is a deterministic AND over the segment's crossed passes
(`routes.passes_crossed`). Modeling at the pass mirrors the data-generating
process. Roll-up to segment is done in `risk_scorer.py` or downstream SQL views.

Evaluation: AUC + Brier per (pass, horizon). Brier is the key metric because
the optimizer downstream needs calibrated probabilities, not just rankings.
"""

import json
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import roc_auc_score, brier_score_loss
from pathlib import Path
import config as cfg


def _encode(df: pd.DataFrame, cat_cols: list, num_cols: list,
            feature_cols: list | None = None) -> tuple[pd.DataFrame, list]:
    keep_cats = [c for c in cat_cols if c in df.columns]
    keep_nums = [c for c in num_cols if c in df.columns]
    X = pd.get_dummies(df[keep_cats + keep_nums], columns=keep_cats, drop_first=False)
    if feature_cols is not None:
        for c in feature_cols:
            if c not in X.columns:
                X[c] = 0
        X = X[feature_cols]
    return X, list(X.columns)


def train(route_df: pd.DataFrame) -> dict:
    """
    Train one XGBoost classifier per (pass, horizon). Returns:
        models[(pass_name, horizon)] = {"booster": ..., "feature_cols": [...]}
    """
    train_end  = pd.Timestamp(cfg.TRAIN_END_DATE)
    test_start = pd.Timestamp(cfg.TEST_START_DATE)
    test_end   = pd.Timestamp(cfg.TEST_END_DATE)

    df = route_df.dropna(subset=["is_open_target"]).copy()
    df["y"] = df["is_open_target"].astype(int)

    train = df[df["date"] <= train_end]
    test  = df[(df["date"] >= test_start) & (df["date"] <= test_end)]

    train_weeks = sorted(train["date"].unique())
    val_cutoff = train_weeks[int(len(train_weeks) * 0.9)]
    inner_train = train[train["date"] < val_cutoff]
    inner_val   = train[train["date"] >= val_cutoff]

    cat_cols = cfg.ROUTE_CATEGORICAL_COLS
    num_cols = cfg.ROUTE_NUMERIC_COLS

    models = {}
    eval_records = []

    for pass_name in cfg.ROUTE_PASSES:
        for h in cfg.ROUTE_HORIZONS_DAYS:
            tag = f"{pass_name}|h={h}d"
            it = inner_train[(inner_train["pass_name"] == pass_name) & (inner_train["horizon"] == h)]
            iv = inner_val[(inner_val["pass_name"] == pass_name)   & (inner_val["horizon"]   == h)]
            te = test[(test["pass_name"] == pass_name)             & (test["horizon"]        == h)]

            if len(it) < 50 or it["y"].nunique() < 2:
                print(f"    [skip {tag}] insufficient training data or single-class")
                continue

            X_it, fcols = _encode(it, cat_cols, num_cols)
            y_it = it["y"].values
            X_iv, _ = _encode(iv, cat_cols, num_cols, feature_cols=fcols)
            y_iv = iv["y"].values
            X_te, _ = _encode(te, cat_cols, num_cols, feature_cols=fcols)
            y_te = te["y"].values

            params = dict(cfg.XGB_BINARY_PARAMS)
            n_est  = params.pop("n_estimators")

            # Class imbalance: closure rates are 5-20% → upweight positives
            pos = int(y_it.sum())
            neg = int(len(y_it) - pos)
            if pos > 0:
                # We want to predict P(open=1); closures are the rare negative class.
                # The pass open rate is ~80-94%, so positives (open) dominate. Don't
                # reweight automatically — but if the test class balance is extreme,
                # log it.
                params["scale_pos_weight"] = max(0.1, neg / max(pos, 1))
            booster = xgb.train(
                params,
                xgb.DMatrix(X_it, label=y_it),
                num_boost_round=n_est,
                evals=[(xgb.DMatrix(X_iv, label=y_iv), "val")],
                early_stopping_rounds=cfg.ROUTE_EARLY_STOPPING_ROUNDS,
                verbose_eval=False,
            )

            models[(pass_name, h)] = {"booster": booster, "feature_cols": fcols}

            # Holdout metrics
            metrics = {"pass": pass_name, "horizon_days": h,
                       "n_train": int(len(it)), "n_test": int(len(te)),
                       "train_open_rate": round(float(y_it.mean()), 3),
                       "test_open_rate":  round(float(y_te.mean()) if len(te) else 0, 3)}

            if len(te) > 0 and len(np.unique(y_te)) >= 2:
                pr = booster.predict(xgb.DMatrix(X_te))
                pr = np.clip(pr, 1e-6, 1 - 1e-6)
                metrics["AUC_open"] = round(float(roc_auc_score(y_te, pr)), 3)
                metrics["Brier"] = round(float(brier_score_loss(y_te, pr)), 4)
                # P(closed) Brier for the rare class — flip predictions
                metrics["Brier_closed"] = round(float(brier_score_loss(1 - y_te, 1 - pr)), 4)
            else:
                metrics["AUC_open"] = None
                metrics["Brier"] = None

            eval_records.append(metrics)

            print(f"    [{tag}] n_train={len(it):5d}  AUC={metrics.get('AUC_open')}  Brier={metrics.get('Brier')}")

    eval_path = cfg.REPORT_DIR / "evaluation_route.json"
    with eval_path.open("w") as f:
        json.dump({
            "model_version": cfg.MODEL_VERSION,
            "n_models_trained": len(models),
            "train_end": cfg.TRAIN_END_DATE,
            "test_window": [cfg.TEST_START_DATE, cfg.TEST_END_DATE],
            "models": eval_records,
        }, f, indent=2)
    print(f"  wrote {eval_path}")

    return models


def save(models: dict) -> None:
    manifest = {}
    for (pass_name, h), m in models.items():
        key = f"{pass_name.replace(' ', '_')}__h{h}"
        path = cfg.MODELS_DIR / f"route_{key}.json"
        m["booster"].save_model(str(path))
        manifest[key] = {
            "pass": pass_name, "horizon_days": h,
            "feature_cols": m["feature_cols"],
            "artifact": str(path.name),
        }
    manifest_path = cfg.MODELS_DIR / "route_manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  saved {len(models)} route models + {manifest_path.name}")


def load() -> dict:
    manifest = json.loads((cfg.MODELS_DIR / "route_manifest.json").read_text())
    models = {}
    for key, info in manifest.items():
        booster = xgb.Booster()
        booster.load_model(str(cfg.MODELS_DIR / info["artifact"]))
        models[(info["pass"], info["horizon_days"])] = {
            "booster": booster,
            "feature_cols": info["feature_cols"],
        }
    return models


def predict(route_df: pd.DataFrame, models: dict) -> pd.DataFrame:
    """Apply all (pass, horizon) models. Returns one row per (pass, date, horizon)."""
    out = []
    cat_cols = cfg.ROUTE_CATEGORICAL_COLS
    num_cols = cfg.ROUTE_NUMERIC_COLS

    for (pass_name, h), m in models.items():
        sub = route_df[(route_df["pass_name"] == pass_name) & (route_df["horizon"] == h)].copy()
        if len(sub) == 0:
            continue
        X, _ = _encode(sub, cat_cols, num_cols, feature_cols=m["feature_cols"])
        pr = m["booster"].predict(xgb.DMatrix(X))
        pr = np.clip(pr, 1e-6, 1 - 1e-6)
        chunk = sub[["pass_name", "date", "horizon"]].copy().reset_index(drop=True)
        chunk["p_open"]   = pr
        chunk["p_closed"] = 1 - pr
        out.append(chunk)

    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()
