"""
Project Bastion — Stage 3 demand forecasters (v1.0)

Trains and serves quantile XGBoost demand forecasters sliced by (band, head).
3 bands × 6 heads = 18 models per quantile × 3 quantiles = 54 model artifacts.

Why this slicing:
  - Per (post, sku) (1,050 models) overfits — sparse non-zero days for ammo SKUs.
  - Global per-SKU (30 models) loses the altitude-band coupling that drives kerosene.
  - Per (band, head) (18 models) preserves the dominant structural cuts while
    giving each model enough rows (~2k–80k weekly observations) to converge stably.
    SKU identity within head is a model feature, not a slicing key.

Output: writes a parquet `demand_forecasts.parquet` with one row per
(post, sku, week, horizon) and columns p10/p50/p90.
"""

import json
import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.metrics import mean_absolute_error
from pathlib import Path
import config as cfg
import features as feat


# ─────────────────────────────────────────────────────────────────────────────
# Encoding helpers
# ─────────────────────────────────────────────────────────────────────────────
def _encode(df: pd.DataFrame, cat_cols: list, num_cols: list,
            feature_cols: list | None = None) -> tuple[pd.DataFrame, list]:
    """One-hot encode categoricals; preserve feature_cols schema if given."""
    keep_cats = [c for c in cat_cols if c in df.columns]
    keep_nums = [c for c in num_cols if c in df.columns]
    X = pd.get_dummies(df[keep_cats + keep_nums], columns=keep_cats, drop_first=False)
    if feature_cols is not None:
        # Align to training-time schema
        for c in feature_cols:
            if c not in X.columns:
                X[c] = 0
        X = X[feature_cols]
    return X, list(X.columns)


# ─────────────────────────────────────────────────────────────────────────────
# Train: per-(band, head) quantile XGBoost
# ─────────────────────────────────────────────────────────────────────────────
def _calibrate_quantile(pred_val: np.ndarray, y_val: np.ndarray, q: float) -> float:
    """
    Conformal-style additive offset: the q-th empirical quantile of
    (y - pred) on validation. Adding this offset to predictions makes
    the calibrated quantile achieve the target coverage rate on val.
    """
    if len(pred_val) == 0:
        return 0.0
    resid = y_val - pred_val
    return float(np.quantile(resid, q))


def train(panel: pd.DataFrame) -> dict:
    """
    Train 18 (band, head) models for each quantile. Returns a dict:
        models[(band, head, q)] = {"booster": Booster, "feature_cols": [...]}
    Also writes evaluation_demand.json with honest holdout MAPE per slice.
    """
    train_end = pd.Timestamp(cfg.TRAIN_END_DATE)
    test_start = pd.Timestamp(cfg.TEST_START_DATE)
    test_end = pd.Timestamp(cfg.TEST_END_DATE)

    panel = panel.copy()
    panel = panel.dropna(subset=["qty_weekly"])
    train = panel[panel["week"] <= train_end].copy()
    test  = panel[(panel["week"] >= test_start) & (panel["week"] <= test_end)].copy()

    # Internal validation split: last 10% of training weeks for early-stopping
    train_weeks = sorted(train["week"].unique())
    val_cutoff = train_weeks[int(len(train_weeks) * 0.9)]
    inner_train = train[train["week"] < val_cutoff]
    inner_val   = train[train["week"] >= val_cutoff]

    cat_cols = cfg.DEMAND_CATEGORICAL_COLS
    num_cols = cfg.DEMAND_NUMERIC_COLS

    models = {}
    eval_records = []

    slices = panel.groupby(["band", "head"]).size().reset_index(name="n")
    print(f"  Slicing into {len(slices)} (band, head) cohorts:")

    for _, srow in slices.iterrows():
        band, head = srow["band"], srow["head"]
        tag = f"{band}|{head}"

        slc_train = inner_train[(inner_train["band"] == band) & (inner_train["head"] == head)]
        slc_val   = inner_val[(inner_val["band"] == band) & (inner_val["head"] == head)]
        slc_test  = test[(test["band"] == band) & (test["head"] == head)]

        if len(slc_train) < 50:
            print(f"    [skip {tag}] only {len(slc_train)} train rows")
            continue

        X_train, feat_cols = _encode(slc_train, cat_cols, num_cols)
        y_train = slc_train["qty_weekly"].values
        X_val,   _ = _encode(slc_val, cat_cols, num_cols, feature_cols=feat_cols)
        y_val = slc_val["qty_weekly"].values
        X_test,  _ = _encode(slc_test, cat_cols, num_cols, feature_cols=feat_cols)
        y_test = slc_test["qty_weekly"].values

        print(f"    [train {tag}] n_train={len(slc_train)} n_val={len(slc_val)} n_test={len(slc_test)} features={len(feat_cols)}")

        slice_metrics = {"band": band, "head": head, "n_train": int(len(slc_train)),
                         "n_test": int(len(slc_test))}

        for q in cfg.QUANTILES:
            params = dict(cfg.XGB_QUANTILE_PARAMS)
            params["quantile_alpha"] = q
            n_est = params.pop("n_estimators")

            booster = xgb.train(
                params,
                xgb.DMatrix(X_train, label=y_train),
                num_boost_round=n_est,
                evals=[(xgb.DMatrix(X_val, label=y_val), "val")],
                early_stopping_rounds=cfg.DEMAND_EARLY_STOPPING_ROUNDS,
                verbose_eval=False,
            )

            # Conformal-style additive recalibration on val residuals so the
            # achieved quantile coverage matches the target q. The raw XGBoost
            # quantile predictor consistently undershoots interval widths on
            # our heavy-tailed weekly consumption distribution.
            val_pred_raw = booster.predict(xgb.DMatrix(X_val))
            offset = _calibrate_quantile(val_pred_raw, y_val, q)

            models[(band, head, q)] = {
                "booster": booster,
                "feature_cols": feat_cols,
                "calibration_offset": offset,
            }

            # Holdout eval — applies the offset
            if len(slc_test) > 0:
                pred = booster.predict(xgb.DMatrix(X_test)) + offset
                pred = np.maximum(0, pred)
                if q == 0.50:
                    nz = y_test > 1.0
                    if nz.sum() > 0:
                        mape = float(np.mean(np.abs((y_test[nz] - pred[nz]) / y_test[nz])) * 100)
                        mae = float(mean_absolute_error(y_test, pred))
                        slice_metrics["MAPE_p50_pct"] = round(mape, 2)
                        slice_metrics["MAE_p50"] = round(mae, 2)
                    else:
                        slice_metrics["MAPE_p50_pct"] = None
                        slice_metrics["MAE_p50"] = None
                resid = y_test - pred
                loss = np.maximum(q * resid, (q - 1) * resid).mean()
                slice_metrics[f"pinball_q{int(q*100)}"] = round(float(loss), 2)
                if q == 0.10:
                    slice_metrics["pct_below_p10"] = round(float((y_test < pred).mean() * 100), 1)
                if q == 0.90:
                    slice_metrics["pct_above_p90"] = round(float((y_test > pred).mean() * 100), 1)
                slice_metrics[f"calibration_offset_q{int(q*100)}"] = round(offset, 3)

        eval_records.append(slice_metrics)

    # Write evaluation report
    eval_path = cfg.REPORT_DIR / "evaluation_demand.json"
    with eval_path.open("w") as f:
        json.dump({
            "model_version": cfg.MODEL_VERSION,
            "n_slices_trained": len(eval_records),
            "train_end": cfg.TRAIN_END_DATE,
            "test_window": [cfg.TEST_START_DATE, cfg.TEST_END_DATE],
            "slices": eval_records,
        }, f, indent=2)
    print(f"  wrote {eval_path}")

    return models


def save(models: dict) -> None:
    """Save each booster as XGBoost JSON, plus a manifest of feature_cols and calibration offsets."""
    manifest = {}
    for (band, head, q), m in models.items():
        key = f"{band}__{head}__q{int(q*100)}"
        path = cfg.MODELS_DIR / f"demand_{key}.json"
        m["booster"].save_model(str(path))
        manifest[key] = {
            "band": band, "head": head, "quantile": q,
            "feature_cols": m["feature_cols"],
            "calibration_offset": m.get("calibration_offset", 0.0),
            "artifact": str(path.name),
        }
    manifest_path = cfg.MODELS_DIR / "demand_manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)
    print(f"  saved {len(models)} model artifacts + {manifest_path.name}")


def load() -> dict:
    """Inverse of save: reload models, feature schemas, and offsets from MODELS_DIR."""
    manifest = json.loads((cfg.MODELS_DIR / "demand_manifest.json").read_text())
    models = {}
    for key, info in manifest.items():
        booster = xgb.Booster()
        booster.load_model(str(cfg.MODELS_DIR / info["artifact"]))
        models[(info["band"], info["head"], info["quantile"])] = {
            "booster": booster,
            "feature_cols": info["feature_cols"],
            "calibration_offset": info.get("calibration_offset", 0.0),
        }
    return models


# ─────────────────────────────────────────────────────────────────────────────
# Predict: applies all 54 models to a feature panel
# ─────────────────────────────────────────────────────────────────────────────
def predict(panel: pd.DataFrame, models: dict) -> pd.DataFrame:
    """
    Apply quantile models to a (post, sku, week) feature panel.
    Returns one row per (post, sku, week) with p10/p50/p90.
    """
    out = []
    cat_cols = cfg.DEMAND_CATEGORICAL_COLS
    num_cols = cfg.DEMAND_NUMERIC_COLS

    for (band, head), sub in panel.groupby(["band", "head"]):
        keys_present = [(band, head, q) for q in cfg.QUANTILES if (band, head, q) in models]
        if not keys_present:
            continue

        # Use the P50 model's feature_cols as the schema (all three quantiles share it)
        feat_cols = models[(band, head, 0.50)]["feature_cols"]
        X, _ = _encode(sub, cat_cols, num_cols, feature_cols=feat_cols)
        D = xgb.DMatrix(X)

        preds = {}
        for q in cfg.QUANTILES:
            m = models[(band, head, q)]
            raw = m["booster"].predict(D)
            offset = m.get("calibration_offset", 0.0)
            preds[q] = np.maximum(0, raw + offset)

        chunk = sub[["post_id", "sku", "week", "band", "head"]].copy().reset_index(drop=True)
        chunk["p10"] = preds[0.10]
        chunk["p50"] = preds[0.50]
        chunk["p90"] = preds[0.90]
        out.append(chunk)

    return pd.concat(out, ignore_index=True)
