# Project Bastion — Stage 4: Planning & Optimization Layer

> **v3.4 (multi-modal as a frontier option) + v3.3 (alternate road paths).**
> These two close the last gaps in "the plans are genuinely different commitments."
>
> **v3.3 — alternate road paths.** The synthetic world ships one route per post,
> so the optimizer could choose who/when/what-mode but never WHICH ROUTE. v3.3
> derives up to 3 candidate road legs per post at Stage-4 input time (no world
> regeneration — the generator and its committed rows are untouched): the
> primary, an alternate-depot route on the same axis, and a pass-variant that
> reroutes around the post's most-marginal pass. Each carries its own per-slot
> availability. The objective then PICKS a path: min_exposure takes the safer,
> longer road; min_cost the shortest; full_coverage the doctrine primary. Effect
> on seed-42/15-Dec: min_exposure's mean chosen-path availability rises 0.26 →
> 0.36 and its expected in-transit loss falls ~93 t purely from route choice —
> a decision the single-path world could not express. A second, free benefit:
> when a reroutable pass closes (e.g. Chang La), the pass-variant rescues the
> affected posts by road, so they never become a non-road problem at all.
>
> **v3.4 — multi-modal inside the frontier.** Phase 3 (air/porter/mule) used to
> fire only on road-ISOLATED residual. v3.4 lets the EXPOSURE objective
> PROACTIVELY divert genuinely air/animal-critical cargo (Medical, Ammunition —
> NOT bulk rations or POL, which you don't air-drop off a 35%-open pass) off a
> marginal-but-feasible road path onto an all-weather mode, via the SAME
> mule→porter→air resolver. On seed-42/15-Dec min_exposure mules 6.82 t of
> medical forward (₹819k) rather than gamble it on near-shut passes, cutting
> expected in-transit loss 882 → 777 t. Cost/coverage plans still truck
> everything (cheap); only the exposure-minimising plan pays the non-road
> premium where it buys arrival certainty. Gated by objective + tier + head +
> road availability, all in config.
>
> **The frontier now (seed-42 / 15-Dec):**
>
> | plan | reach-cover | cost | exp. in-transit loss | convoys | non-road |
> |---|---|---|---|---|---|
> | full_coverage | 92.6% | ₹2,002,447 | 896.7 t | 170 | — |
> | min_cost | 90.9% | ₹1,967,108 | 882.7 t | 166 | — |
> | min_exposure | 91.0% | ₹2,781,235 | 777.2 t | 164 | 6.8 t medical (mule) |
>
> Three genuinely distinct commitments: cheapest-trucks-everything, trim-marginal-
> cargo, or reroute-safer-and-fly-the-medical. Phase 3 residual mop-up is
> preserved and verified (closing Zoji La, the universal chokepoint, lifts
> 258.75 t by mule/porter/air). Determinism re-verified end-to-end at both CLI
> (15 s) and service (3 s) limits — the residual VRP is pinned to deterministic
> time so timed-out incumbents are byte-identical across runs.
>
> **Still open:** alternate paths and proactive multi-modal are SYNTHETIC-INFERRED
> topology/doctrine; with real route data and real lift-capacity figures they'd
> recalibrate. The next structural step is the stochastic (scenario-sampled)
> planner — robust dispatch across many simulated winters.

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
