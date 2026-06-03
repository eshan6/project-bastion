"""
Project Bastion — Stage 2 Generator: Orchestrator

Runs all generator modules in dependency order:
    world → weather → disruption → consumption → vehicles

Writes outputs to disk as Parquet (compact, schema-preserving).
Emits a validation report cross-checking every output against its
calibration source.

Usage:
    python generate.py [--seed 42] [--out_dir ./output]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

from config import START_DATE, END_DATE, N_DAYS, PROVENANCE
from world import build_world
from weather import generate_weather, validate_weather
from disruption import generate_pass_closures, validate_closures
from consumption import generate_consumption, validate_consumption
from vehicles import generate_vehicle_events, validate_vehicles
from stock import generate_stock, validate_stock


def write_parquet(df: pd.DataFrame, path: Path, name: str):
    """Write a DataFrame to Parquet, fall back to CSV if Parquet engine unavailable."""
    if len(df) == 0:
        print(f"  [skip] {name}: empty DataFrame")
        return
    try:
        df.to_parquet(path / f"{name}.parquet", index=False)
        print(f"  [ok]   {name}.parquet ({len(df):,} rows)")
    except (ImportError, ValueError):
        df.to_csv(path / f"{name}.csv", index=False)
        print(f"  [ok]   {name}.csv ({len(df):,} rows) — parquet engine not found, used CSV fallback")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out_dir", type=str, default="./output")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print(f"Project Bastion — Stage 2 Generator")
    print(f"Seed: {args.seed}")
    print(f"Horizon: {START_DATE} to {END_DATE} ({N_DAYS} days)")
    print(f"Output: {out_dir}")
    print()

    # --- Stage 1: world ---
    print("[1/6] Building world...")
    world = build_world(seed=args.seed)
    print(world.summary())
    print()

    # --- Stage 2.1: weather ---
    print("[2/6] Generating weather...")
    t1 = time.time()
    weather_df, wd_events_df = generate_weather(world, seed=args.seed)
    print(f"  {len(weather_df):,} weather rows, {len(wd_events_df)} WD events ({time.time()-t1:.1f}s)")

    # --- Stage 2.3: disruption (needs weather for snow events) ---
    print("[3/6] Generating pass closures...")
    t1 = time.time()
    closures_df, pass_status_df = generate_pass_closures(world, weather_df, seed=args.seed)
    print(f"  {len(closures_df)} closures, {len(pass_status_df):,} pass-day status rows ({time.time()-t1:.1f}s)")

    # --- Stage 2.2: consumption (needs weather + pass status for isolation) ---
    print("[4/6] Generating consumption...")
    t1 = time.time()
    consumption_df, tempo_df = generate_consumption(world, weather_df, pass_status_df, seed=args.seed)
    print(f"  {len(consumption_df):,} consumption rows, {len(tempo_df)} tempo rows ({time.time()-t1:.1f}s)")

    # --- Stage 2.4: vehicle deadline events ---
    print("[5/6] Generating vehicle events...")
    t1 = time.time()
    vehicle_events_df = generate_vehicle_events(world, pass_status_df, seed=args.seed)
    print(f"  {len(vehicle_events_df)} vehicle deadline events ({time.time()-t1:.1f}s)")

    # --- Stage 2.5: stock dynamics (needs consumption + pass status + weather) ---
    # The forward accounting identity: opening + AWS + routine - consumption
    # - spoilage = closing. This is the layer that makes a stockout
    # predictable — without a running stock balance there is nothing for
    # the FSP to forecast. Includes a discarded 2021 warm-up year so the
    # 2022 opening balances are a genuine steady state, not hand-seeded.
    print("[6/6] Generating stock dynamics...")
    t1 = time.time()
    stock_df, aws_plan_df = generate_stock(world, consumption_df, pass_status_df,
                                           weather_df, seed=args.seed)
    print(f"  {len(stock_df):,} stock-ledger rows, {len(aws_plan_df):,} AWS-plan rows ({time.time()-t1:.1f}s)")
    print()

    # --- Persist outputs ---
    print("Writing outputs...")
    write_parquet(world.posts,    out_dir, "posts")
    write_parquet(world.routes,   out_dir, "routes")
    write_parquet(world.vehicles, out_dir, "vehicles")
    write_parquet(world.skus,     out_dir, "skus")
    write_parquet(weather_df,     out_dir, "weather_daily")
    write_parquet(wd_events_df,   out_dir, "wd_events")
    write_parquet(closures_df,    out_dir, "pass_closures")
    write_parquet(pass_status_df, out_dir, "pass_status_daily")
    write_parquet(consumption_df, out_dir, "consumption_daily")
    write_parquet(tempo_df,       out_dir, "tempo_daily")
    write_parquet(vehicle_events_df, out_dir, "vehicle_events")
    write_parquet(stock_df,       out_dir, "stock_daily")
    write_parquet(aws_plan_df,    out_dir, "aws_plan")
    print()

    # --- Validation report ---
    print("=" * 70)
    print("VALIDATION REPORT")
    print("=" * 70)
    report = {
        "seed": args.seed,
        "horizon_days": N_DAYS,
        "rows_total": (len(weather_df) + len(closures_df) + len(consumption_df) +
                       len(vehicle_events_df) + len(pass_status_df) + len(tempo_df) +
                       len(stock_df) + len(aws_plan_df)),
        "weather": validate_weather(weather_df, world),
        "disruption": validate_closures(closures_df),
        "consumption": validate_consumption(consumption_df, world),
        "vehicles": validate_vehicles(vehicle_events_df, world),
        "stock": validate_stock(stock_df, aws_plan_df, world),
        "provenance": PROVENANCE,
    }

    def _print(d, indent=0):
        for k, v in d.items():
            if isinstance(v, dict):
                print("  " * indent + f"{k}:")
                _print(v, indent + 1)
            elif isinstance(v, list):
                print("  " * indent + f"{k}: {v}")
            else:
                print("  " * indent + f"{k}: {v}")

    _print(report)

    # Persist report
    # Convert any non-JSON-friendly types (numpy floats, dates) to str
    def _coerce(o):
        if isinstance(o, dict):
            return {k: _coerce(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_coerce(x) for x in o]
        try:
            json.dumps(o)
            return o
        except TypeError:
            return str(o)

    with open(out_dir / "validation_report.json", "w") as f:
        json.dump(_coerce(report), f, indent=2)
    print()
    print(f"Validation report written to {out_dir / 'validation_report.json'}")
    print(f"Total runtime: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
