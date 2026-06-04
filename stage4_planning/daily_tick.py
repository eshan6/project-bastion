#!/usr/bin/env python3
"""
Project Bastion — Stage 4 daily tick (the scheduled orchestrator).

One entrypoint that runs the operational loop for a snapshot date:

  [--predict]  run Stage 3 prediction service for the date   (subprocess; Stage 3
               has its own `config` module, so it runs out-of-process to avoid a
               name clash with Stage 4's config)
               -> writes stage3_models/output/snapshot_<date>/*.parquet
  (always)     run Stage 4 planning over that snapshot
               -> writes .../snapshot_<date>/stage4/*.parquet + diagnostics
  [--load]     load plans + alerts into Supabase  (needs DATABASE_URL)

Design note: --predict requires the trained Stage 3 models AND the regenerated
stock_daily.parquet (gitignored; rebuilt deterministically from seed 42). Without
--predict the tick plans against the committed canonical snapshot, which is the
default CI path and needs no heavy regeneration.

Usage:
  python daily_tick.py                         # plan canonical snapshot only
  python daily_tick.py --date 2024-12-15       # explicit date
  python daily_tick.py --predict --date ...    # full Stage 3 -> Stage 4
  python daily_tick.py --load                  # also write to Supabase
"""
from __future__ import annotations
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

import config as cfg
import plan_service


def _stage3_dir(root: Path, date: str) -> Path:
    return root / "stage3_models" / "output" / f"snapshot_{date}"


def run_stage3_predict(root: Path, date: str) -> None:
    """Run Stage 3 predict_service for `date` as a subprocess."""
    s3 = root / "stage3_models"
    print(f"\n── [tick] Stage 3 predictions for {date} ──")
    proc = subprocess.run(
        [sys.executable, "predict_service.py", date],
        cwd=str(s3), capture_output=True, text=True)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"Stage 3 predict failed for {date} (rc={proc.returncode})")


def run_load(root: Path, snapshot_dir: Path) -> None:
    """Load Stage 4 outputs into Supabase as a subprocess (needs DATABASE_URL)."""
    if not os.environ.get("DATABASE_URL"):
        raise SystemExit("--load requested but DATABASE_URL is not set.")
    print(f"\n── [tick] Loading plans + alerts into Supabase ──")
    env = {**os.environ, "BASTION_ROOT": str(root), "BASTION_SNAPSHOT_DIR": str(snapshot_dir)}
    proc = subprocess.run([sys.executable, str(cfg.ROOT / "load_plans.py")],
                          capture_output=True, text=True, env=env)
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr)
        raise SystemExit(f"load_plans failed (rc={proc.returncode})")


def main():
    ap = argparse.ArgumentParser(description="Bastion Stage 4 daily tick")
    ap.add_argument("--date", default="2024-12-15", help="snapshot date YYYY-MM-DD")
    ap.add_argument("--horizon", type=int, default=cfg.PLANNING_HORIZON_DAYS,
                    help="planning horizon (days)")
    ap.add_argument("--predict", action="store_true",
                    help="run Stage 3 prediction service first (needs models + regenerated world)")
    ap.add_argument("--load", action="store_true",
                    help="load plans + alerts into Supabase (needs DATABASE_URL)")
    args = ap.parse_args()

    root = cfg.ROOT.parent          # repo root (sibling of stage2_world/stage3_models)
    t0 = time.time()
    print(f"══════ BASTION DAILY TICK  date={args.date}  horizon={args.horizon}d ══════")

    if args.predict:
        run_stage3_predict(root, args.date)

    snapshot_dir = _stage3_dir(root, args.date)
    if not snapshot_dir.exists():
        raise SystemExit(
            f"Snapshot {snapshot_dir} not found. Use --predict to generate it, "
            f"or point --date at an existing snapshot.")

    result = plan_service.run_plan(snapshot_dir, planning_horizon=args.horizon)

    if args.load:
        run_load(root, snapshot_dir)

    print(f"\n══════ TICK COMPLETE in {time.time()-t0:.1f}s ══════")
    print(f"  plans={result['n_plans']}  legs={result['n_legs']}  alerts={result['n_alerts']}")
    print(f"  outputs: {result['out_dir']}")


if __name__ == "__main__":
    main()
