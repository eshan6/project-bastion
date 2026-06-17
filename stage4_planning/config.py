"""
Project Bastion — Stage 4 config (planning / optimization layer, v1.1)

Stage 4 turns Stage 3's prediction objects into *actions*:
  - resupply plans   (OR-Tools MIP, 4 ranked objectives)  -> resupply_plan(_leg)
  - alerts           (3 types, from the 3 Stage 3 outputs)  -> alert

Same discipline as Stages 2-3: every numeric choice is either anchored to a
public source or explicitly flagged SYNTHETIC-INFERRED.

──────────────────────────────────────────────────────────────────────────────
v1.1 — Advance Winter Stocking (AWS) rebuild.  WHY THIS CHANGED:
──────────────────────────────────────────────────────────────────────────────
v1.0 defined a post's deficit as (21-day P90 target − current_stock). Run against
the seed-42 world on 15-Dec, that produced plans containing ONLY Fresh Meat: every
other SKU sat at 4–7× of a 21-day target because forward posts hold deep pre-winter
reserves, so their deficit clipped to zero. Only the one perishable (Fresh Meat,
7-day shelf life) was ever thin enough to surface. The optimizer was correct; the
deficit *definition* was wrong.

The real decision these posts model is NOT "what runs out in two weeks." It is
Advance Winter Stocking: forward posts in Eastern Ladakh are road-cut for ~5–6
months a winter (winter declared 15-Nov; passes shut Nov→onwards). AWS pre-positions
"everything a soldier needs to last the whole year plus reserves" BEFORE the road
shuts. Public anchors:
  - ThePrint (20-Sep-2024): winter declared 15-Nov, stock for "the next six months."
  - ETV Bharat / The Week (2020): "six-month period when the Ladakh roads are cut off";
    AWS = procurement+transport of every commodity for that period.
  - The Tribune (Jan-2025): AWS stocks forward posts "to last for the whole year
    besides some reserves for unforeseen operational requirements."

So the planning target is daily_p90 × (days_to_closure + ISOLATION_DURATION + RESERVE),
gated by isolation probability, and capped by each SKU's shelf life (you cannot
pre-position 120 days of fresh meat — public record: switched to frozen/tinned in 2015).
Perishable shortfall is routed into the tinned substitute; any residual the depot
genuinely cannot cover is surfaced as an explicit shortfall, never silently dropped.

Design stance (unchanged, now actually enforced in code):
  We plan on WORST-CASE (P90) demand and dispatch ANTICIPATORILY. Demand P90 and
  pass-closure probability share a driver (winter / western disturbances), so a
  post's worst consumption coincides with its least-reachable window. Stage 3 hands
  us p90 + isolation_probability precisely so we plan against the bad case.
"""
from pathlib import Path
import os

# ─────────────────────────────────────────────────────────────────────────────
# Paths — Stage 4 reads a Stage 3 snapshot output dir + Stage 2 topology
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
DATA_DIR = Path(os.environ.get("BASTION_DATA_DIR", ROOT.parent / "stage2_world" / "data"))
STAGE3_OUTPUT_DIR = Path(os.environ.get("BASTION_STAGE3_OUTPUT",
                                        ROOT.parent / "stage3_models" / "output"))
OUTPUT_DIR = ROOT / "output"
REPORT_DIR = ROOT / "reports"
for _d in (OUTPUT_DIR, REPORT_DIR):
    _d.mkdir(exist_ok=True, parents=True)

MODEL_VERSION = "stage4-v3.0"
DATA_SNAPSHOT_SEED = 42

# ─────────────────────────────────────────────────────────────────────────────
# Planning window — Advance Winter Stocking
# ─────────────────────────────────────────────────────────────────────────────
# The deficit a post must close BEFORE its road shuts is enough to consume through:
#   (a) the time until the road actually closes              -> days_to_closure
#   (b) the road-closed isolation period itself              -> ISOLATION_DURATION
#   (c) an operational reserve on top                        -> RESERVE_DAYS
#
# ISOLATION_DURATION = 120: a conservative mid-range of the publicly reported 5–6
# month (≈150–180d) road-closed season. 120d (4 months) is deliberately below the
# headline figure so the target is defensible rather than maximal. ANCHORED to the
# AWS literature; the specific 120 vs 150 choice is a documented conservative call.
ISOLATION_DURATION_DAYS = 120

# Operational reserve carried on top of the closure period (unforeseen ops / calamity).
# 7d mirrors Stage 2/3 rationing threshold (cover < 7d => rationing). ANCHORED to that.
RESERVE_DAYS = 7

# days_to_closure: how long the inbound path stays usable before it shuts for winter.
# Derived per post from route predictions (first horizon at which path availability
# falls below DAYS_TO_CLOSURE_PAVAIL). If the path never crosses it inside the route
# horizon, we use this default (assume the road holds at least this long). The route
# models only predict to 14d, so this is necessarily a SYNTHETIC-INFERRED bridge
# between the 14d prediction horizon and the multi-month stocking horizon.
DAYS_TO_CLOSURE_DEFAULT = 14
DAYS_TO_CLOSURE_PAVAIL = 0.20      # path treated as "shut for the season" below this

# Planning horizon used for reading Stage-3 risk rows (which horizon's P90 rate we
# annualize from). Kept at 14 — the longest route-prediction horizon and the rate
# we trust most. The STOCKING window above is what changed, not the rate source.
PLANNING_HORIZON_DAYS = 14

# ─────────────────────────────────────────────────────────────────────────────
# Anticipatory trigger (the gate)  — isolation_probability decides IF we stock
# ─────────────────────────────────────────────────────────────────────────────
# A post is stocked to AWS scale only if it is actually going to be cut off. Posts
# that stay reachable are NOT force-stocked to 4-month scale (the road can resupply
# them normally). isolation_probability is Stage 3's composed P(post unreachable)
# at the route horizon. >= this threshold => anticipatory stocking engages.
# 0.50 = "more likely than not to be isolated." SYNTHETIC-INFERRED operational gate.
ISOLATION_GATE = 0.50

# A post also enters scope on a fired tier alert or a bad worst-case status, even
# below the isolation gate (a post already starving gets resupplied regardless of
# whether it is about to be cut off).
ACTIONABLE_WORSTCASE_STATUSES = {"stockout", "rationing"}

# ─────────────────────────────────────────────────────────────────────────────
# Shelf-life cap + perishable substitution
# ─────────────────────────────────────────────────────────────────────────────
# You cannot pre-position ISOLATION_DURATION days of a perishable. The stocking
# window for any SKU is capped at its shelf_life_days (read live from skus.parquet,
# NOT hardcoded). Demand beyond shelf life for a perishable is routed into a
# longer-life substitute below. Public anchor: Army switched forward-post non-veg
# from live animals to frozen/tinned contracts (~2015) precisely because fresh
# cannot be stocked through the closed season.
#
# Substitution map: perishable_sku -> (substitute_sku, units_substitute_per_unit_orig).
# Fresh Meat (RAT-005, 7d) -> Tinned Rations (RAT-006, 730d). Ratio 1.0 is a
# SYNTHETIC-INFERRED nutritional-equivalence placeholder (1 kg fresh ≈ 1 tin-unit of
# protein cover); replace with a real ration-scale equivalence when available.
PERISHABLE_SHELF_CAP_ENABLED = True
SUBSTITUTION_MAP = {
    "RAT-005": {"substitute": "RAT-006", "ratio": 1.0,
                "note": "Fresh Meat beyond shelf life -> Tinned Rations (frozen/tinned "
                        "AWS practice, ~2015 contract shift). ratio SYNTHETIC-INFERRED."},
}

# ─────────────────────────────────────────────────────────────────────────────
# Per-SKU shipping weight  (kg per consumption-unit) — unchanged from v1.0
# ─────────────────────────────────────────────────────────────────────────────
SKU_WEIGHT_KG = {
    "RAT-001": 1.00, "RAT-002": 1.00, "RAT-003": 1.00, "RAT-004": 0.92,
    "RAT-005": 1.00, "RAT-006": 0.40, "RAT-007": 1.00, "RAT-008": 0.001,
    "POL-001": 0.81, "POL-002": 0.84, "POL-003": 0.74, "POL-004": 0.90,
    "AMM-001": 0.0123, "AMM-002": 0.0250, "AMM-003": 0.2300, "AMM-004": 4.2000,
    "AMM-005": 0.5000,
    "CLO-001": 1.80, "CLO-002": 1.50, "CLO-003": 0.20, "CLO-004": 2.50,
    "MED-001": 0.0005, "MED-002": 0.0500, "MED-003": 10.000, "MED-004": 1.0000,
    "MED-005": 0.1000,
    "ENG-001": 12.00, "ENG-002": 15.00, "ENG-003": 0.05, "ENG-004": 0.50,
}
HEAD_WEIGHT_FALLBACK_KG = {"Rations": 1.0, "POL": 0.85, "Ammunition": 0.05,
                           "Clothing": 1.5, "Medical": 0.5, "Engineer": 5.0}

# ─────────────────────────────────────────────────────────────────────────────
# Vehicle class economics  (all SYNTHETIC-INFERRED) — unchanged from v1.0
# ─────────────────────────────────────────────────────────────────────────────
VEHICLE_CLASS_FUEL_COST_PER_KM = {
    "Tata-LPTA": 18.0, "Stallion-4x4": 24.0, "Stallion-6x6": 30.0, "BharatBenz-HD": 38.0,
}
VEHICLE_CLASS_SPEED_KMPH = {
    "Tata-LPTA": 25.0, "Stallion-4x4": 24.0, "Stallion-6x6": 22.0, "BharatBenz-HD": 20.0,
}
VEHICLE_FIXED_DISPATCH_COST = 5000.0
DEFAULT_FUEL_COST_PER_KM = 25.0
DEFAULT_SPEED_KMPH = 23.0
PATH_DELAY_HOURS_AT_FULL_CLOSURE = 72.0

# ─────────────────────────────────────────────────────────────────────────────
# Feasibility + risk
# ─────────────────────────────────────────────────────────────────────────────
PATH_FEASIBILITY_MIN = 0.05
ROUTE_HORIZONS_DAYS = [1, 3, 7, 14]
VEHICLE_HORIZON_DAYS = 7

# ─────────────────────────────────────────────────────────────────────────────
# Objectives — v3.0 ε-constraint frontier (REPLACES the v1/v2 four-label set)
# ─────────────────────────────────────────────────────────────────────────────
# WHY THE OLD SET WAS RETIRED (measured on seed-42 / 15-Dec, v2.0):
#   min_cost / min_time / min_risk / balanced produced four plans within 1.1% on
#   cost, 8% on makespan, byte-identical coverage, and aggregate_risk pinned at
#   1.0 in all four. Root causes, all verified:
#     1. Phase-1 allocation ignored the objective → identical manifests.
#     2. 84 of 90 convoys were objective-blind full-truck shuttles; only 4.9% of
#        tonnage ever reached the objective-aware VRP.
#     3. The fleet has NO cost-vs-time tradeoff (cheapest class is also fastest),
#        so min_cost and min_time were the same objective.
#     4. Each post has exactly one path, so min_risk had nothing to choose.
#   min_time is therefore REMOVED until a real time axis exists (multi-modal /
#   multi-day dispatch). Honest > decorative.
#
# THE v3.0 SET — three plans that are different COMMITMENTS, not different labels:
#   full_coverage : ship everything reachable (lexicographic coverage ≫ cost).
#                   The doctrine-shaped maximal plan; reference point for floors.
#   min_cost      : cheapest plan that still covers ≥ COVERAGE_FLOOR_FRAC of the
#                   full_coverage tonnage per depot (Tier-1 never sacrificed).
#                   Drops the most expensive marginal tonnage; cheapest ₹/t·km
#                   vehicle mix.
#   min_exposure  : minimize tier-weighted EXPECTED SHORTFALL — kg that fail to
#                   arrive, whether deliberately unshipped (counts in full) or
#                   shipped over a failing path (counts × P(leg fails)) — plus an
#                   exposure charge per kg sent over marginal passes. Refuses
#                   low-tier tonnage over nearly-closed passes; staffs convoys
#                   with the fleet's most reliable vehicles. Tier-1 floored at
#                   the full_coverage level; total floored at its
#                   COVERAGE_FLOOR_FRAC.
#
# Floors are PER DEPOT, relative to the full_coverage allocation (which is also
# solved per depot, jointly across that depot's axes — the v3.0 fix for the
# v2.0 bug where a depot serving two axes had its stock allocated once per axis).
COVERAGE_WEIGHT = 1.0e6            # retained: lexicographic weight inside full_coverage
TIER_PRIORITY = {1: 5.0, 2: 2.0, 3: 1.0}
STATUS_PRIORITY = {"stockout": 3.0, "rationing": 1.5, "ok": 1.0}
OBJECTIVES = ["full_coverage", "min_cost", "min_exposure"]
COVERAGE_FLOOR_FRAC = {"min_cost": 0.98, "min_exposure": 0.95}
# Exposure weight: how many tier-weight-equivalents of penalty one kg·P(fail) of
# shipped cargo carries, representing the men/vehicles put on a marginal pass.
# At 1.0 the allocation drops tonnage iff P(path fails) > tier_w/(tier_w+1):
# tier-3 drops below P(open)=0.50, tier-2 below 0.33, tier-1 is hard-floored and
# never dropped. SYNTHETIC-INFERRED operational judgement; isolated here so a
# user (or a what-if scenario) can turn the dial.
EXPOSURE_WEIGHT = 1.0
# A convoy counts as a "risky sortie" (reported metric) below this path P(open).
RISKY_SORTIE_PAVAIL = 0.50

# ─────────────────────────────────────────────────────────────────────────────
# Alerting thresholds  (Component 5, steps 5-7) — unchanged from v1.0
# ─────────────────────────────────────────────────────────────────────────────
ROUTE_DISRUPTION_PCLOSED_THRESHOLD = 0.60
ROUTE_DISRUPTION_WINDOW_DAYS = 7
VEHICLE_DEADLINE_PDEADLINE_THRESHOLD = 0.05


def stockout_severity(predicted_status_worstcase: str, predicted_status: str, tier: int) -> str:
    if predicted_status_worstcase == "stockout":
        return "critical"
    if predicted_status == "rationing" or predicted_status_worstcase == "rationing":
        return "warning" if tier != 1 else "critical"
    return "info"


# ─────────────────────────────────────────────────────────────────────────────
# Solver — unchanged from v1.0
# ─────────────────────────────────────────────────────────────────────────────
SOLVER_BACKEND = "CBC"
SOLVER_TIME_LIMIT_MS = 5000
SOLVER_NUM_THREADS = 1
# v2.0 VRP (CP-SAT): per-cluster time cap in seconds. The 5s replan cap is relaxed
# (founder decision) — clusters are ≤8 posts and solve to optimality far faster, but
# a generous ceiling guarantees optimality on the largest cluster. Deterministic via
# single worker + fixed random_seed regardless of wall-clock.
SOLVER_TIME_LIMIT_S = 15.0
# Per-objective residual-routing time caps. cost/time prove optimality fast; the
# risk and balanced objectives are FLAT (aggregate risk saturates near 1.0 when many
# independent-deadline vehicles compound — the known Stage 4 risk-saturation issue),
# so the solver finds the best solution instantly but cannot certify it. Verified:
# min_risk answer is byte-identical at 3s vs 60s. So we cap the flat objectives low —
# zero quality loss, large wall-time saving. (Risk saturation itself flagged for a
# separate fix: the objective needs a discriminating formulation, e.g. max-leg-risk
# or expected-disrupted-legs instead of compounded P(any disruption).)
SOLVER_TIME_LIMIT_BY_OBJECTIVE = {"full_coverage": 15.0, "min_cost": 15.0,
                                  "min_exposure": 15.0}
VRP_VEHICLE_SLACK = 3
