# Forward Stockout Predictor — Methodology

*Project Bastion, Silverpot Defence Technologies. Block A, Wk6 lock.*

---

## The trade, stated upfront

This demonstration is built on synthetic and publicly-sourced data. It does not use, reproduce, or claim to reproduce any classified or restricted Indian Army information. Real Army scales of issue, post-level headcounts, depot stocking levels, and unit-level ORBAT details are not public, and this demo does not attempt to recreate them.

What this demo does claim is that the architecture, ontology, modelling approach, and operator-facing workflow are correct — and that, when integrated with real Army Service Corps, Army Ordnance Corps, and EME data feeds during a Phase 3 pilot, the same platform will produce decision-grade predictions of stockout risk on real forward posts.

The data shown here is illustrative. The platform is real. Where any number — a consumption rate, a vehicle reliability prior, a closure probability — is illustrative rather than sourced, it is graded explicitly in the underlying data files (provenance grades A, B, or C, defined below). Anyone reviewing the demo can audit any specific entity in seconds.

This is the trade. The rest of the document explains how it was constructed, what it can and cannot show, and what changes when real data flows.

---

## What FSP is

The Forward Stockout Predictor is the wedge product for Project Bastion — Silverpot's predictive sustainment platform for high-altitude formations. It is scoped to a single AOI (Eastern Ladakh, XIV Corps area) and a single problem: predicting per-post per-SKU stockout risk over a 90-day horizon, accounting for terrain, weather, route closures, and vehicle reliability.

The demo presents the same operator-facing surface that production Bastion will present at Brigade or Corps logistics headquarters. Map view of the AOI with hex-binned post status. Drill-down from sub-sector to post to SKU. Timeline scrubber across 90 days. Three resupply-option cards on every critical-state alert, with cost / time / risk tradeoffs. Auto-generated SITREP export in standard military logistics format.

Three scripted scenarios drive the narrative: a normal-operations baseline, a Zoji La closure cascade, and a vehicle deadline cascade. An additional unscripted what-if mode lets the operator inject arbitrary disruptions and watch the system re-plan in real time.

The demo's design assumption is that an experienced retired Lt Gen logistics advisor watching FSP for ten minutes can recognize the geographic and operational realism. That assumption is testable; we welcome it being tested.

---

## What's synthetic and what's not

Every entity in the demo's data layer carries a `provenance_grade` field — A, B, or C — defined consistently across all five JSON files in `data/fsp/`.

**Grade A** means publicly documented. Coordinates, names, altitudes, route distances, vehicle specifications, and major operational facts that can be verified against open sources — Wikipedia, MoD annual reports, BRO publications, manufacturer brochures, news archives, CAG performance audits, Lok Sabha Standing Committee reports. Roughly two-thirds of the demo's named entities fall into this grade.

**Grade B** means the area, terrain feature, or category is publicly known, but the specific instance shown is illustrative. The Galwan valley is publicly known; the exact picket position labelled `POST-003 FOB Galwan` in the demo is a representative position consistent with reported deployments, not a claim about a specific real picket. The Spanggur Gap is publicly named; the specific sub-position is illustrative. Roughly one-quarter of entities fall here.

**Grade C** means generic — the entity exists for demo coverage but is not modelled on any specific real entity. `POST-004 PP-North-1` is the clearest example: patrol points are numbered in real life, but the numbering scheme and exact locations are not public, so a generic designator is used. Grade-C entities are deliberately rare; only one post and one route segment carry this grade in the locked data files.

This grading is enforced at the file level. If a reviewer wants to audit which specific posts are real and which are illustrative, they open `data/fsp/posts.json` and read the `provenance_grade` field on each entry. The same applies to routes, vehicles, and SKUs.

Numerical figures — consumption rates, reliability priors, costs — sit in a different category. These are illustrative central estimates consistent with publicly reported patterns, not direct citations of restricted Army data. The next section explains how each was constructed.

---

## How the data was constructed

### Posts and depots (`posts.json`)

Fifteen forward posts and four depots covering four sub-sectors of Eastern Ladakh — DBO axis, Pangong-Chushul, Demchok-Hanle, and Kargil-Drass. Coordinates for grade-A posts are taken from public mapping sources and verified to within 50m. Altitudes are from public elevation data (SRTM, Bhuvan). Names use the publicly documented form where one exists; generic designators where none does.

Notional formation assignments — `POST-001` to XIV Corps, `POST-005` to 3 Inf Div, `POST-013` to 8 Mtn Div, and so on — reflect publicly documented divisional Areas of Responsibility. Brigade-level assignments are deliberately illustrative; specific brigade-to-post mappings are not part of the public record and the demo does not claim them.

The four depots — Leh ASC, Karu Sub-Depot, Hanle Sub-Depot, Kargil Main — are at publicly known locations and serve their notional formations as the public record describes. Sub-depot supply relationships are realistic but illustrative at the level of which posts each sub-depot serves directly.

### Routes (`routes.json`)

The routes file uses a hybrid model: strategic Lines of Communication (the Srinagar-Leh axis via Zoji La, the Manali-Leh axis via Baralacha and Taglang La, and the air bridge from Hindon and Chandigarh) are fully segmented at every chokepoint with independent closure behaviour. Tactical post-feeder routes are modelled as single-segment edges for design economy.

Pass altitudes — Zoji La 3,528m, Baralacha La 4,890m, Taglang La 5,359m, Khardung La 5,359m, Chang La 5,360m — are taken from public sources and verified to within 50m. Route distances are approximate road distances from public mapping. Seasonal availability patterns (Zoji La closed Dec-Apr, Manali road closed Oct-May, etc.) reflect multi-year patterns documented in BRO bulletins, news archives from Tribune, Greater Kashmir, and Reach Ladakh, and IMD weather records.

Closure-driver categories (snow avalanche, landslide, river crossing flood, ice on track) are taken from publicly documented BRO maintenance records and news archives. Specific closure probabilities per day per pass are illustrative central estimates — real-data deployment will fit these to the actual 10-15 year IMD record per chokepoint.

### SKUs (`skus.json`)

Thirty SKUs across six stock heads (Rations, POL, Ammunition, Medical, Clothing, General) — the 80/20 of operational cost and risk in Eastern Ladakh sustainment. The stock-head structure mirrors publicly documented Army Service Corps and Army Ordnance Corps organisational categories.

Specific SKU choices — Composite Ration Pack, HSD diesel, kerosene/SKO, 5.56×45mm ball ammunition, 81mm mortar HE, oxygen cylinders, ECC mittens — are publicly documented in MoD annual reports, manufacturer disclosures, and CAG audits. Calibers and ammunition families are not classified information; they appear in DRDO and Ordnance Factory Board publications and parliamentary procurement records.

Consumption rates are illustrative central estimates. The methodology for setting them: identify the publicly cited multiplier patterns between terrain classes (the 3-4× baseline difference between plains and high-altitude consumption that recurs in CAG performance audits and Lok Sabha Standing Committee testimony), then set demo numbers that produce that multiplier shape. The kerosene multiplier from plains to ECC in this demo is 12×, with a 1.6× winter uplift on top — within the publicly cited range, but the specific point estimates are not claimed as Army scales of issue.

Notional headcount is not in `posts.json` precisely because it is operationally sensitive. Headcount assumptions are scenario-internal in `scenarios.json` and clearly documented as illustrative central estimates per post type.

### Vehicles (`vehicles.json`)

Nine vehicle classes spanning road, animal, and air lift. The Stallion (Ashok Leyland), Topaz (Ashok Leyland), ALS (Tata LPTA), and ALSV families are all publicly documented in MoD annual reports and manufacturer brochures. Payload, range, fuel type, and dimensions are taken from public manufacturer specifications.

The mule and porter classes are real — the Indian Army Animal Transport companies remain operational at SHA and ECC posts where motor transport cannot reach, and contracted civilian porter use is publicly documented in Siachen-class operations.

Helicopter classes — Cheetah/Cheetal, Mi-17 V5, CH-47F Chinook — are publicly documented in IAF inventory disclosures. Sea-level payload figures are from manufacturer specifications. Altitude derate curves follow published rotorcraft physics; specific derate percentages at 5,000m and 5,500m are illustrative central estimates aligned with publicly known operating limits at locations like Daulat Beg Oldi and Siachen ALGs.

Reliability priors — deadline events per 1,000 vehicle-km, helicopter and mule availability fractions by season — are illustrative central estimates aligned with patterns documented in CAG audits of Army vehicle fleet condition. Real-data deployment will fit these to actual EME workshop records.

Cost-per-tonne-km figures are dimensionless ratios anchored to a Stallion-on-paved-road baseline of 1.0. The relative ratios — Mi-17 at 9× truck baseline, mule at 8×, porter at 25× — are what matter for optimizer reasoning. Absolute INR figures in the resupply-option cards are illustrative for the demo and do not represent specific MoD costing.

### Scenarios (`scenarios.json`)

Three scripted scenarios. Each is a 90-day temporal sequence with explicit disruption events, daily projections for focal posts and SKUs, and three resupply options per critical-state alert.

Cascade math is computed against the locked entities in the other four files: a kerosene-burn calculation pulls the per-soldier-per-day rate from `skus.json`, the headcount from the scenario's documented assumption, and the terrain class from the post's altitude band. Stallion convoy capacity at DBO altitude pulls the sea-level payload from `vehicles.json` and applies the documented derate curve. Every number in the scenarios traces to a specific cell in a specific other file, by design.

Disruption timings are anchored to plausible historical patterns. The Zoji La early-closure event in Scenario 2 is modelled on real anomaly events in IMD records — early-October blizzards have closed Zoji La three weeks ahead of historical median in roughly one in seven years over the last two decades. Three Stallions deadlining simultaneously at Karu in Scenario 3 is modelled on the publicly observed pattern of vehicle service intervals concentrating in tranches due to common procurement years.

---

## How the math works

The platform's modelling layer has three components — demand forecasting, route availability prediction, and resupply optimization — described in the master Bastion architecture document. Under Path C, all three are pre-computed offline by Silverpot rather than running live, and the results are embedded in `scenarios.json`. This is a design choice for the demo, not a limitation of the architecture; production Bastion runs all three live.

**Demand forecasting** computes daily expected consumption per post per SKU, using a combination of headcount, terrain class, season, and operational tempo signals. The demo uses simplified linear-burn models with explicit winter-uplift multipliers; production Bastion uses XGBoost with quantile confidence intervals (10/50/90 percentiles). The simplified linear models are sufficient to produce realistic 90-day stockout horizons at the granularity the demo presents.

**Route availability prediction** computes per-segment per-day availability probabilities. The demo uses scenario-scripted closure events; production Bastion uses gradient-boosted models trained on 10-15 year IMD weather records and BRO closure logs.

**Resupply optimization** computes feasible resupply plans against demand, supply, capacity, and route constraints. The demo presents three pre-computed options per critical-state alert, with the cost / time / risk tradeoffs that an OR-Tools mixed-integer program would produce on real data; production Bastion runs the MIP solver live with sub-five-second re-plan latency on disruption events.

Cascade chains across the three layers are explicit and auditable. Every alert in the demo traces back through the chain: stockout projection → demand assumption → route closure → alternate viability → vehicle availability → resupply plan. The lineage is in the data files, and the production UI surfaces it as a click-through panel.

---

## What real-data deployment changes

Phase 3 of the Bastion roadmap is a pilot deployment at one Brigade with real Army Service Corps, Army Ordnance Corps, EME, MES, IMD, and BRO data feeds under appropriate security controls. Several aspects of the demo become more rigorous, and a few become different in kind.

The provenance grade distinction collapses. Every post, depot, route, and SKU becomes grade-A by virtue of being a real entity in the Brigade's actual sustainment graph. Numerical figures move from illustrative central estimates to fitted values from real consumption logs and EME workshop records.

Demand forecasting moves from simplified linear-burn to fitted XGBoost with quantile confidence bands. Forecast accuracy targets at this stage: MAPE under 20% on the top-30 SKUs at the 30-day horizon, reported honestly with both training and held-out validation periods.

Route availability prediction moves from scripted scenarios to per-segment models trained on the actual IMD record for the AOI, with closure events fitted to historical patterns at each chokepoint.

Resupply optimization moves from pre-computed scenario branches to a live MIP solver with warm-start re-planning under five seconds on disruption injection.

The operator-facing surface changes least, by design. The map view, the timeline scrubber, the drill-down panels, the three-options-per-alert pattern — all of these remain the same. An operator who learned the demo at iDEX and the production system at the pilot will not encounter a different interface.

---

## What the demo deliberately doesn't claim

The demo does not claim to predict adversary action. Bastion is a sustainment platform; its scenarios cover weather, route closures, vehicle reliability, and demand surges. Adversary-action modelling belongs to Lighthouse, the ISR product, and is out of scope here.

The demo does not claim to reproduce real Army stocking levels or scales of issue. Day-zero inventory in each scenario is set to produce operationally interesting horizons — typically 27-45 days to stockout — for demonstration tension. Real War Wastage Reserve stocking and seasonal pre-positioning doctrine is not public and not modelled here.

The demo does not claim accuracy in the absolute INR figures shown in resupply-option cards. The relative cost ratios between options matter for tradeoff visualization; the absolute lakhs and crores are illustrative.

The demo does not claim to replicate the full SKU breadth that a real ASC depot manages. The thirty SKUs shown are the 80/20 of cost and operational risk; a real depot tracks thousands of line items. Production Bastion handles this scale; the demo deliberately doesn't.

The demo does not claim its specific brigade-level formation assignments are accurate. They are illustrative against publicly documented divisional Areas of Responsibility.

The demo does not present itself as a decision-replacement system. Every critical-state alert ends with three resupply options and a tradeoff summary; the operator chooses. This design property is non-negotiable and will remain so in production. Indian Army logisticians do not adopt systems that remove operator agency, nor should they.

---

## Sources and references

The following public sources informed entity selection, route topology, vehicle specifications, and consumption-rate multiplier shapes used in the demo. Anyone reviewing the methodology can audit against these directly.

Government sources include MoD Annual Reports across multiple years, MoD Demands for Grants documents on indiabudget.gov.in, CAG Performance Audits on Army logistics and supply chain management, CAG audits of Army vehicle fleet condition and high-altitude clothing/equipment, Lok Sabha Standing Committee on Defence reports including Annual Demands for Grants reviews, Lok Sabha and Rajya Sabha Question and Answer archives on defence vehicles and logistics, PIB press releases from Ministry of Defence, Border Roads Organisation publications and project pages (Beacon, Vijayak, Himank, Deepak), India Meteorological Department historical bulletins and warnings, and ISRO Bhuvan and Survey of India terrain data.

Academic and think-tank sources include PRS India defence budget analyses, MP-IDSA monographs and issue briefs, CLAWS publications, and USI Journal articles by serving and retired officers.

News and OSINT sources include The Tribune, Greater Kashmir, Kashmir Observer, Reach Ladakh Bulletin, The Hindu, Indian Express, Times of India, Hindustan Times, Damien Symon's published OSINT writeups on detresfa.com, Wikipedia formation pages for Northern Command, XIV Corps, 3 Infantry Division, and 8 Mountain Division, and the GlobalSecurity.org Indian Army order-of-battle pages.

Manufacturer and equipment sources include Ashok Leyland Defence product specifications for Stallion and Topaz, Tata Motors Defence specifications for ALS and LPTA family, Boeing CH-47F Chinook specifications as deployed by the Indian Air Force, and HAL Cheetah/Cheetal manuals.

The catalogue of these sources, with URLs and per-source provenance and licensing notes, is in `data/catalogue/sources.yaml` in the repository. The demo's data files cite provenance against these sources at the entity level via the `provenance_grade` and `provenance_note` fields.

---

*Methodology document, Wk6 lock. For questions or to audit any specific entity's provenance, refer to the per-file `provenance_grade` and `provenance_note` fields in `data/fsp/`.*
