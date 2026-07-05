"""
Project Bastion — Model Service (HF Space app, v2.2)

Serves the FSP single-file dashboard's EXISTING contract, against a world
that is now LIVE (advances one sim day per real day, plus manual /advance).

CONTRACT (unchanged from the UI's perspective):
  GET /snapshot?date=YYYY-MM-DD&at_risk_only=...
        → {stockout_risk:[rows], vehicle_reliability:[rows],
           counts:{demand,route,risk}, sim_date}
  GET /optimize?date=YYYY-MM-DD&horizon=H
        → {plans:[rows], legs:[rows], non_road_legs:[rows],
           shortfalls:[rows], diagnostics:{...planning_diagnostics.json}}
        (horizon accepted for compatibility; the v1.1+ AWS rebuild made the
         stocking horizon doctrine-driven, so it no longer re-parameterises
         the solve)
  GET /series?post=&sku=  → {daily:[stock_daily rows]}

NEW (the live world):
  GET  /health    boot status (the world fast-forwards on boot)
  GET  /sim       sim date, tempo, active closures
  POST /advance   {"days": N} manual advance + replan

WARGAME (v2.2 — wires stage4_planning/scenarios.py into the service):
  POST /whatif       {date, scenario, mode} → full frontier re-solved under a
                     world modification, plus per-objective diff_vs_baseline.
                     scenario keys: pass_closures {pass:0..1},
                     demand_multiplier (float | {post_id:float}),
                     depot_stock_factor {depot_id:0..1}, vehicle_loss_pct 0..100.
                     mode: "peacetime" | "wartime". Solves LIVE in-process
                     (two full solve_all passes, ~30–60 s) — this is not a
                     cached-snapshot read like /optimize.
  POST /custom_plan  {date, items:[{post_id,sku_id,qty}], name} → re-optimize
                     routing/vehicles/schedule for a commander-edited manifest;
                     quantities clamped to depot stock + road feasibility
                     (clamps itemised in clamped_requests).

Any requested date that has no cached snapshot is computed on demand via the
tick (~25 s) — same UX as the old on-request model, but now the computable
range extends past 2024-12-31 into the deterministic continuation.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
SNAP_ROOT = ROOT / "stage3_models" / "output"
STATE_DIR = ROOT / "stage2_world" / "world_state"
LIVE_DATA = ROOT / "live_data"

# ── stage4 wargame engine bootstrap ─────────────────────────────────────────
# scenarios.py / optimizer.py / inputs.py / config.py under stage4_planning use
# bare top-level imports of each other ("import optimizer", "from inputs import
# ...").  They are NOT a package, so we put that dir on sys.path and import the
# scenario engine lazily inside the route handlers (keeps boot fast and avoids
# import-time failures taking down the whole service if stage4 deps shift).
STAGE4_DIR = ROOT / "stage4_planning"
if str(STAGE4_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE4_DIR))

_scen_mod = None


def _scenarios():
    """Import stage4_planning/scenarios.py on first use. Raises 503 (not 500)
    if the engine cannot load, so the rest of the service stays up."""
    global _scen_mod
    if _scen_mod is None:
        try:
            import scenarios as _s  # noqa: PLC0415
            _scen_mod = _s
        except Exception as e:  # noqa: BLE001
            raise HTTPException(503, detail=f"wargame engine unavailable: {str(e)[-600:]}")
    return _scen_mod

CANONICAL_END = date(2024, 12, 31)
SIM_EPOCH_REAL = date.fromisoformat(os.environ.get("SIM_EPOCH_REAL", "2026-06-15"))
SIM_EPOCH_SIM = date.fromisoformat(os.environ.get("SIM_EPOCH_SIM", "2025-01-15"))
MAX_MANUAL_DAYS = int(os.environ.get("MAX_MANUAL_DAYS", "30"))
IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Bastion Model Service", version="2.2")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                   allow_headers=["*"])

_lock = asyncio.Lock()
_status = {"sim_date": None, "boot": "starting", "last_tick_s": None,
           "manual_offset_days": 0, "error": None}


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────
def _clean(o):
    if isinstance(o, dict):
        # Drop keys whose value is null. Parquet round-trips a dict column
        # (e.g. platform_commitment) into a struct spanning the UNION of keys
        # across all rows, back-filling absent keys with None. Those null
        # struct members are not real data and crash naive consumers that
        # map over Object.entries expecting populated objects.
        return {k: _clean(v) for k, v in o.items() if v is not None}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        o = float(o)
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def _records(df: pd.DataFrame) -> list:
    for c in df.columns:
        if str(df[c].dtype).startswith("datetime") or c in ("date", "deadline_date",
                                                             "return_date", "week",
                                                             "depart_date"):
            df[c] = df[c].astype(str).str.slice(0, 10)
    return _clean(df.to_dict("records"))


def _snap_dir(d: date) -> Path:
    return SNAP_ROOT / f"snapshot_{d.isoformat()}"


def _anchored_sim_date() -> date:
    real_today = datetime.now(IST).date()
    anchored = SIM_EPOCH_SIM + (real_today - SIM_EPOCH_REAL)
    anchored = max(anchored, CANONICAL_END + timedelta(days=1))
    return anchored + timedelta(days=_status["manual_offset_days"])


def _run_tick_sync(target: date) -> None:
    t0 = time.time()
    r = subprocess.run([sys.executable, "tick.py", "--to", target.isoformat()],
                       cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-2000:] or r.stdout[-2000:])
    _status["last_tick_s"] = round(time.time() - t0, 1)


def _snapshot_complete(d: date) -> bool:
    sd = _snap_dir(d)
    return (sd / "stockout_risk.parquet").exists() and \
           (sd / "stage4" / "resupply_plans.parquet").exists()


async def _ensure_snapshot(d: date) -> None:
    """Compute predictions+plans for a date if not cached. For dates at/past
    the live frontier this advances the world too; for historical dates the
    tick re-plans against existing history (no world advance)."""
    if _snapshot_complete(d):
        return
    async with _lock:
        if _snapshot_complete(d):
            return
        # tick --to handles both cases: historical dates re-plan against
        # existing history (world advance is a no-op); future dates advance
        # the world first. Deterministic either way.
        frontier = date.fromisoformat(_status["sim_date"]) if _status["sim_date"] else CANONICAL_END
        try:
            await asyncio.to_thread(_run_tick_sync, d)
        except Exception as e:                                   # noqa: BLE001
            # A bare RuntimeError here previously escaped as an opaque 500 with
            # no detail reaching the client. Convert to a structured 500 that
            # carries the tail of the tick's stderr so the failure is
            # diagnosable from the browser / logs without SSH-ing the Space.
            _status["error"] = str(e)[-800:]
            raise HTTPException(
                500, detail={"stage": "on-demand tick",
                             "date": d.isoformat(),
                             "cause": str(e)[-1200:]})
        if d > frontier:
            _status["sim_date"] = d.isoformat()


@app.on_event("startup")
async def _boot():
    async def boot_task():
        try:
            tgt = _anchored_sim_date()
            async with _lock:
                await asyncio.to_thread(_run_tick_sync, tgt)
            _status["sim_date"] = tgt.isoformat()
            _status["boot"] = "ready"
        except Exception as e:                                   # noqa: BLE001
            _status["boot"] = "error"
            _status["error"] = str(e)[-800:]
    asyncio.create_task(boot_task())
    asyncio.create_task(_scheduler())


async def _scheduler():
    while True:
        await asyncio.sleep(3600)
        try:
            tgt = _anchored_sim_date()
            if _status["boot"] == "ready" and (
                    _status["sim_date"] is None or tgt.isoformat() > _status["sim_date"]):
                async with _lock:
                    await asyncio.to_thread(_run_tick_sync, tgt)
                _status["sim_date"] = tgt.isoformat()
        except Exception as e:                                   # noqa: BLE001
            _status["error"] = str(e)[-800:]


def _require_ready() -> date:
    if _status["boot"] != "ready" or not _status["sim_date"]:
        raise HTTPException(503, detail={"boot": _status["boot"], "error": _status["error"],
                                          "hint": "world is fast-forwarding; retry shortly"})
    return date.fromisoformat(_status["sim_date"])


def _world_state() -> dict:
    p = STATE_DIR / "state.json"
    if not p.exists():
        return {}
    s = json.loads(p.read_text())
    return {"tempo": s.get("tempo"), "active_closures": s.get("active_closures", [])}


# ─────────────────────────────────────────────────────────────────────────────
# routes — existing FSP contract
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/snapshot")
async def snapshot(date_: str | None = None, at_risk_only: bool = False, date: str | None = None):  # noqa: A002
    sim = _require_ready()
    d = pd.Timestamp(date or date_ or sim).date()
    await _ensure_snapshot(d)
    sd = _snap_dir(d)
    risk = pd.read_parquet(sd / "stockout_risk.parquet")
    if at_risk_only:
        risk = risk[risk["predicted_status"] != "ok"]
    veh = pd.read_parquet(sd / "vehicle_reliability.parquet")
    n_dem = len(pd.read_parquet(sd / "demand_forecasts.parquet")) \
        if (sd / "demand_forecasts.parquet").exists() else 0
    n_rt = len(pd.read_parquet(sd / "route_predictions.parquet")) \
        if (sd / "route_predictions.parquet").exists() else 0
    return {"stockout_risk": _records(risk),
            "vehicle_reliability": _records(veh),
            "counts": {"demand": n_dem, "route": n_rt, "risk": len(risk)},
            "sim_date": _status["sim_date"]}


@app.get("/optimize")
async def optimize(date_: str | None = None, horizon: int | None = None, date: str | None = None):  # noqa: A002
    sim = _require_ready()
    d = pd.Timestamp(date or date_ or sim).date()
    await _ensure_snapshot(d)
    s4 = _snap_dir(d) / "stage4"
    plans = pd.read_parquet(s4 / "resupply_plans.parquet")
    legs = pd.read_parquet(s4 / "resupply_plan_legs.parquet")
    nonroad_p = s4 / "resupply_nonroad_legs.parquet"
    nonroad = pd.read_parquet(nonroad_p) if nonroad_p.exists() else pd.DataFrame()
    short = pd.read_parquet(s4 / "resupply_shortfalls.parquet")
    diag = json.loads((s4 / "planning_diagnostics.json").read_text())
    return {"plans": _records(plans), "legs": _records(legs),
            "non_road_legs": _records(nonroad) if len(nonroad) else [],
            "shortfalls": _records(short),
            "diagnostics": _clean(diag),
            "sim_date": _status["sim_date"],
            "note_horizon": "stocking horizon is doctrine-driven (AWS) since v1.1; "
                             "the horizon query param is accepted but does not "
                             "re-parameterise the solve"}


@app.get("/series")
def series(post: str, sku: str):
    _require_ready()
    src = (LIVE_DATA / "stock_daily.parquet") if (LIVE_DATA / "stock_daily.parquet").exists() \
        else ROOT / "stage2_world" / "data" / "stock_daily.parquet"
    df = pd.read_parquet(src, columns=["post_id", "sku", "date", "opening_stock",
                                        "closing_stock", "consumption", "status",
                                        "days_of_cover"])
    sub = df[(df["post_id"] == post) & (df["sku"] == sku)].sort_values("date")
    return {"daily": _records(sub)}


# ─────────────────────────────────────────────────────────────────────────────
# routes — live world (new)
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    # BUILD_COMMIT is written by the Dockerfile at image-build time (the short
    # hash of the v3 commit that was cloned). Its PRESENCE proves the container
    # was built by the current clone-from-GitHub Dockerfile; its VALUE says
    # exactly which commit is serving. This exists because a stray Space-local
    # app.py once shadowed the cloned repo for multiple sessions undetected.
    bc = ROOT / "BUILD_COMMIT"
    commit = bc.read_text().strip() if bc.exists() else None
    return {"ok": _status["boot"] == "ready", "build_commit": commit, **_status}


@app.get("/sim")
def sim():
    return {**_status, "anchored_date": _anchored_sim_date().isoformat(),
            "canonical_end": CANONICAL_END.isoformat(), "world": _world_state(),
            "note": "one sim day per real day; POST /advance for manual steps"}


class AdvanceReq(BaseModel):
    days: int = 1


@app.post("/advance")
async def advance(req: AdvanceReq):
    d = _require_ready()
    if not (1 <= req.days <= MAX_MANUAL_DAYS):
        raise HTTPException(400, detail=f"days must be 1..{MAX_MANUAL_DAYS}")
    if _lock.locked():
        raise HTTPException(409, detail="a tick is already running; retry shortly")
    target = d + timedelta(days=req.days)
    _status["manual_offset_days"] += req.days
    try:
        async with _lock:
            await asyncio.to_thread(_run_tick_sync, target)
        _status["sim_date"] = target.isoformat()
    except Exception as e:                                       # noqa: BLE001
        _status["manual_offset_days"] -= req.days
        raise HTTPException(500, detail=str(e)[-1500:])
    return {"sim_date": _status["sim_date"], "advanced_days": req.days,
            "tick_seconds": _status["last_tick_s"],
            "note": "manual offset resets if the Space restarts (ephemeral storage)"}


_PLAN_NS = uuid.uuid5(uuid.NAMESPACE_URL, "bastion/stage4/resupply_plan")


def _plans_to_list(plans_dict: dict, snap_date: str, tag: str = "whatif") -> list:
    """solve_all() returns {objective: plan_dict}; the FSP dashboard's PlanCards
    consumes an ARRAY of plans each carrying plan_id + objective (the same shape
    /optimize serves). Mirror plan_service.py's plan_id convention, namespaced
    with `tag` so scenario plans never collide with the cached baseline plans.
    Order preserved as the solver emitted it (deterministic)."""
    out = []
    for obj, res in plans_dict.items():
        pid = str(uuid.uuid5(_PLAN_NS, f"{tag}:{snap_date}:{obj}"))
        out.append({"plan_id": pid, "objective": obj, **res})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# routes — wargame / what-if (v2.2)
#
# These re-solve the optimizer LIVE against a modified world (scenarios.py),
# rather than reading a cached snapshot. The snapshot dir must already exist
# (predictions + baseline stage4 outputs) — we _ensure_snapshot first, exactly
# like /optimize, so the forecasts/route-probabilities the scenario perturbs
# are present. The solve itself then runs in-thread.
# ─────────────────────────────────────────────────────────────────────────────
class WhatIfReq(BaseModel):
    date: str | None = None
    scenario: dict | None = None
    mode: str = "peacetime"
    mode_overrides: dict | None = None


class CustomPlanReq(BaseModel):
    date: str | None = None
    items: list = []
    scenario: dict | None = None
    mode: str = "peacetime"
    mode_overrides: dict | None = None
    name: str = "custom"


@app.post("/whatif")
async def whatif(req: WhatIfReq):
    sim = _require_ready()
    d = pd.Timestamp(req.date or sim).date()
    await _ensure_snapshot(d)                 # forecasts + baseline stage4 must exist
    scen = _scenarios()
    snap = _snap_dir(d)
    if _lock.locked():
        raise HTTPException(409, detail="a tick is running; retry shortly")
    try:
        async with _lock:                     # serialise heavy solves on 2-vCPU Space
            res = await asyncio.to_thread(
                scen.run_whatif, str(snap), req.scenario, req.mode, req.mode_overrides)
    except HTTPException:
        raise
    except Exception as e:                    # noqa: BLE001
        raise HTTPException(500, detail=str(e)[-1500:])
    # solve_all returns {objective: plan}; the dashboard maps over an array.
    snap_iso = d.isoformat()
    if isinstance(res.get("plans"), dict):
        res["plans"] = _plans_to_list(res["plans"], snap_iso, tag="whatif")
    if isinstance(res.get("baseline"), dict):
        res["baseline"] = _plans_to_list(res["baseline"], snap_iso, tag="baseline")
    res["sim_date"] = _status["sim_date"]
    res["snapshot_date"] = snap_iso
    return _clean(res)


@app.post("/custom_plan")
async def custom_plan(req: CustomPlanReq):
    sim = _require_ready()
    d = pd.Timestamp(req.date or sim).date()
    if not req.items:
        raise HTTPException(400, detail="items is empty; send [{post_id,sku_id,qty}, ...]")
    await _ensure_snapshot(d)
    scen = _scenarios()
    snap = _snap_dir(d)
    if _lock.locked():
        raise HTTPException(409, detail="a tick is running; retry shortly")
    try:
        async with _lock:
            res = await asyncio.to_thread(
                scen.run_custom, str(snap), req.items, req.scenario,
                req.mode, req.mode_overrides, req.name)
    except HTTPException:
        raise
    except Exception as e:                    # noqa: BLE001
        raise HTTPException(500, detail=str(e)[-1500:])
    res["sim_date"] = _status["sim_date"]
    res["snapshot_date"] = d.isoformat()
    return _clean(res)
