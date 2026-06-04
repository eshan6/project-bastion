# Project Bastion — Stage 4: Planning & Optimization Layer

Stage 4 turns Stage 3's *predictions* into *actions*. It is the layer that
answers "given what we forecast, what should actually roll, and what can't be
saved by road at all?"

It produces three first-class ontology outputs:

| Output | Table | What it is |
|---|---|---|
| Resupply plans | `bastion.resupply_plan` / `resupply_plan_leg` | An OR-Tools MIP solved under **4 objectives** (min_cost / min_time / min_risk / balanced) — which depot vehicles to dispatch, loaded with which SKUs, to which posts |
| Alerts | `bastion.alert` | All **3 alert types** — stockout-risk, route-disruption, vehicle-deadline |
| Diagnostics | `planning_diagnostics.json` | The decision-grade readout: reachability, binding constraints, plan-comparison matrix, plain-language interpretation |

Stage 4 reads **only** `stockout_risk.parquet`, `route_predictions.parquet`,
`vehicle_reliability.parquet` (the Stage 3 contract) plus Stage 2 topology
(`posts/routes/vehicles/skus`). The *risk evaluation itself* — days-of-cover,
`tier_alert_fired`, `isolation_probability` — is already done in Stage 3's
`risk_scorer.py`; Stage 4 consumes it, it does not recompute it.

---

## The load-bearing design decision

**Plan on worst-case (P90) demand; dispatch anticipatorily.**

Demand-P90 spikes and pass-closure probability share a driver — winter / western
disturbances. A post's worst consumption week is the *same* week its serving pass
is most likely shut. So planning on the median (P50) and dispatching reactively
("send a convoy once the post is short") fails at the exact moment resupply
matters. Stage 3 hands us `p90` and `isolation_probability` precisely so we can
plan against the bad case and dispatch *before* the window closes.

This is not a stylistic choice; it falls out of the data (see Findings below).

---

## The optimization problem

The AOR is hub-and-spoke: each post has a `serving_depot_id` and a direct inbound
road route with a known distance and **pass chain**. So we don't solve a free
multi-commodity network flow — we solve a **capacitated vehicle-assignment with
coverage shortfall**, which is right-sized, realistic, and fast (<5s warm-start).

### Variables
```
x[v,p] ∈ {0,1}   vehicle v dispatched to post p   (≤ 1 mission per vehicle)
f[v,p,k] ≥ 0     units of SKU k loaded on v for p
u[p,k] ≥ 0       unmet deficit (shortfall) for (post, sku)
```

### Constraints
```
(1) Σ_p x[v,p] ≤ 1                                  one mission per vehicle
(2) Σ_k f[v,p,k]·wkg[k] ≤ payload_t[v]·1000·x[v,p]  capacity + load-only-if-assigned
(3) Σ_v f[v,p,k] + u[p,k] = deficit[p,k]            coverage accounting
(4) Σ_{v@d,p} f[v,p,k] ≤ depot_stock[d,k]           depot supply cap
```
A post whose **path availability** (∏ P(open) over the passes on its leg, at the
planning horizon) falls below `PATH_FEASIBILITY_MIN` is **road-isolated**: it gets
no `x[v,p]` and its deficit becomes surfaced shortfall (air-resupply flagged if the
post supports it). Isolation is an explicit, visible output — never a silent miss.

### Deficit (worst-case, anticipatory top-up)
```
daily_p90       = forecast_p90_weekly / 7
target_units    = daily_p90 · (PLANNING_HORIZON_DAYS + RESERVE_DAYS)
deficit[p,k]    = max(0, target_units − current_stock)
```
i.e. restore every at-risk post to *(horizon + reserve)* days of **P90** cover.

### Objective (minimize)
```
COVERAGE_WEIGHT · Σ priority[p,k]·wkg[k]·u[p,k]      (lexicographically first)
  +  Σ_legs  secondary_penalty(objective) · x[v,p]
priority[p,k] = TIER_PRIORITY[tier] · STATUS_PRIORITY[worst-case status]
```
Coverage is lexicographically dominant (huge weight), so the optimizer always
covers everything it *physically can*; the secondary term then chooses among the
covering solutions. The four objectives change only the secondary penalty:

| Objective | Secondary penalty per leg |
|---|---|
| `min_cost` | `fuel(class)·distance + fixed dispatch` |
| `min_time` | one-way convoy hours `distance/speed(class)` + marginal-path hold |
| `min_risk` | expected leg failure `1 − P(path open)·P(vehicle survives)` |
| `balanced` | normalized blend of the three (`BALANCED_BLEND`) |

All four cover the same deficit but route/select vehicles differently — e.g.
`min_cost` spreads onto the cheapest light trucks, `min_risk` consolidates onto
the fleet's most-reliable trucks.

### Solver / determinism
CBC (bundled with OR-Tools), single-thread, 5 s limit. Variables created in
sorted order; `min_cost` is solved first and its assignment warm-starts the other
three. Plan IDs are `uuid5(snapshot:horizon:model:objective)` — **byte-identical
on re-run**.

---

## Findings from the canonical snapshot (2024-12-15)

Running against the committed seed-42 deep-winter snapshot:

- **15 of 30 at-risk posts are road-isolated.** Zoji La path-open ≈ 0.29, Chang La
  ≈ 0.21; posts behind a 3-pass chain compound to ≈ 0.037 — unreachable.
- **Best achievable road coverage is 31.7%.** The uncovered 68% is **not** a stock
  problem (depots are full) or a truck problem (capacity is slack) — it is a
  *reachability* problem. The resupply that mattered was due in October–November.
  The lever is convoys-before-closure, not more inventory.
- **Plans differentiate on cost (₹53.6k–62.3k) and vehicle mix**, less on risk —
  because when passes are marginal, the *path* dominates leg risk and vehicle
  choice is second-order. `aggregate_risk` (P(≥1 leg fails)) pins near 1.0 in deep
  winter; `expected_disrupted_legs` is the metric that still discriminates.
- Solve time ≈ 1.4 s for all four objectives — inside the <5 s replan budget.

This is the anticipatory-logistics thesis demonstrated by the optimizer's own
refusal to promise undeliverable convoys, not asserted in a slide.

---

## SYNTHETIC-INFERRED parameters (the only new free parameters Stage 4 adds)

All isolated in `config.py` so a real tariff/spec sheet replaces them in one place.

- **`SKU_WEIGHT_KG`** — kg per consumption-unit. *Anchored* where the unit dictates
  (kg=1.0; litres via standard fluid density; small-arms cartridge masses; O2
  cylinder ≈ standard D-cylinder). *Flagged SYNTHETIC-INFERRED* for packed items
  (clothing, kits, engineer stores).
- **`VEHICLE_CLASS_FUEL_COST_PER_KM`, `VEHICLE_CLASS_SPEED_KMPH`,
  `VEHICLE_FIXED_DISPATCH_COST`, `PATH_DELAY_HOURS_AT_FULL_CLOSURE`** — all
  SYNTHETIC-INFERRED illustrative economics.
- **`PATH_FEASIBILITY_MIN` (0.05), `COVERAGE_WEIGHT`, `TIER_PRIORITY`,
  `STATUS_PRIORITY`, `BALANCED_BLEND`** — planning-policy choices, documented.
- **Thresholds**: route-disruption `P(closed) > 0.60` (masterplan); vehicle-deadline
  `P(deadline) > 0.05` over 7 d (fleet mean ≈ 1%, so 5% is genuinely high).

Independence of pass closures is assumed for path availability (∏ over passes).
This *under*-estimates joint openness → we are pessimistic about reachability →
we plan earlier. Documented and deliberate.

---

## Files

```
stage4_planning/
  config.py          all priors/policies (anchored or flagged)
  inputs.py          assemble the optimizer bundle from a Stage 3 snapshot
  optimizer.py       the OR-Tools MIP (build + solve, 4 objectives, warm-start)
  alerts.py          the authoritative 3-type alert generator
  plan_service.py    orchestrator → writes plans/legs/alerts parquet + diagnostics
  daily_tick.py      single CI entrypoint: [predict] → plan → [load]
  load_plans.py      DB writer → Supabase ontology (idempotent, lineage-linked)
  requirements.txt
  (bundle also ships .github/workflows/tick.yml at its real path)
```

## Running

```bash
# plan the committed canonical snapshot (no DB, no regeneration needed)
cd stage4_planning && python plan_service.py

# full tick for a date, then load into Supabase
python daily_tick.py --date 2024-12-15 --load      # needs DATABASE_URL

# regenerate Stage 3 predictions for a new date first, then plan
python daily_tick.py --predict --date 2024-10-15    # needs Stage 3 models + world
```

## Wiring into the live DB

1. `python db/load_world.py` — loads world + Stage 3 predictions, creates the
   snapshot + model_versions + `stockout_risk` rows.
2. `python stage4_planning/load_plans.py` — registers the `optimizer`
   model_version, writes plans + legs, and writes the **authoritative** alert set
   (superseding `load_world.py`'s stopgap stockout alerts; idempotent, re-runnable).
   Alerts are re-linked to their source `stockout_risk` / `route_prediction` rows so
   `bastion.v_prediction_lineage` stays whole: alert → risk → model → snapshot.
