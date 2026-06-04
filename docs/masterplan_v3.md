# Project Bastion — Master Context (v3, Build-the-System)

*Founder: Eshan Ghose | Entity: Silverpot Defence Technologies | Status: Pre-incorporation, build phase*

*This document supersedes v2. It reflects a deliberate pivot away from "polish a static demo for procurement" and toward "build the actual system end-to-end on synthetic data." Customer-facing work (iDEX, Army outreach, advisor pitches) is parked, not cancelled. The current operating mode is: founder + Claude building a real ontology, real models, real automation, on real infrastructure, against synthetic data we generate ourselves.*

---

## Part 1 — Why this version exists

v2 (Path C) was a procurement-driven plan. It optimized for: get something polished in front of an iDEX evaluator and a retired Lt Gen as fast as possible, accepting that "polished" meant a static React app reading hand-curated JSON with pre-computed model outputs baked in. The trade was deliberate — speed and presentability in exchange for the system not actually being real.

Two things changed.

First, the founder's appetite for actually building shifted. The Path C framing assumed a non-technical founder who would not run code. That's still true in the sense that the founder doesn't write code — but it's no longer true in the sense that the founder is willing to oversee a real engineering build, with Claude doing the writing and execution. The constraint isn't "no code"; it's "no code the founder personally types or runs locally."

Second, the procurement framing was making the product worse. A scripted demo with pre-computed math has a ceiling — it can't surprise anyone, including the founder. Building a real system that runs on synthetic data has no such ceiling. The system either works or it doesn't, and the answer is discoverable rather than scripted.

v3 inverts Path C's central trade. Build the thing. The demo becomes a window onto a working system rather than the system itself.

---

## Part 2 — The problem Bastion solves

*Unchanged from v2. Reproduced here so this document is self-contained.*

Forward sustainment in Ladakh, Arunachal Pradesh, Sikkim, and Siachen is a four-variable optimization problem currently solved by experienced JCOs with whiteboards, radio voice traffic, and intuition. The four variables:

- **Demand** — what each post will consume in the next 7/30/90 days, by SKU
- **Supply** — what's in which depot, in what condition, with what shelf life
- **Transport** — which roads/passes/helipads are open, with what capacity, under what weather
- **Disruption** — when does Zoji La close, when does the next storm hit Tawang, when does a vehicle deadline cascade into a stockout

Each variable is tracked in a different system or no system at all. There is no single pane of glass where a Brigadier (Logistics) at a Corps HQ can see *"Post 14 in Sub-Sector North will run out of kerosene in 9 days, the route closes in 6, here are your three options."*

That is the gap Bastion closes — eventually, in production. Right now, in v3, we are building the system that would close it, against synthetic data, with no customer.

---

## Part 3 — What we are explicitly NOT building

This is the part where v3 differs hardest from v2 and from most defence-tech startup roadmaps. Naming it explicitly so it stays settled:

- **Not an inventory management system.** No stock count entry forms. No requisition workflows for humans. No vehicle dispatch UI. The Army has SAMBHAV/ASIGMA/Excel/paper for these. We integrate with them eventually; we never replace them.
- **Not a data-acquisition product.** No scrapers, no PDF extractors, no source catalogue maintenance. The data-engineering Python currently in the `eshan6/project-bastion` GitHub repo is legacy from the v2 era; it does not constrain v3.
- **Not a real-time system.** Batch processing with a manual "trigger replan" button. Military logistics does not replan every six seconds in reality.
- **Not currently a product-with-customers.** No iDEX submission, no Army outreach, no advisor pitches in the current build phase. Those resume when the system is real and we have something worth showing.

The thing being built is the **decision-support intelligence layer** that would sit on top of whatever inventory system the customer already runs. Ontology, forecasts, risk, optimization, alerting, lineage. Six components, named explicitly in Part 5.

---

## Part 4 — Settled architectural decisions

Four decisions made at the start of v3. Treat as locked unless new information genuinely changes the analysis.

1. **Hosting: Supabase free tier.** PostgreSQL 15+ with PostGIS extension, managed. Free tier comfortably handles our scale (≤500 MB database, 2 GB file storage, 50K MAU equivalent). Founder creates the project once via web UI; everything after that is schema migrations and queries Claude writes. No local Postgres on the founder's laptop.

2. **Synthetic data fidelity: thick.** Target dataset is roughly 50–100 posts × 30 SKUs × 3 years of daily history ≈ 1.5–3 million stock/consumption rows, plus weather, disruption events, convoy tempo, vehicle reliability events. The generator is calibrated against publicly reported patterns (CAG audits, RTI returns, IMD climatology, news archives of pass closures) so that the world it produces is internally coherent and behaviourally realistic, not arbitrary. The model learning the generator's patterns is then a legitimate proof-of-functionality.

3. **Execution mode: batch with manual replan trigger.** Scheduled daily ticks generate forecasts, update risk scores, and write alerts. A manual "replan now" button (and eventually a "what if X happens" mode) triggers the optimizer on demand. No websockets, no live event streams, no second-by-second updates.

4. **Model outputs are first-class ontology objects.** `DemandForecast`, `StockoutRisk`, `DisruptionEvent` (predicted vs actual), and `ResupplyPlan` are all persisted Postgres rows with foreign keys back to the inputs they were derived from, the model version that produced them, and the data snapshot they ran on. Predictions live in the database. This is what makes the system Palantir-shaped rather than a generic ML app — lineage is structural, not bolted on.

These four decisions cascade into everything else.

---

## Part 5 — The six components

The system being built, decomposed. Each component has a clear contract with the others.

### Component 1 — Ontology

PostgreSQL schema. Domain objects: **Post, Depot, Route, RouteSegment, Vehicle, VehicleClass, Convoy, SKU, StockHead, StockLevel, ConsumptionEvent, WeatherObservation, DisruptionEvent, Requisition, DemandForecast, StockoutRisk, ResupplyPlan**. Provenance objects: **Source, RawArtifact, Claim, EvidenceLink, ModelVersion, DataSnapshot**. All with real foreign keys, real constraints, PostGIS geometry where appropriate (Post.location, RouteSegment.path, Depot.location), proper indices on time-series and lookup columns.

This is the load-bearing piece. If the schema is wrong, everything else is wrong.

### Component 2 — Synthetic data generator

Parameterised, deterministic, seedable. Inputs: AOI (default: Eastern Ladakh, ~32.5–35.5°N, 76–79.5°E), number of posts, number of depots, time range, RNG seed. Outputs: a fully populated ontology — posts at realistic altitudes with plausible road/air connectivity, route topology with strategic-vs-tactical classification, SKU catalogue across six stock heads, vehicle fleet, three years of daily weather (calibrated against IMD climatology), three years of daily consumption per (post, SKU) coupled to weather and tempo, disruption events drawn from publicly observed pass-closure patterns, vehicle-deadline events drawn from CAG-style reliability priors.

The generator is the single source of truth for the world. `regenerate(seed=42)` produces the identical universe every time.

### Component 3 — Models

Three workhorse models. Trained on the synthetic data, persisted as artifacts in Supabase storage, served from a Python service Claude can call.

| Model | Algorithm | Output | Persistence |
|---|---|---|---|
| Demand forecast | XGBoost per (post, SKU), quantile regression | P10 / P50 / P90 at 7/30/90-day horizon | `DemandForecast` rows |
| Route availability | Gradient-boosted classifier | P(open) per RouteSegment per day, 14-day horizon | `DisruptionEvent` predicted rows |
| Vehicle reliability | Random survival forest (Cox fallback) | P(deadline within next mission) | feature on `Vehicle` |

Honest framing: synthetic accuracy is meaningless as a real-world claim. We will report MAPE / AUC / concordance against held-out synthetic, and we will explicitly label them as proofs-of-functionality, not proofs-of-accuracy. Real-world validation happens whenever real data arrives, if ever.

### Component 4 — Optimizer

OR-Tools MIP. Takes current ontology state + forecast quantiles + route-availability probabilities + vehicle reliability scores. Emits `ResupplyPlan` rows: which vehicles carry which SKUs from which depot to which post via which route, on which day, with what expected cost / time / risk. Multiple plans per request (3–5 alternatives ranked by different objectives — lowest cost, fastest delivery, lowest risk).

Warm-start enabled for fast re-plans (<5s) when a disruption fires.

### Component 5 — Automation / alerting loop

Daily tick (scheduled via Supabase cron / GitHub Actions / similar — finalised at build time). For each tick:

1. Generator advances the synthetic world one day (in dev; in production this would be a no-op and real data would arrive instead).
2. Forecast models run, write fresh `DemandForecast` rows.
3. Route model runs, writes/updates `DisruptionEvent` predictions.
4. Vehicle model runs, updates `Vehicle.reliability_score`.
5. Risk evaluator runs: for each (Post, SKU), compute days-to-stockout from latest forecast vs current stock. Where it crosses tier-specific thresholds (Tier 1 SKUs: 14 days; Tier 2: 7 days; Tier 3: 3 days), emit `StockoutRisk` row and an alert.
6. Where `DisruptionEvent.probability > 0.6` within the next 7 days, emit alert.
7. Where `Vehicle.reliability_score` drops below class threshold, emit alert.
8. Optimizer does NOT run on every tick — only on manual trigger or when an alert crosses a "critical" threshold that warrants a fresh plan.

Alerts are themselves ontology rows (`Alert` object, joined to whatever triggered them). Lineage from alert → risk → forecast → input data → snapshot is queryable in one SQL view.

### Component 6 — Visibility layer

How we (and eventually a customer) see what the system is doing. Options:

- Extend the existing Vercel FSP demo to read from Supabase instead of static JSON. Pros: reuse existing UI work, single demo URL. Cons: the existing demo's interaction model (timeline scrubber, scripted scenarios) is wrong for a live system.
- Build a new dashboard against the live data. Pros: shaped for the real system. Cons: more work, duplicate UI codebases.
- Internal-only for the build phase. Just a SQL client + a handful of materialised views + maybe a notebook. Decide on a customer-facing UI later when there's a customer.

**Tentative call: internal-only for the build phase, decide on customer-facing UI in v4 of the masterplan when the system is real.** The existing FSP demo on Vercel stays up as a separate artifact (marketing-state, not connected to anything) until we decide what to do with it.

---

## Part 6 — Build sequence

No calendar weeks attached. Sequenced by dependency, not by deadline.

**Stage 1 — Substrate.**
1. Founder creates Supabase project, hands Claude the credentials.
2. Claude writes ontology schema migration. All tables, all FKs, all indices, PostGIS columns.
3. Claude writes generator skeleton — world creation (posts, depots, routes, SKUs, vehicles) deterministic from seed.
4. Founder runs the migration and the generator (one button each, or Claude runs them via Supabase's SQL editor / a hosted notebook). Verify by querying.

**Stage 2 — World physics.**
5. Generator extension: three years of daily weather, calibrated against IMD climatology priors.
6. Generator extension: daily consumption per (post, SKU), coupled to weather + tempo + holiday/religious calendar + lognormal noise.
7. Generator extension: disruption events on strategic passes, calibrated against publicly observed closure patterns.
8. Generator extension: vehicle reliability events, calibrated against CAG-style audit findings.

**Stage 3 — Models.**
9. Train demand forecasters (one per top-N SKU per post type — exact slicing decided at build time based on what learns well). Quantile regression for P10/P50/P90. Persist as Supabase storage artifacts.
10. Train route-availability classifier on weather → P(open).
11. Train vehicle survival model.
12. Wire all three into a Python service that writes predictions back as ontology rows.

**Stage 4 — Optimizer + automation.**
13. OR-Tools MIP formulation. Inputs: current state + forecasts + risks. Output: `ResupplyPlan` rows.
14. Risk evaluator and alert generator (Component 5).
15. Scheduled daily tick (mechanism TBD — likely Supabase cron + GitHub Actions).

**Stage 5 — Lineage UI and queries.**
16. SQL views joining alerts → risks → forecasts → models → snapshots. Test by walking from a single alert all the way back to the seed.
17. Decide on Component 6 (visibility layer) and build accordingly.

The stages are dependent but the lengths inside each stage are not predetermined. Stage 1 is small and fast. Stage 2 is the longest because the generator is the load-bearing piece. Stages 3–4 are medium. Stage 5 is small.

---

## Part 7 — Parked context

These are real parts of the broader project that are explicitly not active right now. Listed so they are not lost, and so a future v4 can resume them.

- **Incorporation, DPIIT, MSME, GST, MoD vendor registration, trademark.** Pre-incorporation status remains. Not blocking the build.
- **iDEX Open Challenge application.** Resumes when there is a working system to point at.
- **Direct Army outreach via QMG/MGS branches.** Same.
- **Advisor search — retired Lt Gen with logistics background.** Same.
- **Phase 2 hiring sequence (ML / backend / OR engineer).** Same. Founder + Claude is the team for the current phase.
- **Pricing model finalisation.** Premature. Resumes pre-pilot.
- **Lighthouse (Silverpot's ISR product).** Remains paused per v2 decision.
- **The original 18-month budget envelope (₹1.20–1.50 Cr).** Mostly intact; current build phase has near-zero burn (Supabase free tier, Vercel free tier, no hires).

---

## Part 8 — Decisions already made

Settled context. Do not re-debate without new information.

1. **Bastion is the lead product.** Lighthouse remains paused.
2. **Operating mode: build the system on synthetic data.** No customer in the current phase. The system either works or it doesn't, and that is discoverable.
3. **Hosting: Supabase free tier** for Postgres + PostGIS + storage. Vercel free tier for any future web frontend. GitHub for code.
4. **Synthetic data fidelity: thick.** ~1.5–3M rows, calibrated against public patterns.
5. **Execution mode: batch with manual replan trigger.**
6. **Predictions are first-class ontology objects** with full lineage.
7. **Architecture mirrors Palantir's ontology pattern**, right-sized. Postgres + PostGIS, no graph database, no event streams.
8. **No offensive cyber, no offensive autonomy.** Bastion is sustainment — administrative, defensive, dual-use.
9. **The existing data-engineering Python in the GitHub repo is legacy** from the v2 era. Not deleted, but not on the path of v3. The v3 build is fresh.

---

## Part 9 — Open questions

Ranked by how much they'd change the build if answered differently.

1. **Where do scheduled jobs run?** Supabase has pg_cron; GitHub Actions has scheduled workflows; a small always-on worker on Fly.io or Railway free tier is another option. Each has trade-offs around credentials, observability, and what state the job needs to read/write. Decide before Stage 4.
2. **Generator calibration depth.** Thick synthetic implies the generator should be calibrated against real patterns. How deep does calibration go before we're back to "Path C without the customer"? Default position: each calibration source gets named explicitly in the generator code with a comment pointing to the public document it's drawn from, and the generator's behaviour is documented separately. If a parameter has no public source, it's flagged as "synthetic-arbitrary" and the documentation says so. This keeps us honest without re-importing all of Track 2's scraping work.
3. **What happens to the existing Vercel FSP demo?** Three options: (a) leave it alone as a separate marketing artifact; (b) rebuild it against the live Supabase backend in Stage 5; (c) replace it with a new dashboard. Decide in Stage 5 once the system is real.
4. **What happens to the existing `eshan6/project-bastion` GitHub repo?** It currently holds the v2 data-engineering Python files. Three options: (a) reuse the same repo, push v3 alongside in a new directory; (b) archive it and start fresh; (c) leave it as legacy reference, create `project-bastion-v3` or similar. Recommendation: option (a), with v3 work in a clearly named subdirectory and a top-level README explaining the layout.
5. **Visibility layer call.** Per Component 6 — internal-only for the build phase is the tentative call; revisit when the system is real.

---

## Part 10 — Working style notes

*Operating principles, unchanged from v2. These are how Eshan and Claude work together regardless of what is being built.*

- **No patchwork fixes.** Always full, complete, self-contained code blocks. When something breaks, rewritten clean.
- **Justify before proceeding.** Eshan asks Claude to justify claims and approach before building. Healthy skepticism welcomed; suggestions land better *after* a working MVP than as upfront clarifying questions.
- **Realism over generic.** Reject generic solutions. Domain-grounded, behaviourally accurate, specific.
- **Foundry data engineer mindset for data work.** Interrogate, don't describe. Pipelines, ontologies, object relationships. Surface non-obvious patterns. Prioritise insights that change a decision.
- **Architectural philosophy: build toward Palantir parity, right-sized for the current stage.** Always map features to what the eventual customer needs, even though we're not currently customer-facing.
- **Right-sized over over-engineered.** No full RDF graph databases when Postgres + graph queries work. No infinite abstraction.
- **No technical instructions to execute.** Eshan is non-technical. All deliverables are files or hosted things; nothing for the founder to run locally beyond the occasional click in a web UI.

---

## Part 11 — Single-track project notes

v2 ran two parallel tracks (chat-Claude on demo content, Claude Code on scrapers). v3 collapses this to one track: this conversation, building the system end-to-end on Supabase.

- The existing repo's v2 contents become legacy reference. v3 work lives in a clearly demarcated subdirectory (final layout decided in Stage 1).
- The existing FSP Vercel demo stays up as an independent artifact until Stage 5 decides what to do with it.
- `CLAUDE.md` at the repo root (which briefed the Claude Code track) can be left as-is or updated to reflect that v2's parallel-track structure no longer applies. Not blocking.

---

*End of master context v3. Sessions starting fresh on this project should treat Parts 1–8 as settled and engage primarily with Part 9 (open questions) and the Part 6 build sequence.*
