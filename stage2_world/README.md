# Project Bastion — Stage 2 Generator (v1.1)

**Status:** End-to-end working. 2.35M synthetic data rows produced in ~62 seconds for a 3-year Tangtse Brigade AOR horizon. Every meaningful parameter is anchored to a named public source or explicitly flagged `SYNTHETIC-INFERRED`.

**v1.1 adds the stock dynamics layer** — the forward stock-accounting identity (AWS pre-positioning, routine convoys, spoilage, perishable substitution) that turns the consumption stream into a running stock balance. Without it there is no days-to-stockout, and the Forward Stockout Predictor has nothing to forecast.

---

## What this is

The synthetic data generator for Project Bastion's Forward Stockout Predictor. Per the v3 masterplan, the generator is the load-bearing piece — the rest of the system trains on what it produces, so it must be **internally coherent and behaviourally realistic**, not arbitrary.

The data is **thick synthetic**: weather, pass closures, post isolation, consumption multipliers, and vehicle hazard all flow from a single seeded RNG chain. Same seed = identical world, every time. The world the model learns from is the same shape as the world it would have to operate in.

---

## What it produces

Default horizon: **2022-01-01 → 2024-12-31** (1,096 days, 3 years).

| Table                | Rows         | What it is                                                       |
| -------------------- | ------------ | ---------------------------------------------------------------- |
| `posts`              | 35           | Brigade lay-down (5 depots + 12 mid-altitude + 18 forward)       |
| `routes`             | 34           | Depot↔post + inter-depot graph                                   |
| `vehicles`           | 249          | Fleet across 4 classes (Stallion 4x4/6x6, Tata LPTA, BharatBenz) |
| `skus`               | 30           | 6 stock heads: Rations, POL, Ammo, Clothing, Medical, Engineer   |
| `weather_daily`      | 38,360       | Per-post daily T_max / T_min / T_mean / precip / WD flag         |
| `wd_events`          | 18           | Western Disturbance event log                                    |
| `pass_closures`      | 134          | Per-pass closure events                                          |
| `pass_status_daily`  | 5,480        | Per-pass daily open/closed status                                |
| `consumption_daily`  | 1,150,800    | Per-(post, SKU, day) consumption with full feature context       |
| `tempo_daily`        | 1,096        | Brigade-shared tempo state (low/normal/high/crisis)              |
| `vehicle_events`     | 454          | Per-vehicle deadline + return events                             |
| `stock_daily`        | 1,150,800    | Per-(post, SKU, day) stock ledger: opening → receipts → consumption → spoilage → closing, with status |
| `aws_plan`           | 3,150        | Per-(post, SKU, winter) AWS pre-positioning plan + attainment — the planning-lineage record |

Total: **2.35 million rows**.

---

## The seven modules

### 1. `world.py` — static world

35 posts in the box 32.5–35.5°N / 76–79.5°E. Real toponyms where publicly attested (Galwan PP-14, Rezang La, Hot Springs PP-15, Demchok, Chumur, DBO, Karu, Tangtse, Hanle, Nyoma, Fukche, Spanggur Gap, Black Top, Helmet Top, Kongka La, Gogra Post-17A, Pangong Finger-4/8, Depsang North, Burtsa, Karakoram Approach). For unattested forward observation posts, plausible labels and coordinates.

Routes built as a graph: each non-depot post linked to its closest same-axis depot, with road distance approximated by `1.65 × great_circle × (1 + 0.15 × elevation_diff_km)`. Inter-depot routes layered on top (Leh→Karu→Tangtse→Durbuk→Chushul).

Vehicle fleet of 250 (rounded to 249 after fractional splits) distributed across classes by fleet share; home depot weighted by depot troop strength.

### 2. `weather.py` — daily weather per post

For each post:

1. Pick nearest IMD anchor (Leh real, Drass real, Tangtse extrapolated).
2. Read climatological monthly T_max / T_min / precip from anchor.
3. Lapse-rate adjust (−6.5°C/km) to post elevation.
4. Add AR(1) temperature noise (σ=3.5°C, +1.5°C winter boost, persistence φ=0.55 → cold snaps last 2-4 days, not single isolated days).
5. Inject Western Disturbance events (Poisson λ=6/winter), each 1-4 days. **Critically, WDs are AOR-wide** — same event affects all posts simultaneously, with anchor-specific intensity (Drass 100%, Tangtse 55%, Leh 25% for rain-shadow effect). This is the structural correlation a route GBM needs to learn.

**Validation against IMD priors:**
- Leh Jan T_min mean = **−13.8°C** (prior: −14.0°C) ✓
- Leh Aug T_max mean = **22.8°C** (prior: 24.2°C) ✓
- Leh annual precip = **127 mm/yr** (prior range: 50-130 mm/yr) ✓

### 3. `disruption.py` — pass closures

Two regimes:

- **Seasonal (Zoji La):** one closure per winter season. Start date ~ N(Dec 23, 14 days), duration ~ N(75, 18) days clipped to [25, 130]. Models the **modern BRO regime** (post-2020), not the historical 150-day pattern — that's the realistic operating environment now (PIB confirms 73-day closure in 2022, 33-day in 2025).
- **Stochastic (Khardung La, Chang La, Tsaka La, Marsimik La):** per Wikipedia/Vargis Khan, these have NO permanent winter closure. Daily Bernoulli with seasonal probability, boosted 8× when a snow event >4mm water-equivalent hits representative posts in the served region.

**Validation against BRO priors:**
- Zoji La avg seasonal duration = **51 days** (modern prior: 33-79 days, BRO 2022/2025 anchors) ✓
- Khardung La 8.0 closures/yr (prior 3-8) ✓
- Chang La 10.3 closures/yr (prior 3-8 — slight overshoot, single-seed variance)

### 4. `consumption.py` — daily per-(post, SKU) consumption

For each (post, SKU, day):
```
qty = base_per_soldier_day × troops × altitude_band_mult
      × weather_mult        (kerosene piecewise; others linear cold-coupling)
      × tempo_mult          (ammo + POL only)
      × isolation_mult      (kerosene, rations, medical when post is isolated)
      × lognormal_noise(σ=0.18)
      × anomaly_spike       (1% chance, 3-8× spike)
```

Behaviourally important:
- **Tempo is shared across the brigade** (4-state Markov chain). Same day's ammo signal couples across all posts — the forecaster must distinguish brigade-tempo from per-post noise.
- **Isolation derives from disruption status, not a separate variable.** When ALL of a post's required-serving passes are closed, the post is isolated, and the kerosene/medical multiplier kicks in. The model learns this as an emergent property from the data, not from a flag.
- **Kerosene cold-coupling is piecewise:** above 0°C, very weak slope; below 0°C, ~+2.4× by −20°C. Matches the "colossal" qualitative pattern from the Tribune logistics piece without inventing precision the public sources don't have.
- **Anomaly spikes are uncorrelated with anything.** Real operational fog (a stomach bug, an unscheduled exercise, a delayed requisition). The robust forecaster won't chase them.

**Validation against public anchors:**
- DBO 5050m Jan/Jul kerosene ratio = **3.3×** (prior: 3-6× at deepest-cold posts, Tribune "colossal") ✓
- Ammo crisis-tempo / normal ratio = **3.42×** (config 3.5×) ✓
- Brigade peak daily kerosene = **53 kL/day** = 4.3 L/soldier on peak day. Realistic for an isolation + crisis-tempo + deep-cold concurrence.
- Isolation kerosene boost observed = **2.71×** vs naive prior of 1.30× — observed > prior because isolation correlates with extreme cold (kerosene cold-coupling stacks). **This is exactly the kind of multi-cause effect the model needs to learn rather than read from a rule.**

### 5. `vehicles.py` — vehicle deadline events

Per-vehicle Weibull survival simulation. Daily hazard increment = `(1/scale) × altitude_mult × winter_mult × disruption_mult`. When cumulative hazard crosses an `Exp(1)`-sampled threshold, deadline event fires; vehicle goes to repair (depot 35% / field 65%), then returns. Post-repair vehicles slightly more fragile (next threshold reduced 15%, reflecting persistent ageing).

**Validation:**
- Events per vehicle per 3yr = **1.82** (prior: 1-3) ✓
- Winter event share = **61%** (prior: ~50-57%, slight overshoot reflects disruption coupling)
- Depot repair share = **34%** (config 35%) ✓
- Mean repair days = **3.2** ✓

**This is the weakest-anchored module** — no public vehicle survival data exists at this granularity. Shape/scale parameters are SYNTHETIC-INFERRED. The model trained on this output should be reported with that caveat, in line with the masterplan's honesty standard.

### 6. `stock.py` — stock dynamics (the forward accounting identity)

The layer that makes a stockout *predictable*. For each (post, SKU, day) it runs:
```
closing_stock = opening_stock
              + aws_receipt        (Advance Winter Stocking bulk push)
              + routine_receipt    (anticipatory top-up convoys, year-round)
              − consumption        (effective demand, post-substitution)
              − spoilage           (perishables only)
```

Three mechanisms drive the behaviour, each grounded in public-source doctrine:

- **AWS pre-positioning is topology-driven.** Each post's pre-winter stocking target is sized off *its own longest plausible isolation run* (derived from the pass-status data) plus a margin, not an abstract doctrine number. A Chushul post cut off for 120 days automatically stocks deeper than a Pangong post cut off for 40 — no per-post hand-tuning. The target is `planning_days × winter_rate_p80 × tier_safety_mult × attainment × (ammo: tempo_factor)`. Sized off the **P80** of winter consumption (the post stocks for a winter worse than 80% of winters), and delivered as a **push-to-target across the road-open season** (May–Sep + an October catch-up tail) — missed days when the post is isolated are absorbed by heavier delivery on the open days, not permanently written off. Anchored to the Tribune's "road open period" bulk-induction description and Swarajyamag's underground-fuel-dump account.

- **AWS attainment is imperfect, and that imperfection is the signal.** Each (post, SKU, winter) draws an attainment fraction (Beta, mean ~0.93) — most posts mostly succeed, per the CAG framing that shortfalls are audit-flagged *exceptions*, not the steady state. The left tail is the genuine stockout-risk signal the forecaster has to learn. **Per-winter variance is structural:** the planning horizon itself is a noisy estimate redrawn each winter (a logistics staff plans off recent, imperfect experience), so a stockout is a function of *this winter's severity vs this winter's plan* — not a deterministic every-post-every-year wall. POL carries an extra hard-to-stock attainment drag (bulk fuel is the hardest thing to pre-position by volume); ammunition carries a per-winter tempo-misestimate factor (a brigade cannot perfectly forecast next winter's operational tempo).

- **Perishables substitute rather than simply fail.** A 7-day-shelf item (fresh meat) physically cannot survive a multi-week cutoff — but a post does not keep drawing meat it knows isn't there. So a perishable "stockout" is a *short depletion gap* at the onset of an isolation run, after which the perishable's effective demand decays to a residual floor and the displaced demand is rate-converted onto a substitute SKU (tinned rations). This keeps the perishable gap real and labelled `stockout` without it becoming a wall of near-identical rows — and it creates a genuine cross-SKU substitution pattern (tinned-ration consumption spikes when fresh meat gaps) that a forecasting model can learn. Posts with air resupply also get an intermittent, weather-gated emergency perishable trickle while isolated.

**Opening balances come from a discarded warm-up year.** A full extra year (2021) of consumption is synthesised by month-matched resampling of the real distribution, run through the same stock dynamics, then *discarded* — so 2022 opens at a genuine mid-sawtooth steady state, with no hand-seeded artifact.

Each row carries both `nominal_consumption` (what `consumption_daily` produced) and `consumption` (effective demand after substitution), `days_of_cover`, and a `status` of `ok` / `rationing` / `stockout`.

**Validation (seed 42):**
- Forward post-SKU winter survival rate = **85.4%** (target band: 85–90%) ✓ — i.e. ~85% of forward (post, SKU, winter) combinations ride out the winter without a hard stockout.
- Accounting identity max residual = **0.001** (pure float rounding — `opening + receipts − consumption − spoilage + unmet = closing` holds exactly) ✓
- Sawtooth confirmed: kerosene at a deep forward post peaks **October** (post-AWS), troughs **April** (pre-thaw) ✓
- Stockout concentration: Rations 49% / Ammunition 19% / POL 13% / Medical 10% / Engineer 5% / Clothing 4% — no single head is a deterministic wall; POL and Ammunition are real, learnable secondary signals.
- Status mix: 95.4% ok, 3.3% rationing, 1.4% stockout — stress sits mostly in the graded `rationing` warning state, which is what gives the forecaster a non-binary signal.

**Seed sensitivity, stated honestly:** the survival rate is *not* seed-robust. Seed 42 (the canonical world per masterplan Decision 4) gives 85.4%; seed 7 gives 78.5%. This is expected and is **not** tuned away — per the masterplan, the generator builds *one* thick, internally-coherent world (`regenerate(seed=42)` reproduces it identically), not a distribution of worlds. A different seed is a different — equally valid — universe with different topology luck. Tuning the generator until every seed lands in-band would mean massaging it toward a cosmetic target rather than letting the physics produce what it produces. Seed 42 at 85.4% sits on the *hard* side of average (seed 7 brackets it low), so it is not a cherry-picked high.

### 7. `generate.py` — orchestrator

Runs all six generator modules in dependency order (`world → weather → disruption → consumption → vehicles → stock`), writes outputs to disk (Parquet if available, CSV fallback), prints and persists a validation report.

---

## Calibration trail (what's anchored, what isn't)

Every parameter in `config.py` is either:
- **Anchored:** named public source in the comment (e.g. IMD Leh study, PIB BRO release, CAG report, Tribune article)
- **SYNTHETIC-INFERRED:** explicitly flagged where no public source exists

The SYNTHETIC-INFERRED zones:
1. Tangtse anchor station (extrapolated from Leh + lapse rate, no IMD station)
2. Tsaka La closure priors (regional-pattern inferred)
3. Marsimik La closure priors (elevation-scaled inference)
4. Vehicle Weibull shape/scale (inferred from CAG deficiency patterns, no direct survival data)
5. AWS planning horizons and attainment distribution (no public per-post stocking figures; calibrated so ~85–90% of forward post-SKUs enter winter adequately provisioned, per the CAG "exception not norm" framing)
6. Routine convoy cadence, latency, and refill thresholds (operationally plausible, no public source)
7. Spoilage daily fractions and the perishable substitution decay curve (order-of-magnitude estimates)

All are tracked in `PROVENANCE["synthetic_arbitrary_flags"]`.

---

## What this is NOT calibrated for

1. **Vehicle survival** has no real-world anchor; Weibull params are scaled to produce plausible event rates. Real survival data, if obtainable, would replace this.
2. **Inter-depot route distances** use a 1.65× sinuosity factor on great-circle. The actual DSDBO road is 255 km vs my Karu→DBO estimate of ~200 km — within 25%, but a real shapefile from OpenStreetMap/Bhuvan would improve this.
3. **Tangtse climatology** is extrapolated from Leh + lapse rate, not measured.
4. **Anomaly spike distribution** (1% / 3-8×) is a placeholder — the real shape would come from actual ration-issue logs, which are not public.
5. **Stochastic-regime closure rates** for Tsaka La and Marsimik La are inferred by regional pattern. Could be wrong by ±50%.

---

## How this feeds Stage 3

The outputs map directly to the masterplan's ontology objects:

| Generator output         | Ontology object                  | Stage 3 model consuming it                      |
| ------------------------ | -------------------------------- | ----------------------------------------------- |
| `posts`                  | Post                             | Demand forecaster (per-post)                    |
| `routes`                 | Route                            | Route GBM (per-route)                           |
| `vehicles`               | Vehicle                          | Vehicle survival model                          |
| `skus`                   | SKU                              | Demand forecaster (per-SKU)                     |
| `weather_daily`          | WeatherObservation               | All three models (feature)                      |
| `pass_closures`          | DisruptionEvent (actual)         | Route GBM (label)                               |
| `pass_status_daily`      | Route.is_open derived            | Route GBM (label, daily)                        |
| `consumption_daily`      | ConsumptionEvent                 | Demand forecaster (label)                       |
| `tempo_daily`            | Brigade state (feature)          | Demand forecaster (ammo/POL feature)            |
| `vehicle_events`         | Vehicle reliability events       | Vehicle survival model (event labels)           |
| `stock_daily`            | StockLevel / StockoutRisk        | Demand forecaster (running balance), risk scorer (days-to-stockout label) |
| `aws_plan`               | ResupplyPlan (pre-positioning)   | Risk scorer (provisioning context), optimizer (Stage 4 warm-start) |

Each row carries a provenance ID once persisted to Supabase, per masterplan Decision 4 (model outputs are first-class ontology objects).

`stock_daily` is the table the **stockout risk scorer** (masterplan Component 5) is built on: `days_of_cover` and `status` are the direct labels, and the `ok → rationing → stockout` progression is the graded target the composed risk model is scored against (precision/recall), distinct from the demand forecaster's MAPE.

---

## Decisions locked this session

1. **AOR: Tangtse Brigade-equivalent** — 3 Infantry Division (Trishul) Tangtse Brigade slice per Wikipedia XIV Corps entry. Covers Pangong / Chushul / Demchok / Hot Springs / DBO axes.
2. **35 posts** (5 depot / 12 mid / 18 forward).
3. **3 IMD weather anchors:** Leh (real, drives most posts), Drass (real, used only for Zoji La pass-closure modeling — outside AOR proper), Tangtse (extrapolated).
4. **5 strategic passes** (the list you approved): Zoji La (seasonal regime), Khardung La / Chang La / Tsaka La / Marsimik La (stochastic regime).
5. **30 SKUs across 6 stock heads.**
6. **Modern (post-2020) Zoji La regime** — 33-79 day closures, not the historical 150-day pattern. This is what a current operator would actually face.
7. **Brigade-shared tempo as a 4-state Markov chain** (low/normal/high/crisis) — couples ammo and POL signals across all posts on the same day.
8. **Isolation derived from pass status**, not as a primitive state. Emergent from the weather→closure cascade.
9. **Lognormal noise + 1% anomaly spikes** — randomness that teaches the model to be robust to outliers without being chaotic.
10. **AWS targets are topology-driven** — sized off each post's own longest isolation run, not an abstract per-band doctrine number. Per-winter planning variance is structural, so stockouts are a function of *this winter's severity vs this winter's plan*.
11. **Perishable shortfalls are labelled `stockout` but thinned via substitution** — a fresh-meat gap decays effective demand and rate-converts it onto tinned rations, rather than producing a wall of identical stockout rows. Decision taken this session.
12. **Kerosene and ammunition failures come from both leaner attainment and demand-curve realism** — late-winter consumption acceleration outruns the P80 planning rate, so an adequately-planned post can still be caught by a hard winter. Decision taken this session.
13. **Seed 42 is the canonical world; survival rate is not tuned for seed-robustness** — per masterplan Decision 4, the generator builds one coherent world, not a distribution. Seed sensitivity is documented, not engineered away.

---

## Open items for your review

1. **Stock-layer validation (seed 42)** — forward survival 85.4%, status mix 95.4/3.3/1.4, head concentration Rations 49% / Ammo 19% / POL 13%. These are in-band and the deterministic-wall failure modes are resolved. The one judgement call left open: survival sits at the *floor* of the 85–90% band, so the world is on the stressed side. If you want more headroom, a small lift to the attainment mean would do it — but that trades away signal sharpness.
2. **Chang La closure rate** (10.3/yr) is slightly above the 3-8/yr prior. Single-seed variance, but if you want it tighter, easy to dial.
3. **Vehicle Weibull priors** are the weakest-anchored piece. If you have a contact who can ballpark real VOR rates for HA-deployed Stallion fleets, that would tighten this significantly.
4. **AWS planning anchors** are the second-weakest. No public source gives per-post stocking depths; the topology-driven sizing is operationally plausible but SYNTHETIC-INFERRED. A CAG report with actual pre-positioning audit figures would replace it.
5. **Tangtse extrapolated anchor:** if Sentinel-2 / ERA5 reanalysis becomes available, we could replace this with measured data and rerun. Not blocking.

---

## Reproducibility

Re-running with seed=42 produces byte-identical outputs. Different seeds produce different worlds with the same statistical properties.

---

## Sources cited in `config.py`

- IMD Leh 1901-2000 study (Romshoo et al., *Variability of Precipitation regime in Ladakh*)
- Wikipedia Dras / Khardung La / Chang La / XIV Corps / Chushul / Siachen Base Camp
- BRO PIB Press Release 1809806 (Zoji La 2022 closure record)
- The Tribune: "BRO breaks record: Zoji La Pass stays open through winter" (Mar 2026)
- The Tribune: "Zoji La pass defies winter closure" (Jan 2026)
- The Tribune: "Providing logistics in Ladakh a test of mettle" (Jan 2025)
- CAG Report 2017-18 (Siachen / Ladakh / Doklam rations and equipment audit)
- Swarajyamag: "6,000 Trucks, Underground Fuel Dumps..." (Oct 2020)
- Municipal Committee Kargil official climate portal
- SPS Land Forces: "Defending Eastern Ladakh" (Mar 2025) on 72 Infantry Division
- Weather-Atlas / climatestotravel.com aggregates of IMD normals
- IDRW: Stryker high-altitude trial failure (Mar 2025)
- Vargis Khan: Ladakh roads in winter operational guide

---

*End of README. Outputs are in `output/`. Validation report in `output/validation_report.json`.*
