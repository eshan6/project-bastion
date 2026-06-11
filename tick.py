"""
Project Bastion — Daily Tick Orchestrator (#8, v1.0)

One tick = the masterplan's Component-5 loop, against a MOVING world:

  1. stage2_world/advance.py   --to sim_date+BUFFER --materialize live_data/
  2. stage3_models/predict_service.py  <sim_date>      forecasts + risk
  3. stage4_planning/plan_service.py   <snapshot_dir>   plans + alerts

Each stage runs as a SUBPROCESS in its own directory — the three stages each
have a module named `config`, and subprocess isolation is what keeps them
from colliding (the same reason the CLI path always worked).

The world is advanced FORECAST_BUFFER_DAYS (14) past the presentation date
because Stage 3's demand panel treats same-week weather as forecast input
(documented in features.py): a live deployment consumes weather forecasts;
the synthetic world supplies them by generating physics slightly ahead of
the view cursor.

Usage:
  python tick.py --to 2025-02-28     # advance sim to a date and plan it
  python tick.py --next              # advance exactly one day and plan
  python tick.py --replan            # re-plan current sim date, no advance
  python tick.py --status            # print current sim date and exit

All outputs land in stage3_models/output/snapshot_<date>/ exactly like the
canonical batch path. Deterministic: same target date ⇒ same plans.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORECAST_BUFFER_DAYS = 14
LIVE_DATA_DIR = ROOT / "live_data"
STATE_DIR = ROOT / "stage2_world" / "world_state"
CANONICAL_END = date(2024, 12, 31)


def current_sim_date() -> date:
    """Presentation date = stepper date − buffer, floored at the boundary."""
    state_p = STATE_DIR / "state.json"
    if not state_p.exists():
        return CANONICAL_END
    sim = date.fromisoformat(json.loads(state_p.read_text())["sim_date"])
    return max(CANONICAL_END, sim - timedelta(days=FORECAST_BUFFER_DAYS))


def _run(cmd: list, cwd: Path, label: str, verbose: bool) -> None:
    env = {**os.environ, "BASTION_DATA_DIR": str(LIVE_DATA_DIR)}
    r = subprocess.run([sys.executable, *cmd], cwd=cwd, env=env,
                       capture_output=True, text=True)
    if verbose and r.stdout:
        print(r.stdout[-1800:])
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed:\n{r.stderr[-2500:]}")


def run_tick(target: date, replan_only: bool = False, verbose: bool = True) -> dict:
    t0 = time.time()
    if not replan_only:
        _run(["advance.py",
              "--to", (target + timedelta(days=FORECAST_BUFFER_DAYS)).isoformat(),
              "--materialize", str(LIVE_DATA_DIR)],
             ROOT / "stage2_world", "stage2 advance", verbose)
    elif not (LIVE_DATA_DIR / "stock_daily.parquet").exists():
        _run(["advance.py", "--to",
              (target + timedelta(days=FORECAST_BUFFER_DAYS)).isoformat(),
              "--materialize", str(LIVE_DATA_DIR)],
             ROOT / "stage2_world", "stage2 advance", verbose)

    _run(["predict_service.py", target.isoformat()],
         ROOT / "stage3_models", "stage3 predict", verbose)
    snap_dir = ROOT / "stage3_models" / "output" / f"snapshot_{target.isoformat()}"

    _run(["plan_service.py", str(snap_dir)],
         ROOT / "stage4_planning", "stage4 plan", verbose)

    return {"sim_date": target.isoformat(), "snapshot_dir": str(snap_dir),
            "elapsed_s": round(time.time() - t0, 1)}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--to", type=str, help="advance sim to date and plan it")
    g.add_argument("--next", action="store_true", help="advance one day and plan")
    g.add_argument("--replan", action="store_true", help="re-plan current date")
    g.add_argument("--status", action="store_true", help="print sim date and exit")
    args = ap.parse_args()

    cur = current_sim_date()
    if args.status:
        print(f"sim_date: {cur}")
        sys.exit(0)
    tgt = (date.fromisoformat(args.to) if args.to
           else cur + timedelta(days=1) if args.next
           else cur)
    info = run_tick(tgt, replan_only=args.replan)
    print(f"\n✓ tick complete: sim {info['sim_date']} in {info['elapsed_s']}s")
    print(f"  snapshot: {info['snapshot_dir']}")
