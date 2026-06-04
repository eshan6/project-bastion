"""
Project Bastion — Stage 4 config (planning / optimization layer, v1.0)

Stage 4 turns Stage 3's prediction objects into *actions*:
  - resupply plans   (OR-Tools MIP, 4 ranked objectives)  -> resupply_plan(_leg)
  - alerts           (3 types, from the 3 Stage 3 outputs)  -> alert

Same discipline as Stages 2-3: every numeric choice is either anchored to a
public source or explicitly flagged SYNTHETIC-INFERRED. The optimizer must be
*honest about what it does not know*. Cost/speed/weight priors below are the
only new free parameters Stage 4 introduces; they are isolated here so a real
tariff/spec sheet replaces them in one place.

Design stance (the load-bearing decision):
  We plan on WORST-CASE (P90) demand and dispatch ANTICIPATORILY. Demand P90 and
  pass-closure probability share a driver (winter / western disturbances), so a
  post's worst consumption week coincides with its least-reachable week. Planning
  on the median (P50) and dispatching reactively would systematically fail at the
  exact moment resupply matters. Stage 3 hands us p90 and isolation_probability
  precisely so we can plan against the bad case.
"""
from pathlib import Path
import os

# ─────────────────────────────────────────────────────────────────────────────
# Paths — Stage 4 reads a Stage 3 snapshot output dir + Stage 2 topology
# ─────────────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
# Stage 2 world topology (posts/routes/vehicles/skus)
DATA_DIR = Path(os.environ.get("BASTION_DATA_DIR", ROOT.parent / "stage2_world" / "data"))
# Stage 3 prediction snapshots live under stage3_models/output/snapshot_<date>/
STAGE3_OUTPUT_DIR = Path(os.environ.get("BASTION_STAGE3_OUTPUT",
                                        ROOT.parent / "stage3_models" / "output"))
OUTPUT_DIR = ROOT / "output"          # plans + alerts parquet
REPORT_DIR = ROOT / "reports"         # diagnostics json
for _d in (OUTPUT_DIR, REPORT_DIR):
    _d.mkdir(exist_ok=True, parents=True)

MODEL_VERSION = "stage4-v1.0"
DATA_SNAPSHOT_SEED = 42

# ─────────────────────────────────────────────────────────────────────────────
# Planning window
# ─────────────────────────────────────────────────────────────────────────────
# The optimizer plans the next PLANNING_HORIZON_DAYS of resupply. 14 days is the
# operational "next two weeks" cycle, matches the longest route-prediction horizon
# (route models predict at 1/3/7/14d) and the Tier-1 alert window. Configurable.
PLANNING_HORIZON_DAYS = 14

# A post we resupply should end the window holding RESERVE_DAYS of P90 cover on
# top of consuming through the window. Target stock = daily_p90*(horizon+reserve).
# 7d reserve mirrors Stage 2/3 rationing threshold (cover < 7d => rationing).
RESERVE_DAYS = 7

# Which (post, sku) pairs the optimizer is allowed to act on: a post is "at risk"
# if ANY of its sku rows fired a tier alert OR its worst-case status is bad. We
# then top up every sku at that post with a positive deficit (you resupply the
# whole post when a convoy goes, not one carton).
ACTIONABLE_WORSTCASE_STATUSES = {"stockout", "rationing"}

# ─────────────────────────────────────────────────────────────────────────────
# Per-SKU shipping weight  (kg per consumption-unit)
# ─────────────────────────────────────────────────────────────────────────────
# Needed to convert delivered quantity -> tonnage against vehicle payload_tons.
# ANCHORED where the unit dictates it (kg=1.0 by definition; litres via standard
# fluid density; ammunition via public cartridge masses; oxygen via standard
# D-cylinder mass). The rest are SYNTHETIC-INFERRED order-of-magnitude estimates,
# flagged so a real packing/density table replaces them cleanly.
#
# Density anchors (kg/L, standard): kerosene 0.81, diesel 0.84, petrol 0.74,
#   lubricant oil 0.90, cooking oil 0.92.
# Cartridge anchors (kg/round, public small-arms data): 5.56x45 ~0.0123,
#   7.62x51 ~0.025, 40mm UBGL ~0.230, 81mm mortar bomb ~4.2, illum/pyro ~0.5.
SKU_WEIGHT_KG = {
    # Rations  (kg units => 1.0; oil is litres)
    "RAT-001": 1.00,   # Atta/Flour (kg)            ANCHORED unit=kg
    "RAT-002": 1.00,   # Rice (kg)                  ANCHORED
    "RAT-003": 1.00,   # Dal/Pulses (kg)            ANCHORED
    "RAT-004": 0.92,   # Cooking Oil (L)            ANCHORED density
    "RAT-005": 1.00,   # Fresh Meat (kg)            ANCHORED
    "RAT-006": 0.40,   # Tinned Rations (unit/tin)  SYNTHETIC-INFERRED
    "RAT-007": 1.00,   # Tea/Sugar (kg)             ANCHORED
    "RAT-008": 0.001,  # Dry Fruits (g)             ANCHORED unit=gram
    # POL  (all litres -> density)
    "POL-001": 0.81,   # Kerosene (L)               ANCHORED density
    "POL-002": 0.84,   # Diesel HSD (L)             ANCHORED density
    "POL-003": 0.74,   # Petrol MS (L)              ANCHORED density
    "POL-004": 0.90,   # Lubricants (L)             ANCHORED density
    # Ammunition  (kg per round)
    "AMM-001": 0.0123, # 5.56mm Ball                ANCHORED public spec
    "AMM-002": 0.0250, # 7.62mm                     ANCHORED public spec
    "AMM-003": 0.2300, # 40mm UBGL                  ANCHORED public spec
    "AMM-004": 4.2000, # 81mm Mortar bomb           ANCHORED public spec
    "AMM-005": 0.5000, # Pyro/Illum (unit)          SYNTHETIC-INFERRED
    # Clothing  (kg per item)
    "CLO-001": 1.80,   # Boots (pair)               SYNTHETIC-INFERRED
    "CLO-002": 1.50,   # ECC&E Jacket               SYNTHETIC-INFERRED
    "CLO-003": 0.20,   # Snow Goggles (pair)        SYNTHETIC-INFERRED
    "CLO-004": 2.50,   # Thermal Sleeping Bag       SYNTHETIC-INFERRED
    # Medical
    "MED-001": 0.0005, # Diamox (tab)               SYNTHETIC-INFERRED
    "MED-002": 0.0500, # Dexamethasone (vial)       SYNTHETIC-INFERRED
    "MED-003": 10.000, # Oxygen Cylinder refill     ANCHORED ~D-cylinder mass
    "MED-004": 1.0000, # Frostbite Kit              SYNTHETIC-INFERRED
    "MED-005": 0.1000, # Antibiotics (course)       SYNTHETIC-INFERRED
    # Engineer
    "ENG-001": 12.00,  # Bukhari Stove              SYNTHETIC-INFERRED
    "ENG-002": 15.00,  # Prefab Shelter Panel (m2)  SYNTHETIC-INFERRED
    "ENG-003": 0.05,   # Sandbags (empty, unit)     SYNTHETIC-INFERRED
    "ENG-004": 0.50,   # Concertina Wire (m)        SYNTHETIC-INFERRED
}
# Fallback per head if a SKU id is unknown (defensive; current world has all 30).
HEAD_WEIGHT_FALLBACK_KG = {"Rations": 1.0, "POL": 0.85, "Ammunition": 0.05,
                           "Clothing": 1.5, "Medical": 0.5, "Engineer": 5.0}

# ─────────────────────────────────────────────────────────────────────────────
# Vehicle class economics  (all SYNTHETIC-INFERRED — illustrative ₹ and km/h)
# ─────────────────────────────────────────────────────────────────────────────
# Heavier trucks burn more fuel per km but carry more; light trucks are cheaper
# but make more trips. Speeds are mountain-road averages (convoy pace, not spec
# top speed). Replace with a real transport tariff + route-speed survey.
VEHICLE_CLASS_FUEL_COST_PER_KM = {     # ₹/km, SYNTHETIC-INFERRED
    "Tata-LPTA":     18.0,
    "Stallion-4x4":  24.0,
    "Stallion-6x6":  30.0,
    "BharatBenz-HD": 38.0,
}
VEHICLE_CLASS_SPEED_KMPH = {            # convoy avg on forward axes, SYNTHETIC-INFERRED
    "Tata-LPTA":     25.0,
    "Stallion-4x4":  24.0,
    "Stallion-6x6":  22.0,
    "BharatBenz-HD": 20.0,
}
VEHICLE_FIXED_DISPATCH_COST = 5000.0    # ₹ crew/admin per tasked vehicle, SYNTHETIC-INFERRED
DEFAULT_FUEL_COST_PER_KM = 25.0
DEFAULT_SPEED_KMPH = 23.0

# Marginal-path delay: a partly-open path holds convoys at the pass. Extra transit
# hours added in proportion to closure probability of the chosen path.
PATH_DELAY_HOURS_AT_FULL_CLOSURE = 72.0  # SYNTHETIC-INFERRED (a 3-day pass hold)

# ─────────────────────────────────────────────────────────────────────────────
# Feasibility + risk
# ─────────────────────────────────────────────────────────────────────────────
# Below this path availability (P(open) product over passes on the leg at the
# planning horizon) a road leg is treated as INFEASIBLE — the post is effectively
# isolated; the optimizer cannot drive there and the deficit becomes a surfaced
# shortfall (air-resupply flagged if the post supports it). This is the key
# decision-changing output, not a silent failure.
PATH_FEASIBILITY_MIN = 0.05

# Route-prediction horizon to read path availability at. Use the closest available
# route horizon to PLANNING_HORIZON_DAYS. Route models predict at 1/3/7/14.
ROUTE_HORIZONS_DAYS = [1, 3, 7, 14]

# Vehicle-reliability prediction horizon (Stage 3 scores P(deadline) over 7 days).
VEHICLE_HORIZON_DAYS = 7

# ─────────────────────────────────────────────────────────────────────────────
# Objective weights
# ─────────────────────────────────────────────────────────────────────────────
# Coverage is lexicographically first: a very large weight on weighted unmet
# deficit (kg) forces the optimizer to cover everything it physically can; the
# secondary transport term then chooses the cheapest/fastest/safest *among the
# covering solutions* and decides which trucks roll. This is why the 4 plans
# differ — same coverage, different routing/vehicle picks.
COVERAGE_WEIGHT = 1.0e6                  # ₹-equivalent penalty per priority-kg unmet

# Criticality multipliers on unmet deficit (priority weight on shortfall).
# Tier 1 (life/fight-critical: rations, ammo, POL, O2) >> Tier 3.
TIER_PRIORITY = {1: 5.0, 2: 2.0, 3: 1.0}
STATUS_PRIORITY = {"stockout": 3.0, "rationing": 1.5, "ok": 1.0}

# The four plan objectives produced every run. 'balanced' blends the normalized
# cost/time/risk legs. These map to bastion.plan_objective enum exactly.
OBJECTIVES = ["min_cost", "min_time", "min_risk", "balanced"]
# Weights for the 'balanced' blend (sum to 1). SYNTHETIC-INFERRED preference.
BALANCED_BLEND = {"cost": 0.34, "time": 0.33, "risk": 0.33}

# ─────────────────────────────────────────────────────────────────────────────
# Alerting thresholds  (Component 5, steps 5-7)
# ─────────────────────────────────────────────────────────────────────────────
# Stockout alerts come straight from Stage 3 tier_alert_fired (Stage 3 owns the
# days-of-cover math). Stage 4 sets severity and adds the two alert types the
# Stage 3 / loader path does not produce:
#
#   route disruption: fire when P(closed) within the planning window crosses
#       ROUTE_DISRUPTION_PCLOSED_THRESHOLD (masterplan: > 0.6).
#   vehicle deadline: fire when a vehicle's P(deadline) over its horizon crosses
#       VEHICLE_DEADLINE_PDEADLINE_THRESHOLD.
ROUTE_DISRUPTION_PCLOSED_THRESHOLD = 0.60     # masterplan Component 5 step 6
ROUTE_DISRUPTION_WINDOW_DAYS = 7
VEHICLE_DEADLINE_PDEADLINE_THRESHOLD = 0.05   # SYNTHETIC-INFERRED; ~5% over 7d is high
                                              # given fleet mean ~1% (see Stage 3 eval)

# Severity mapping for stockout alerts (Stage 4 is the authoritative alert layer).
def stockout_severity(predicted_status_worstcase: str, predicted_status: str, tier: int) -> str:
    if predicted_status_worstcase == "stockout":
        return "critical"
    if predicted_status == "rationing" or predicted_status_worstcase == "rationing":
        return "warning" if tier != 1 else "critical"
    return "info"

# ─────────────────────────────────────────────────────────────────────────────
# Solver
# ─────────────────────────────────────────────────────────────────────────────
SOLVER_BACKEND = "CBC"          # bundled with OR-Tools; open; deterministic single-thread
SOLVER_TIME_LIMIT_MS = 5000     # masterplan: warm-start replan < 5s
SOLVER_NUM_THREADS = 1          # single thread => deterministic, reproducible plans
