# Project Bastion — Stage 4: Planning & Optimization Layer

> **v3.0 (ε-constraint frontier planner).** v2.0's four objectives (min_cost /
> min_time / min_risk / balanced) were measured producing four near-identical
> plans: coverage byte-identical, cost within 1.1%, makespan within 8%,
> aggregate_risk pinned at 1.0 in all four. Root causes (all verified on
> seed-42 / 15-Dec): Phase-1 allocation never read the objective; 84 of 90
> convoys were objective-blind full-truck shuttles (only 4.9% of tonnage
> reached the objective-aware VRP); the fleet has no cost-vs-time tradeoff
> (cheapest class is also fastest, so min_cost ≡ min_time); and each post has
> exactly one path, so min_risk had no route to choose. A solver cannot
> differentiate plans in a formulation that contains no tradeoffs.
>
> **v3.0 restructures what the objectives trade.** Three plans that are
> different *commitments*, not different labels:
> * **full_coverage** — ship everything reachable (lexicographic max coverage,
>   then min cost; the v2.0 behaviour, honestly named). Reference plan.
> * **min_cost** — cheapest plan covering ≥98% of the full_coverage tonnage
>   per depot. Drops the most expensive marginal cargo; cheapest ₹/t·km fleet.
> * **min_exposure** — minimizes tier-weighted expected shortfall (unshipped kg
>   count in full; shipped kg count × P(leg fails)) plus an exposure charge per
>   kg sent over marginal passes (`EXPOSURE_WEIGHT`, SYNTHETIC-INFERRED dial).
>   Refuses low-tier cargo where path P(open) < ~0.33–0.50; staffs convoys to
>   maximize payload × P(vehicle survives). Coverage floor 95%.
> * **Tier-1 is identical in every plan by construction** (hard restore to the
>   reference allocation). Every deliberately dropped kg appears per post/SKU
>   in `resupply_shortfalls.parquet` with cause **`objective_tradeoff`** — a
>   dropped delivery is a decision the planner can see and overrule, never a
>   silent omission. min_time is **removed** until the world has a real time
>   axis (multi-modal legs / multi-day dispatch); documented in config.py.
>
> **Allocation bug fix (changes the headline number).** v2.0 allocated per
> (depot, axis) cluster with the full depot stock cap in each cluster and no
> decrement; depots P003/P004 serve two axes, and several (depot, SKU) pairs
> are stock-binding — the same stock was promised to both axes. v3.0 allocates
> once per depot, jointly across its axes. Honest reachable coverage is
> **92.5%**, not the previously reported 98.2% (~39 t was double-counted
> stock). Correctness over polish.
>
> **Result on seed-42 / 15-Dec (horizon 14 d):**
>
> | plan | reach-coverage | convoys | cost | exp. in-transit loss | deliberately dropped |
> |---|---|---|---|---|---|
> | full_coverage | 92.5% | 82 | ₹722,178 | 504.1 t | 0 t |
> | min_cost | 90.7% | 81 | ₹711,956 | 496.1 t | 11.8 t |
> | min_exposure | 88.7% | 79 | ₹701,281 | 481.5 t | 25.2 t |
>
> Deterministic across reruns (byte-identical leg sets, all three plans).
> ~40 s end-to-end. New plan metrics: `expected_arrived_tonnes`,
> `expected_loss_tonnes`, `unserved_reachable_tonnes`,
> `objective_tradeoff_tonnes`, `expected_shortfall_tonnes`, `max_leg_risk`,
> `risky_sorties`. `aggregate_risk` retained for schema continuity but
> documented as saturating (P(≥1 of ~80 winter sorties has trouble) ≈ 1 by
> construction); decisions use the tonnage-denominated metrics. Two honest
> caveats: `expected_loss_tonnes` is computed at horizon path availability — a
> conservative exposure index for comparing plans, not a literal arrival
> forecast (convoys dispatch anticipatorily while roads are open); and at this
> deep-winter snapshot every convoy crosses a sub-0.5-availability pass, so
> `risky_sorties` equals convoy count — it discriminates in shoulder seasons,
> not mid-December.

---

> **v2.0 (milk-run convoy optimizer).** v1.1 was one-vehicle-one-post: every at-risk
> post got its own truck, each re-paying the shared mountain trunk (every route in the
> seed-42 world crosses Zoji La; depot P005 alone serves 12 posts via Zoji La). On this
> topology that is structurally wasteful. v2.0 plans **milk-run convoys**: a vehicle
> leaves a depot, climbs one axis, and drops multi-SKU loads at several posts in road
> order until its payload is exhausted.
>
> **Distances.** Routing needs post→post road distances, which Stage 2 didn't have. A
> new `stage2_world/road_network.py` emits `post_distances.parquet` using a spine model:
> each post's depot→post road distance is its position on the axis spine; inter-post
> distance = max(detour·great-circle, |Δspine|), then Floyd–Warshall all-pairs-shortest-
> path repair. Verified physically valid: 0 triangle-inequality violations, 0 spine-
> envelope violations, perfect symmetry. Flagged SYNTHETIC-INFERRED (no real survey
> exists; one-file replacement point when it does).
>
> **Solver.** Exact two-phase decomposition (proven optimal, no optimality loss):
> *Phase 1* allocates scarce depot stock to posts by tier priority (LP). *Phase 2* routes
> per (depot,axis) cluster, further split into full-truckload shuttles (no routing needed
> — a full truck can't chain) and a tiny residual milk-run VRP (CP-SAT). Routing is on
> per-post tonnage; the SKU breakdown is filled deterministically after (route cost never
> depends on which carton sits on which truck). cost/time prove `optimal`; risk/balanced
> report `feasible` only because the risk objective is mathematically flat (verified
> byte-identical at 3s vs 60s), not under-solved.
>
> **Result on seed-42 / 15-Dec:** 98.2% of *reachable* demand covered across all 15
> reachable posts and all six heads (586 t correctly surfaced as road-isolated — the
> winter reality, not a failure). Milk-runs present (e.g. P019→P018→P010 on one convoy).
> Cost reconciles exactly (90 convoy costs = plan total). Deterministic across reruns.
> ~20s end-to-end. New output `resupply_convoys.parquet` (one row per dispatched route)
> alongside the v1.1 shortfall/substitution tables.
>
> **Known carry-over:** the risk objective saturates (aggregate_risk → 1.0 when many
> independent-deadline vehicles compound), so min_risk doesn't discriminate well — the
> same Stage 4 risk-saturation issue flagged earlier, now visible in the VRP. Separate fix.

---

> **v1.1 (Advance Winter Stocking rebuild).** v1.0 defined a post's deficit as
> *(21-day P90 target − current stock)* and produced plans containing **only Fresh
> Meat**: every other SKU sat at 4–7× of a 21-day target because forward posts hold
> deep pre-winter reserves, so their deficit clipped to zero. Only the one perishable
> (7-day shelf life) was ever thin enough to surface. The optimizer was correct; the
> deficit *definition* was wrong — it asked "what runs out in two weeks" against posts
> provisioned for six months.
>
> The decision these posts actually model is **Advance Winter Stocking (AWS)**:
> Eastern Ladakh forward posts are road-cut for ~5–6 months a winter (winter declared
> 15-Nov; passes shut Nov onwards), and AWS pre-positions everything needed to last the
> closure *before* the road shuts. v1.1 therefore stocks to
> `daily_p90 × (days_to_closure + ISOLATION_DURATION + RESERVE)` (default 120-day
> isolation, conservative vs the headline ~150–180d), **gated by isolation probability**
> (a post is only force-stocked to AWS scale if it's actually going to be cut off), with
> each SKU's window **capped at its shelf life** (read live from `skus.parquet`).
> Perishable demand beyond shelf life is **routed into a longer-life substitute** (Fresh
> Meat → Tinned Rations, mirroring the real ~2015 frozen/tinned contract shift); any
> residual the depot genuinely cannot supply is **surfaced as an explicit shortfall**
> (`resupply_shortfalls.parquet`, cause-tagged road_isolated / depot_short /
> capacity_short, air-resupply flagged) — never silently dropped.
>
> Result on the seed-42 / 15-Dec snapshot: plans now ship **29 SKUs across all six
> heads** (611 t Rations, 593 t POL, plus Engineer/Medical/Ammunition/Clothing) instead
> of Fresh-Meat-only. Per-row `expected_cost` now reconciles exactly to plan `total_cost`
> on multi-SKU loads. ~47% road coverage on 15-Dec is **reachability-bound, not
> stock-bound** — half the in-scope posts are genuinely road-isolated mid-winter, which
> the system now states honestly rather than papering over.
>
> Public anchors: ThePrint (20-Sep-2024), The Week / ETV Bharat (2020), The Tribune
> (Jan-2025) on the six-month road-closed AWS cycle. New parameters isolated in
> `config.py` (`ISOLATION_DURATION_DAYS`, `ISOLATION_GATE`, `SUBSTITUTION_MAP`).

---

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
