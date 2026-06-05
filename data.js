// Project Bastion — synthetic canonical snapshot for the UI mock.
// Mirrors the real 2024-12-15 snapshot (stage3-v1.0 / stage4-v1.0 / seed=42).
// Numbers are anchored to the evaluation report + Stage 4 README findings.

window.B = (function () {
  // ─────────────────────────────────────────────── Snapshot meta
  const snapshot = {
    snapshot_id: "0dca27e9-…-2024-12-15",
    label: "canonical",
    seed: 42,
    as_of_date: "2024-12-15",
    generator_version: "stage2-v1.0",
    horizon_days: 14,
    created_at: "2026-05-16T04:39:19.276227Z",
    row_counts: {
      posts: 35,
      skus: 30,
      vehicles: 249,
      passes: 5,
      depots: 4,
      consumption_event: 2_350_274,
      stock_level: 1_148_775,
      weather_observation: 38_325,
    },
    output_row_counts: {
      demand_forecasts: 3_150,
      route_predictions: 580,
      vehicle_reliability: 249,
      stockout_risk: 4_200,
    },
  };

  // ─────────────────────────────────────────────── Model versions
  const models = [
    {
      kind: "demand_forecast",
      name: "stage3-v1.0",
      algorithm: "XGBoost quantile (54 boosters; band × head × {q10,q50,q90}); post-hoc conformal calibration",
      trained_at: "2026-05-16T04:38:22Z",
      git_sha: "13645ff",
      slices: 18,
      artifacts: 54,
      metrics: {
        weighted_mape_p50: 0.294,
        coverage_p10: 0.120,
        coverage_p90: 0.113,
        coverage_target: 0.10,
        mae_over_median_range: [0.14, 0.25],
        notes: "Weighted-avg MAPE 29.4% vs masterplan target <20%. MAE/median 0.14–0.25 across forward SKUs argues acceptable on the band the optimizer plans for.",
      },
    },
    {
      kind: "route_availability",
      name: "stage3-v1.0",
      algorithm: "XGBoost binary (20 classifiers; pass × {1d,3d,7d,14d})",
      trained_at: "2026-05-16T04:38:48Z",
      git_sha: "13645ff",
      slices: 20,
      artifacts: 20,
      metrics: {
        auc_range: [0.63, 0.83],
        brier_range: [0.06, 0.14],
        brier_baseline_range: [0.07, 0.08],
        notes: "Brier is the headline; AUC is unstable on sparse closure days. Tsaka La 1d AUC=0.39 is a rare-event collapse (6 closures in 183 days) — Brier 0.088 shows calibration is fine.",
      },
    },
    {
      kind: "vehicle_reliability",
      name: "stage3-v1.0",
      algorithm: "Rule-based analytic Weibull survival (no training); repair-cycle effective-age correction",
      trained_at: "2026-05-16T04:39:10Z",
      git_sha: "13645ff",
      slices: 1,
      artifacts: 1,
      metrics: {
        predicted_rate: 0.0116,
        observed_rate: 0.0095,
        backtest_n: 25_896,
        brier_skill: -0.004,
        notes: "Brier skill ≈ 0 by design. Rule contains no information beyond unconditional rate — Stage 2's Weibull is too clean for ML. Slot is hot-swappable when real altitude/breakdown data arrives.",
      },
    },
    {
      kind: "risk_evaluator",
      name: "stage3-v1.0",
      algorithm: "Composition (forecast P50/P90 + current stock + ∏ P(pass closed))",
      trained_at: "2026-05-16T04:39:18Z",
      git_sha: "13645ff",
      slices: 1,
      artifacts: 1,
      metrics: {
        stockout_precision_14d: 1.00,
        at_risk_recall_14d: 0.91,
        confusion_14d: { tp: 31, fp: 0, fn: 3, tn: 1015, edge_actual_stockout: 1 },
        notes: "100% precision, 91% recall at 14d, 1,050 (post,SKU) pairs. 128 alerts fired — all Tier 1 RAT-005. No spurious alerts in other tiers.",
      },
    },
    {
      kind: "optimizer",
      name: "stage4-v1.0",
      algorithm: "OR-Tools CBC MIP — coverage-lex (P90 anticipatory) + secondary {cost,time,risk,balanced}",
      trained_at: "2026-05-29T11:14:02Z",
      git_sha: "13645ff",
      slices: 4,
      artifacts: 4,
      metrics: {
        solve_time_s: 1.4,
        plan_count: 4,
        coverage_best_road_pct: 31.7,
        posts_road_isolated: 15,
        posts_at_risk: 30,
        notes: "15/30 at-risk posts are road-isolated at horizon 14d. Best achievable road coverage 31.7% — the load-bearing finding: the optimizer refuses to promise undeliverable convoys.",
      },
    },
  ];

  // ─────────────────────────────────────────────── Stock heads + SKUs
  const heads = ["Rations", "POL", "Ammunition", "Clothing", "Medical", "Engineer"];

  const skus = [
    { sku_id: "RAT-001", head: "Rations", name: "Atta / Flour", tier: 1, base_per_soldier_day: 0.60, shelf_life_days: 365 },
    { sku_id: "RAT-002", head: "Rations", name: "Rice", tier: 1, base_per_soldier_day: 0.20, shelf_life_days: 540 },
    { sku_id: "RAT-003", head: "Rations", name: "Dal / Pulses", tier: 1, base_per_soldier_day: 0.10, shelf_life_days: 540 },
    { sku_id: "RAT-004", head: "Rations", name: "Cooking Oil", tier: 1, base_per_soldier_day: 0.05, shelf_life_days: 365 },
    { sku_id: "RAT-005", head: "Rations", name: "Fresh Meat", tier: 1, base_per_soldier_day: 0.18, shelf_life_days: 14 },
    { sku_id: "RAT-006", head: "Rations", name: "Tinned Rations", tier: 2, base_per_soldier_day: 0.40, shelf_life_days: 730 },
    { sku_id: "RAT-007", head: "Rations", name: "Tea & Sugar", tier: 2, base_per_soldier_day: 0.04, shelf_life_days: 730 },
    { sku_id: "RAT-008", head: "Rations", name: "Dry Fruits", tier: 3, base_per_soldier_day: 0.03, shelf_life_days: 365 },
    { sku_id: "POL-001", head: "POL", name: "Kerosene", tier: 1, base_per_soldier_day: 0.80, shelf_life_days: 1095 },
    { sku_id: "POL-002", head: "POL", name: "Diesel (HSD)", tier: 1, base_per_soldier_day: 0.60, shelf_life_days: 365 },
    { sku_id: "POL-003", head: "POL", name: "Petrol (MS)", tier: 2, base_per_soldier_day: 0.05, shelf_life_days: 180 },
    { sku_id: "POL-004", head: "POL", name: "Lubricants", tier: 3, base_per_soldier_day: 0.02, shelf_life_days: 1095 },
    { sku_id: "AMM-001", head: "Ammunition", name: "5.56mm Ball", tier: 1, base_per_soldier_day: 0.20, shelf_life_days: 3650 },
    { sku_id: "AMM-002", head: "Ammunition", name: "7.62mm", tier: 1, base_per_soldier_day: 0.10, shelf_life_days: 3650 },
    { sku_id: "AMM-003", head: "Ammunition", name: "40mm UBGL", tier: 2, base_per_soldier_day: 0.02, shelf_life_days: 3650 },
    { sku_id: "AMM-004", head: "Ammunition", name: "81mm Mortar", tier: 2, base_per_soldier_day: 0.01, shelf_life_days: 3650 },
    { sku_id: "AMM-005", head: "Ammunition", name: "Pyro / Illum", tier: 3, base_per_soldier_day: 0.005, shelf_life_days: 1825 },
    { sku_id: "CLO-001", head: "Clothing", name: "Boots (pair)", tier: 2, base_per_soldier_day: 0.002, shelf_life_days: 1095 },
    { sku_id: "CLO-002", head: "Clothing", name: "ECC&E Jacket", tier: 1, base_per_soldier_day: 0.001, shelf_life_days: 1825 },
    { sku_id: "CLO-003", head: "Clothing", name: "Snow Goggles", tier: 3, base_per_soldier_day: 0.001, shelf_life_days: 1825 },
    { sku_id: "CLO-004", head: "Clothing", name: "Thermal Sleeping Bag", tier: 1, base_per_soldier_day: 0.0005, shelf_life_days: 1825 },
    { sku_id: "MED-001", head: "Medical", name: "Diamox", tier: 1, base_per_soldier_day: 0.05, shelf_life_days: 730 },
    { sku_id: "MED-002", head: "Medical", name: "Dexamethasone", tier: 1, base_per_soldier_day: 0.003, shelf_life_days: 730 },
    { sku_id: "MED-003", head: "Medical", name: "Oxygen Cylinder", tier: 1, base_per_soldier_day: 0.005, shelf_life_days: 1825 },
    { sku_id: "MED-004", head: "Medical", name: "Frostbite Kit", tier: 2, base_per_soldier_day: 0.001, shelf_life_days: 1095 },
    { sku_id: "MED-005", head: "Medical", name: "Antibiotics", tier: 2, base_per_soldier_day: 0.01, shelf_life_days: 1095 },
    { sku_id: "ENG-001", head: "Engineer", name: "Bukhari Stove", tier: 2, base_per_soldier_day: 0.0005, shelf_life_days: 3650 },
    { sku_id: "ENG-002", head: "Engineer", name: "Prefab Shelter Panel", tier: 3, base_per_soldier_day: 0.001, shelf_life_days: 3650 },
    { sku_id: "ENG-003", head: "Engineer", name: "Sandbags", tier: 3, base_per_soldier_day: 0.05, shelf_life_days: 1825 },
    { sku_id: "ENG-004", head: "Engineer", name: "Concertina Wire (m)", tier: 3, base_per_soldier_day: 0.02, shelf_life_days: 3650 },
  ];

  // ─────────────────────────────────────────────── Depots + Posts (35 nodes)
  const depots = [
    { depot_id: "DEP-LEH",    name: "Leh ASC Depot",     axis: "central",  coords: [77.58, 34.15], elev_m: 3524, provenance: "B" },
    { depot_id: "DEP-KARU",   name: "Karu Sub-Depot",    axis: "central",  coords: [77.74, 33.94], elev_m: 3700, provenance: "C" },
    { depot_id: "DEP-PARTAPUR", name: "Partapur Depot",  axis: "siachen",  coords: [77.32, 34.85], elev_m: 3070, provenance: "B" },
    { depot_id: "DEP-KARGIL", name: "Kargil Main Depot", axis: "western",  coords: [76.13, 34.55], elev_m: 2680, provenance: "B" },
  ];

  // 35 posts. coords loosely anchored to real Ladakh / Siachen positions.
  const posts = [
    // ---- Siachen axis (north) — extreme altitude, air-resupply dependent
    { post_id: "POST-001", name: "DBO Base",            band: "forward", axis: "DBO",         coords: [77.83, 35.34], elev_m: 5065, troops: 150, depot: "DEP-PARTAPUR", served_by: ["Khardung La","Saser La"], has_air: true,  provenance: "B" },
    { post_id: "POST-002", name: "Murgo Sub-Base",      band: "mid",     axis: "DBO",         coords: [77.67, 35.04], elev_m: 4470, troops:  80, depot: "DEP-PARTAPUR", served_by: ["Khardung La","Saser La"], has_air: false, provenance: "B" },
    { post_id: "POST-003", name: "Saser Brangsa",       band: "forward", axis: "DBO",         coords: [77.78, 35.20], elev_m: 4940, troops:  60, depot: "DEP-PARTAPUR", served_by: ["Khardung La","Saser La"], has_air: true,  provenance: "C" },
    { post_id: "POST-004", name: "Burtse",              band: "forward", axis: "DBO",         coords: [78.01, 35.18], elev_m: 4790, troops:  45, depot: "DEP-PARTAPUR", served_by: ["Khardung La","Saser La"], has_air: false, provenance: "C" },
    { post_id: "POST-005", name: "Siachen Base Camp",   band: "mid",     axis: "Siachen",     coords: [77.20, 35.10], elev_m: 3620, troops: 220, depot: "DEP-PARTAPUR", served_by: [],                          has_air: true,  provenance: "A" },
    // ---- Galwan / DSDBO corridor
    { post_id: "POST-006", name: "PP-14 Galwan",        band: "forward", axis: "DBO",         coords: [78.92, 34.79], elev_m: 4800, troops: 120, depot: "DEP-KARU",     served_by: ["Khardung La","Chang La"], has_air: false, provenance: "B" },
    { post_id: "POST-007", name: "PP-15 Hot Springs",   band: "forward", axis: "DBO",         coords: [78.55, 34.55], elev_m: 4720, troops:  90, depot: "DEP-KARU",     served_by: ["Khardung La","Chang La"], has_air: false, provenance: "B" },
    { post_id: "POST-008", name: "PP-17A Gogra",        band: "forward", axis: "DBO",         coords: [78.62, 34.42], elev_m: 4690, troops:  70, depot: "DEP-KARU",     served_by: ["Khardung La","Chang La"], has_air: false, provenance: "B" },
    // ---- Pangong-Chushul cluster
    { post_id: "POST-009", name: "Tangtse",             band: "mid",     axis: "Pangong",     coords: [78.13, 33.96], elev_m: 4080, troops: 120, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: false, provenance: "A" },
    { post_id: "POST-010", name: "Lukung",              band: "mid",     axis: "Pangong",     coords: [78.46, 34.05], elev_m: 4250, troops:  90, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: false, provenance: "B" },
    { post_id: "POST-011", name: "Finger Area N-Bank",  band: "forward", axis: "Pangong",     coords: [78.55, 33.92], elev_m: 4300, troops:  40, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: false, provenance: "B" },
    { post_id: "POST-012", name: "Chushul Garrison",    band: "mid",     axis: "Chushul",     coords: [78.65, 33.58], elev_m: 4360, troops: 250, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: true,  provenance: "A" },
    { post_id: "POST-013", name: "Rezang La OP",        band: "forward", axis: "Chushul",     coords: [78.78, 33.47], elev_m: 4750, troops:  35, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: false, provenance: "A" },
    { post_id: "POST-014", name: "Spanggur Gap",        band: "forward", axis: "Chushul",     coords: [78.80, 33.55], elev_m: 4250, troops:  50, depot: "DEP-KARU",     served_by: ["Chang La"],                has_air: false, provenance: "B" },
    { post_id: "POST-015", name: "Marsimik La OP",      band: "forward", axis: "Pangong",     coords: [78.43, 34.22], elev_m: 5582, troops:  20, depot: "DEP-KARU",     served_by: ["Chang La","Marsimik La"],  has_air: false, provenance: "B" },
    // ---- Demchok-Hanle cluster
    { post_id: "POST-016", name: "Hanle Forward Camp",  band: "mid",     axis: "Demchok",     coords: [79.00, 32.78], elev_m: 4290, troops: 100, depot: "DEP-KARU",     served_by: ["Tsaka La"],                has_air: true,  provenance: "A" },
    { post_id: "POST-017", name: "Demchok Picket",      band: "forward", axis: "Demchok",     coords: [79.45, 32.70], elev_m: 4380, troops:  50, depot: "DEP-KARU",     served_by: ["Tsaka La"],                has_air: false, provenance: "B" },
    { post_id: "POST-018", name: "Loma Sub-Base",       band: "mid",     axis: "Demchok",     coords: [79.10, 32.95], elev_m: 4150, troops:  60, depot: "DEP-KARU",     served_by: ["Tsaka La"],                has_air: false, provenance: "B" },
    { post_id: "POST-019", name: "Nyoma ALG",           band: "mid",     axis: "Demchok",     coords: [78.65, 33.20], elev_m: 4170, troops: 110, depot: "DEP-KARU",     served_by: ["Tsaka La"],                has_air: true,  provenance: "A" },
    { post_id: "POST-020", name: "Koyul",               band: "forward", axis: "Demchok",     coords: [79.25, 32.95], elev_m: 4380, troops:  30, depot: "DEP-KARU",     served_by: ["Tsaka La"],                has_air: false, provenance: "C" },
    // ---- Central Indus axis
    { post_id: "POST-021", name: "Leh Garrison",        band: "depot",   axis: "central",     coords: [77.58, 34.15], elev_m: 3524, troops: 800, depot: "DEP-LEH",      served_by: [],                          has_air: true,  provenance: "A" },
    { post_id: "POST-022", name: "Karu Garrison",       band: "depot",   axis: "central",     coords: [77.74, 33.94], elev_m: 3700, troops: 400, depot: "DEP-KARU",     served_by: [],                          has_air: false, provenance: "A" },
    { post_id: "POST-023", name: "Khardung Village",    band: "mid",     axis: "central",     coords: [77.61, 34.30], elev_m: 4040, troops:  90, depot: "DEP-LEH",      served_by: ["Khardung La"],            has_air: false, provenance: "C" },
    { post_id: "POST-024", name: "Upshi",               band: "mid",     axis: "central",     coords: [77.79, 33.85], elev_m: 3460, troops:  60, depot: "DEP-KARU",     served_by: [],                          has_air: false, provenance: "C" },
    // ---- Kargil-Drass western axis
    { post_id: "POST-025", name: "Kargil HQ",           band: "depot",   axis: "western",     coords: [76.13, 34.55], elev_m: 2680, troops: 1200,depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "A" },
    { post_id: "POST-026", name: "Drass Garrison",      band: "mid",     axis: "western",     coords: [75.75, 34.43], elev_m: 3280, troops: 300, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "A" },
    { post_id: "POST-027", name: "Mushkoh Valley OP",   band: "forward", axis: "western",     coords: [76.10, 34.55], elev_m: 4500, troops:  40, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "A" },
    { post_id: "POST-028", name: "Tiger Hill OP",       band: "forward", axis: "western",     coords: [75.90, 34.48], elev_m: 5062, troops:  40, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "A" },
    { post_id: "POST-029", name: "Tololing OP",         band: "forward", axis: "western",     coords: [75.80, 34.40], elev_m: 4590, troops:  35, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "A" },
    { post_id: "POST-030", name: "Batalik Sector",      band: "forward", axis: "western",     coords: [76.40, 34.75], elev_m: 4200, troops:  80, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "B" },
    { post_id: "POST-031", name: "Kaksar Picket",       band: "forward", axis: "western",     coords: [76.10, 34.60], elev_m: 3800, troops:  45, depot: "DEP-KARGIL",   served_by: ["Zoji La"],                 has_air: false, provenance: "B" },
    // ---- Extreme high-altitude OPs (Saser muztagh, Karakoram saddle)
    { post_id: "POST-032", name: "Indira Col OP",       band: "forward", axis: "Siachen",     coords: [77.06, 35.65], elev_m: 5640, troops:  25, depot: "DEP-PARTAPUR", served_by: [],                          has_air: true,  provenance: "B" },
    { post_id: "POST-033", name: "Bana Post",           band: "forward", axis: "Siachen",     coords: [77.15, 35.40], elev_m: 6450, troops:  18, depot: "DEP-PARTAPUR", served_by: [],                          has_air: true,  provenance: "A" },
    { post_id: "POST-034", name: "Sonam Post",          band: "forward", axis: "Siachen",     coords: [77.10, 35.30], elev_m: 5900, troops:  20, depot: "DEP-PARTAPUR", served_by: [],                          has_air: true,  provenance: "B" },
    { post_id: "POST-035", name: "Kumar Post",          band: "forward", axis: "Siachen",     coords: [77.08, 35.20], elev_m: 5450, troops:  22, depot: "DEP-PARTAPUR", served_by: [],                          has_air: true,  provenance: "B" },
  ];

  // ─────────────────────────────────────────────── Passes (route closure unit)
  // Probabilities from Stage 4 README findings at 2024-12-15.
  const passes = [
    { pass_name: "Zoji La",      coords: [75.50, 34.30], elev_m: 3528, axis: "western",  p_open: 0.29, p_closed: 0.71, status: "warn" },
    { pass_name: "Chang La",     coords: [77.90, 34.05], elev_m: 5360, axis: "central",  p_open: 0.21, p_closed: 0.79, status: "warn" },
    { pass_name: "Khardung La",  coords: [77.60, 34.28], elev_m: 5359, axis: "central",  p_open: 0.65, p_closed: 0.35, status: "ok" },
    { pass_name: "Marsimik La",  coords: [78.43, 34.22], elev_m: 5582, axis: "Pangong",  p_open: 0.15, p_closed: 0.85, status: "crit" },
    { pass_name: "Tsaka La",     coords: [78.95, 32.80], elev_m: 4910, axis: "Demchok",  p_open: 0.44, p_closed: 0.56, status: "warn" },
  ];

  // ─────────────────────────────────────────────── Routes (post → depot edges)
  // Drawn on the map; real `routes.parquet` has 60+ rows. Curated sample.
  const routes = [
    // Western axis (Zoji La gate)
    { route_id: "RT-LEH-KARGIL",        from: "DEP-LEH",      to: "POST-025", via: ["Khardung La"], distance_km: 218, status: "warn" },
    { route_id: "RT-KARGIL-DRASS",      from: "DEP-KARGIL",   to: "POST-026", via: ["Zoji La"],     distance_km:  55, status: "warn" },
    { route_id: "RT-KARGIL-MUSHKOH",    from: "DEP-KARGIL",   to: "POST-027", via: ["Zoji La"],     distance_km:  70, status: "warn" },
    { route_id: "RT-KARGIL-TOLOLING",   from: "DEP-KARGIL",   to: "POST-029", via: ["Zoji La"],     distance_km:  62, status: "warn" },
    { route_id: "RT-KARGIL-TIGER",      from: "DEP-KARGIL",   to: "POST-028", via: ["Zoji La"],     distance_km:  68, status: "crit" },
    { route_id: "RT-KARGIL-BATALIK",    from: "DEP-KARGIL",   to: "POST-030", via: ["Zoji La"],     distance_km:  64, status: "warn" },
    // Central axis
    { route_id: "RT-LEH-KARU",          from: "DEP-LEH",      to: "DEP-KARU", via: [],              distance_km:  36, status: "ok" },
    { route_id: "RT-LEH-KHARDUNG",      from: "DEP-LEH",      to: "POST-023", via: ["Khardung La"], distance_km:  40, status: "ok" },
    // DSDBO corridor (Khardung La + Saser La)
    { route_id: "RT-PARTAPUR-DBO",      from: "DEP-PARTAPUR", to: "POST-001", via: ["Khardung La","Saser La"], distance_km: 220, status: "crit" },
    { route_id: "RT-PARTAPUR-MURGO",    from: "DEP-PARTAPUR", to: "POST-002", via: ["Khardung La"], distance_km: 105, status: "warn" },
    { route_id: "RT-PARTAPUR-SASER",    from: "DEP-PARTAPUR", to: "POST-003", via: ["Khardung La","Saser La"], distance_km: 175, status: "crit" },
    { route_id: "RT-PARTAPUR-BURTSE",   from: "DEP-PARTAPUR", to: "POST-004", via: ["Khardung La","Saser La"], distance_km: 195, status: "crit" },
    // Pangong-Chushul (Chang La gate)
    { route_id: "RT-KARU-TANGTSE",      from: "DEP-KARU",     to: "POST-009", via: ["Chang La"],    distance_km:  82, status: "warn" },
    { route_id: "RT-KARU-LUKUNG",       from: "DEP-KARU",     to: "POST-010", via: ["Chang La"],    distance_km: 124, status: "warn" },
    { route_id: "RT-KARU-FINGER",       from: "DEP-KARU",     to: "POST-011", via: ["Chang La"],    distance_km: 152, status: "warn" },
    { route_id: "RT-KARU-CHUSHUL",      from: "DEP-KARU",     to: "POST-012", via: ["Chang La"],    distance_km: 162, status: "warn" },
    { route_id: "RT-KARU-REZANG",       from: "DEP-KARU",     to: "POST-013", via: ["Chang La"],    distance_km: 174, status: "crit" },
    { route_id: "RT-KARU-SPANGGUR",     from: "DEP-KARU",     to: "POST-014", via: ["Chang La"],    distance_km: 172, status: "warn" },
    { route_id: "RT-KARU-MARSIMIK",     from: "DEP-KARU",     to: "POST-015", via: ["Chang La","Marsimik La"], distance_km: 160, status: "crit" },
    // Galwan / Hot Springs (Chang La gate)
    { route_id: "RT-KARU-GALWAN",       from: "DEP-KARU",     to: "POST-006", via: ["Chang La"],    distance_km: 240, status: "crit" },
    { route_id: "RT-KARU-HOTSPRINGS",   from: "DEP-KARU",     to: "POST-007", via: ["Chang La"],    distance_km: 184, status: "warn" },
    { route_id: "RT-KARU-GOGRA",        from: "DEP-KARU",     to: "POST-008", via: ["Chang La"],    distance_km: 196, status: "warn" },
    // Demchok-Hanle (Tsaka La gate)
    { route_id: "RT-KARU-HANLE",        from: "DEP-KARU",     to: "POST-016", via: ["Tsaka La"],    distance_km: 195, status: "warn" },
    { route_id: "RT-KARU-DEMCHOK",      from: "DEP-KARU",     to: "POST-017", via: ["Tsaka La"],    distance_km: 245, status: "warn" },
    { route_id: "RT-KARU-LOMA",         from: "DEP-KARU",     to: "POST-018", via: ["Tsaka La"],    distance_km: 220, status: "warn" },
    { route_id: "RT-KARU-NYOMA",        from: "DEP-KARU",     to: "POST-019", via: ["Tsaka La"],    distance_km: 175, status: "warn" },
    { route_id: "RT-KARU-KOYUL",        from: "DEP-KARU",     to: "POST-020", via: ["Tsaka La"],    distance_km: 230, status: "warn" },
  ];

  // ─────────────────────────────────────────────── Hydro / decorative
  const hydro = [
    { name: "Pangong Tso", points: [[78.30,33.78],[78.50,33.79],[78.75,33.75],[79.10,33.72],[79.30,33.70],[79.10,33.74],[78.75,33.77],[78.50,33.80],[78.30,33.80]] },
    { name: "Tso Moriri", points: [[78.30,32.92],[78.36,32.85],[78.34,32.75],[78.28,32.78],[78.26,32.88]] },
  ];
  const lac = [[78.30,35.40],[78.80,34.90],[79.20,34.20],[79.30,33.60],[79.40,32.90],[79.45,32.70],[79.20,32.50]];

  // ─────────────────────────────────────────────── Route predictions (sample)
  const route_predictions = [
    // pass × {1d,3d,7d,14d} at snapshot 2024-12-15
    { pass_name: "Zoji La",     date: "2024-12-16", horizon: 1,  p_open: 0.32, p_closed: 0.68 },
    { pass_name: "Zoji La",     date: "2024-12-18", horizon: 3,  p_open: 0.28, p_closed: 0.72 },
    { pass_name: "Zoji La",     date: "2024-12-22", horizon: 7,  p_open: 0.25, p_closed: 0.75 },
    { pass_name: "Zoji La",     date: "2024-12-29", horizon: 14, p_open: 0.29, p_closed: 0.71 },
    { pass_name: "Chang La",    date: "2024-12-16", horizon: 1,  p_open: 0.24, p_closed: 0.76 },
    { pass_name: "Chang La",    date: "2024-12-18", horizon: 3,  p_open: 0.22, p_closed: 0.78 },
    { pass_name: "Chang La",    date: "2024-12-22", horizon: 7,  p_open: 0.20, p_closed: 0.80 },
    { pass_name: "Chang La",    date: "2024-12-29", horizon: 14, p_open: 0.21, p_closed: 0.79 },
    { pass_name: "Khardung La", date: "2024-12-16", horizon: 1,  p_open: 0.72, p_closed: 0.28 },
    { pass_name: "Khardung La", date: "2024-12-18", horizon: 3,  p_open: 0.68, p_closed: 0.32 },
    { pass_name: "Khardung La", date: "2024-12-22", horizon: 7,  p_open: 0.65, p_closed: 0.35 },
    { pass_name: "Khardung La", date: "2024-12-29", horizon: 14, p_open: 0.61, p_closed: 0.39 },
    { pass_name: "Marsimik La", date: "2024-12-16", horizon: 1,  p_open: 0.18, p_closed: 0.82 },
    { pass_name: "Marsimik La", date: "2024-12-18", horizon: 3,  p_open: 0.16, p_closed: 0.84 },
    { pass_name: "Marsimik La", date: "2024-12-22", horizon: 7,  p_open: 0.14, p_closed: 0.86 },
    { pass_name: "Marsimik La", date: "2024-12-29", horizon: 14, p_open: 0.15, p_closed: 0.85 },
    { pass_name: "Tsaka La",    date: "2024-12-16", horizon: 1,  p_open: 0.48, p_closed: 0.52 },
    { pass_name: "Tsaka La",    date: "2024-12-18", horizon: 3,  p_open: 0.46, p_closed: 0.54 },
    { pass_name: "Tsaka La",    date: "2024-12-22", horizon: 7,  p_open: 0.42, p_closed: 0.58 },
    { pass_name: "Tsaka La",    date: "2024-12-29", horizon: 14, p_open: 0.44, p_closed: 0.56 },
  ];

  // ─────────────────────────────────────────────── Stockout risk (sample of 4,200 rows)
  // Only showing the rows that fired tier alerts (128 in real data; we render 16 representative ones)
  // plus a handful of context rows.
  // status thresholds: stockout (closing_stock<=0), rationing (dts<7), ok (else).
  const stockout_risk = [
    // FIRED — Tier 1 RAT-005 (Fresh Meat, 14-day shelf life). 128 in real snapshot; sample below.
    { risk_id: "R-001", post_id: "POST-001", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:  140, current_days_of_cover:  5.2,  p10: 25, p50: 27, p90: 32, projected_consumption_p50:  54, projected_consumption_p90:  64, projected_closing_stock_p50:  86, projected_closing_stock_p90:  76, projected_days_of_cover_p50:  3.6, projected_days_of_cover_p90:  3.0, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.962, tier_alert_fired: true },
    { risk_id: "R-002", post_id: "POST-003", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   54, current_days_of_cover:  4.5,  p10: 11, p50: 12, p90: 14, projected_consumption_p50:  24, projected_consumption_p90:  28, projected_closing_stock_p50:  30, projected_closing_stock_p90:  26, projected_days_of_cover_p50:  2.5, projected_days_of_cover_p90:  2.2, predicted_status: "rationing", predicted_status_worstcase: "stockout",  isolation_probability: 0.962, tier_alert_fired: true },
    { risk_id: "R-003", post_id: "POST-004", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   38, current_days_of_cover:  4.7,  p10:  8, p50:  9, p90: 11, projected_consumption_p50:  18, projected_consumption_p90:  22, projected_closing_stock_p50:  20, projected_closing_stock_p90:  16, projected_days_of_cover_p50:  2.5, projected_days_of_cover_p90:  2.0, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.962, tier_alert_fired: true },
    { risk_id: "R-004", post_id: "POST-006", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:  108, current_days_of_cover:  5.0,  p10: 19, p50: 22, p90: 26, projected_consumption_p50:  44, projected_consumption_p90:  52, projected_closing_stock_p50:  64, projected_closing_stock_p90:  56, projected_days_of_cover_p50:  2.9, projected_days_of_cover_p90:  2.5, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.834, tier_alert_fired: true },
    { risk_id: "R-005", post_id: "POST-008", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   62, current_days_of_cover:  4.9,  p10: 11, p50: 13, p90: 15, projected_consumption_p50:  26, projected_consumption_p90:  30, projected_closing_stock_p50:  36, projected_closing_stock_p90:  32, projected_days_of_cover_p50:  2.7, projected_days_of_cover_p90:  2.4, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.834, tier_alert_fired: true },
    { risk_id: "R-006", post_id: "POST-011", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   34, current_days_of_cover:  4.5,  p10:  7, p50:  8, p90:  9, projected_consumption_p50:  16, projected_consumption_p90:  18, projected_closing_stock_p50:  18, projected_closing_stock_p90:  16, projected_days_of_cover_p50:  2.4, projected_days_of_cover_p90:  2.1, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.834, tier_alert_fired: true },
    { risk_id: "R-007", post_id: "POST-013", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   32, current_days_of_cover:  5.1,  p10:  6, p50:  7, p90:  8, projected_consumption_p50:  14, projected_consumption_p90:  16, projected_closing_stock_p50:  18, projected_closing_stock_p90:  16, projected_days_of_cover_p50:  2.7, projected_days_of_cover_p90:  2.3, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.834, tier_alert_fired: true },
    { risk_id: "R-008", post_id: "POST-015", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   18, current_days_of_cover:  4.2,  p10:  4, p50:  4, p90:  5, projected_consumption_p50:   9, projected_consumption_p90:  10, projected_closing_stock_p50:   9, projected_closing_stock_p90:   8, projected_days_of_cover_p50:  2.1, projected_days_of_cover_p90:  1.9, predicted_status: "stockout",  predicted_status_worstcase: "stockout",  isolation_probability: 0.963, tier_alert_fired: true },
    { risk_id: "R-009", post_id: "POST-027", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   34, current_days_of_cover:  4.7,  p10:  7, p50:  8, p90:  9, projected_consumption_p50:  16, projected_consumption_p90:  18, projected_closing_stock_p50:  18, projected_closing_stock_p90:  16, projected_days_of_cover_p50:  2.7, projected_days_of_cover_p90:  2.3, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.710, tier_alert_fired: true },
    { risk_id: "R-010", post_id: "POST-028", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   30, current_days_of_cover:  4.3,  p10:  6, p50:  7, p90:  8, projected_consumption_p50:  14, projected_consumption_p90:  16, projected_closing_stock_p50:  16, projected_closing_stock_p90:  14, projected_days_of_cover_p50:  2.3, projected_days_of_cover_p90:  2.0, predicted_status: "rationing", predicted_status_worstcase: "stockout",  isolation_probability: 0.710, tier_alert_fired: true },
    { risk_id: "R-011", post_id: "POST-029", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   28, current_days_of_cover:  4.4,  p10:  6, p50:  7, p90:  8, projected_consumption_p50:  14, projected_consumption_p90:  16, projected_closing_stock_p50:  14, projected_closing_stock_p90:  12, projected_days_of_cover_p50:  2.2, projected_days_of_cover_p90:  1.9, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.710, tier_alert_fired: true },
    { risk_id: "R-012", post_id: "POST-032", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   22, current_days_of_cover:  4.9,  p10:  4, p50:  5, p90:  6, projected_consumption_p50:  10, projected_consumption_p90:  12, projected_closing_stock_p50:  12, projected_closing_stock_p90:  10, projected_days_of_cover_p50:  2.6, projected_days_of_cover_p90:  2.2, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 1.000, tier_alert_fired: true },
    { risk_id: "R-013", post_id: "POST-033", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   14, current_days_of_cover:  4.3,  p10:  3, p50:  3, p90:  4, projected_consumption_p50:   7, projected_consumption_p90:   8, projected_closing_stock_p50:   7, projected_closing_stock_p90:   6, projected_days_of_cover_p50:  2.2, projected_days_of_cover_p90:  1.8, predicted_status: "rationing", predicted_status_worstcase: "stockout",  isolation_probability: 1.000, tier_alert_fired: true },
    { risk_id: "R-014", post_id: "POST-034", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   16, current_days_of_cover:  4.4,  p10:  3, p50:  4, p90:  4, projected_consumption_p50:   8, projected_consumption_p90:   8, projected_closing_stock_p50:   8, projected_closing_stock_p90:   8, projected_days_of_cover_p50:  2.2, projected_days_of_cover_p90:  2.2, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 1.000, tier_alert_fired: true },
    { risk_id: "R-015", post_id: "POST-035", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   18, current_days_of_cover:  4.5,  p10:  4, p50:  4, p90:  5, projected_consumption_p50:   8, projected_consumption_p90:  10, projected_closing_stock_p50:  10, projected_closing_stock_p90:   8, projected_days_of_cover_p50:  2.5, projected_days_of_cover_p90:  2.0, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 1.000, tier_alert_fired: true },
    { risk_id: "R-016", post_id: "POST-014", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:   46, current_days_of_cover:  4.6,  p10: 10, p50: 11, p90: 12, projected_consumption_p50:  22, projected_consumption_p90:  24, projected_closing_stock_p50:  24, projected_closing_stock_p90:  22, projected_days_of_cover_p50:  2.4, projected_days_of_cover_p90:  2.2, predicted_status: "rationing", predicted_status_worstcase: "rationing", isolation_probability: 0.834, tier_alert_fired: true },
    // Context rows — not firing
    { risk_id: "R-017", post_id: "POST-001", sku: "POL-001", head: "POL",     tier: 1, horizon_days: 14, current_stock: 12400, current_days_of_cover: 28.0, p10: 90, p50: 110, p90: 135, projected_consumption_p50: 220, projected_consumption_p90: 270, projected_closing_stock_p50: 12180, projected_closing_stock_p90: 12130, projected_days_of_cover_p50: 27.5, projected_days_of_cover_p90: 22.5, predicted_status: "ok", predicted_status_worstcase: "ok", isolation_probability: 0.962, tier_alert_fired: false },
    { risk_id: "R-018", post_id: "POST-021", sku: "RAT-005", head: "Rations", tier: 1, horizon_days: 14, current_stock:  2400, current_days_of_cover: 16.7, p10: 130, p50: 144, p90: 158, projected_consumption_p50: 288, projected_consumption_p90: 316, projected_closing_stock_p50: 2112, projected_closing_stock_p90: 2084, projected_days_of_cover_p50: 14.7, projected_days_of_cover_p90: 13.2, predicted_status: "ok", predicted_status_worstcase: "ok", isolation_probability: 0.000, tier_alert_fired: false },
  ];

  // ─────────────────────────────────────────────── Vehicles (sample of 249)
  const vehicles = [
    { vehicle_id: "VH-LEH-014", class_id: "Stallion-6x6",   payload_tons: 7.5, home_depot_id: "DEP-LEH",      effective_age_days: 1840, events_to_date: 0, p_deadline: 0.182, reliability_score: 0.818, status: "available" },
    { vehicle_id: "VH-KAR-029", class_id: "BharatBenz-HD",  payload_tons:12.0, home_depot_id: "DEP-KARGIL",   effective_age_days: 2120, events_to_date: 2, p_deadline: 0.156, reliability_score: 0.844, status: "available" },
    { vehicle_id: "VH-LEH-022", class_id: "Stallion-4x4",   payload_tons: 5.0, home_depot_id: "DEP-LEH",      effective_age_days: 1980, events_to_date: 1, p_deadline: 0.094, reliability_score: 0.906, status: "available" },
    { vehicle_id: "VH-PRT-007", class_id: "Stallion-6x6",   payload_tons: 7.5, home_depot_id: "DEP-PARTAPUR", effective_age_days: 1560, events_to_date: 1, p_deadline: 0.068, reliability_score: 0.932, status: "available" },
    { vehicle_id: "VH-KAR-041", class_id: "Tata-LPTA",      payload_tons: 2.5, home_depot_id: "DEP-KARU",     effective_age_days: 2240, events_to_date: 0, p_deadline: 0.062, reliability_score: 0.938, status: "available" },
    { vehicle_id: "VH-LEH-051", class_id: "Tata-LPTA",      payload_tons: 2.5, home_depot_id: "DEP-LEH",      effective_age_days: 1640, events_to_date: 0, p_deadline: 0.058, reliability_score: 0.942, status: "available" },
    { vehicle_id: "VH-KAR-016", class_id: "Stallion-4x4",   payload_tons: 5.0, home_depot_id: "DEP-KARGIL",   effective_age_days:  920, events_to_date: 0, p_deadline: 0.024, reliability_score: 0.976, status: "available" },
    { vehicle_id: "VH-KAR-002", class_id: "BharatBenz-HD",  payload_tons:12.0, home_depot_id: "DEP-KARU",     effective_age_days:  640, events_to_date: 0, p_deadline: 0.014, reliability_score: 0.986, status: "available" },
    { vehicle_id: "VH-PRT-018", class_id: "Stallion-4x4",   payload_tons: 5.0, home_depot_id: "DEP-PARTAPUR", effective_age_days:  480, events_to_date: 0, p_deadline: 0.009, reliability_score: 0.991, status: "available" },
    { vehicle_id: "VH-LEH-003", class_id: "BharatBenz-HD",  payload_tons:12.0, home_depot_id: "DEP-LEH",      effective_age_days:  380, events_to_date: 0, p_deadline: 0.007, reliability_score: 0.993, status: "available" },
  ];
  const vehicle_summary = {
    total: 249,
    by_class: { "Tata-LPTA": 72, "Stallion-4x4": 96, "Stallion-6x6": 54, "BharatBenz-HD": 27 },
    by_depot: { "DEP-LEH": 81, "DEP-KARU": 73, "DEP-PARTAPUR": 48, "DEP-KARGIL": 47 },
    alert_count: 6,
    mean_p_deadline: 0.0116,
  };

  // ─────────────────────────────────────────────── Alerts
  const alerts = [
    // CRITICAL — stockout_risk worstcase (sample of 32, all RAT-005 at forward posts behind closed passes)
    { alert_id: "A-001", alert_type: "stockout_risk",    severity: "critical", message: "POST-015 / Rations (RAT-005 Fresh Meat): 4d cover now, worst-case status 'stockout' within 14d tier window (h=14d)", post_id: "POST-015", sku_id: "RAT-005", source_risk_id: "R-008",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.1,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-002", alert_type: "stockout_risk",    severity: "critical", message: "POST-033 / Rations (RAT-005 Fresh Meat): 4d cover now, worst-case status 'stockout' within 14d tier window (h=14d)", post_id: "POST-033", sku_id: "RAT-005", source_risk_id: "R-013",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.2,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-003", alert_type: "stockout_risk",    severity: "critical", message: "POST-003 / Rations (RAT-005 Fresh Meat): 4d cover now, worst-case status 'stockout' within 14d tier window (h=14d)", post_id: "POST-003", sku_id: "RAT-005", source_risk_id: "R-002",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.5,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-004", alert_type: "stockout_risk",    severity: "critical", message: "POST-028 / Rations (RAT-005 Fresh Meat): 4d cover now, worst-case status 'stockout' within 14d tier window (h=14d)", post_id: "POST-028", sku_id: "RAT-005", source_risk_id: "R-010",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.3,  created_at: "2026-05-29 11:14:02" },
    // WARNING — stockout_risk rationing
    { alert_id: "A-005", alert_type: "stockout_risk",    severity: "warning",  message: "POST-001 / Rations (RAT-005 Fresh Meat): 5d cover now, worst-case status 'rationing' within 14d tier window (h=14d)", post_id: "POST-001", sku_id: "RAT-005", source_risk_id: "R-001",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 3.6,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-006", alert_type: "stockout_risk",    severity: "warning",  message: "POST-006 / Rations (RAT-005 Fresh Meat): 5d cover now, worst-case status 'rationing' within 14d tier window (h=14d)", post_id: "POST-006", sku_id: "RAT-005", source_risk_id: "R-004",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.9,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-007", alert_type: "stockout_risk",    severity: "warning",  message: "POST-013 / Rations (RAT-005 Fresh Meat): 5d cover now, worst-case status 'rationing' within 14d tier window (h=14d)", post_id: "POST-013", sku_id: "RAT-005", source_risk_id: "R-007",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.7,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-008", alert_type: "stockout_risk",    severity: "warning",  message: "POST-027 / Rations (RAT-005 Fresh Meat): 5d cover now, worst-case status 'rationing' within 14d tier window (h=14d)", post_id: "POST-027", sku_id: "RAT-005", source_risk_id: "R-009",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.7,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-009", alert_type: "stockout_risk",    severity: "warning",  message: "POST-011 / Rations (RAT-005 Fresh Meat): 5d cover now, worst-case status 'rationing' within 14d tier window (h=14d)", post_id: "POST-011", sku_id: "RAT-005", source_risk_id: "R-006",  trigger_metric: "projected_days_of_cover_p50", trigger_value: 2.4,  created_at: "2026-05-29 11:14:02" },
    // CRITICAL — disruption alerts (P(closed) > 0.85)
    { alert_id: "A-101", alert_type: "disruption",       severity: "critical", message: "Marsimik La: P(closed) 86% by 2024-12-22 (h=7d) — posts beyond this pass risk isolation", pass_name: "Marsimik La", source_route_prediction_id: "RP-015", trigger_metric: "p_closed", trigger_value: 0.86,  created_at: "2026-05-29 11:14:02" },
    // WARNING — disruption alerts (P(closed) > 0.60)
    { alert_id: "A-102", alert_type: "disruption",       severity: "warning",  message: "Chang La: P(closed) 80% by 2024-12-22 (h=7d) — posts beyond this pass risk isolation",     pass_name: "Chang La",    source_route_prediction_id: "RP-007", trigger_metric: "p_closed", trigger_value: 0.80,  created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-103", alert_type: "disruption",       severity: "warning",  message: "Zoji La: P(closed) 75% by 2024-12-22 (h=7d) — posts beyond this pass risk isolation",      pass_name: "Zoji La",     source_route_prediction_id: "RP-003", trigger_metric: "p_closed", trigger_value: 0.75,  created_at: "2026-05-29 11:14:02" },
    // WARNING — vehicle deadline alerts (P(deadline) > 0.05)
    { alert_id: "A-201", alert_type: "vehicle_deadline", severity: "critical", message: "VH-LEH-014 (Stallion-6x6 @ DEP-LEH): P(deadline) 18.2% within 7d — exclude from forward tasking / pre-empt maintenance", vehicle_id: "VH-LEH-014", trigger_metric: "p_deadline", trigger_value: 0.182, created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-202", alert_type: "vehicle_deadline", severity: "critical", message: "VH-KAR-029 (BharatBenz-HD @ DEP-KARGIL): P(deadline) 15.6% within 7d — exclude from forward tasking / pre-empt maintenance", vehicle_id: "VH-KAR-029", trigger_metric: "p_deadline", trigger_value: 0.156, created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-203", alert_type: "vehicle_deadline", severity: "warning",  message: "VH-LEH-022 (Stallion-4x4 @ DEP-LEH): P(deadline) 9.4% within 7d — exclude from forward tasking / pre-empt maintenance",  vehicle_id: "VH-LEH-022", trigger_metric: "p_deadline", trigger_value: 0.094, created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-204", alert_type: "vehicle_deadline", severity: "warning",  message: "VH-PRT-007 (Stallion-6x6 @ DEP-PARTAPUR): P(deadline) 6.8% within 7d — exclude from forward tasking / pre-empt maintenance", vehicle_id: "VH-PRT-007", trigger_metric: "p_deadline", trigger_value: 0.068, created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-205", alert_type: "vehicle_deadline", severity: "warning",  message: "VH-KAR-041 (Tata-LPTA @ DEP-KARU): P(deadline) 6.2% within 7d — exclude from forward tasking / pre-empt maintenance",      vehicle_id: "VH-KAR-041", trigger_metric: "p_deadline", trigger_value: 0.062, created_at: "2026-05-29 11:14:02" },
    { alert_id: "A-206", alert_type: "vehicle_deadline", severity: "warning",  message: "VH-LEH-051 (Tata-LPTA @ DEP-LEH): P(deadline) 5.8% within 7d — exclude from forward tasking / pre-empt maintenance",       vehicle_id: "VH-LEH-051", trigger_metric: "p_deadline", trigger_value: 0.058, created_at: "2026-05-29 11:14:02" },
  ];

  // Aggregated alert counts (real snapshot: 128 stockout + ~3 disruption + ~6 vehicle)
  const alert_totals = {
    stockout_risk:    { critical:  32, warning:  96, info:   0, total: 128 },
    disruption:       { critical:   1, warning:   2, info:   0, total:   3 },
    vehicle_deadline: { critical:   2, warning:   4, info:   0, total:   6 },
    total: 137,
    acknowledged: 0,
  };

  // ─────────────────────────────────────────────── Resupply plans (Stage 4)
  const plans = [
    {
      plan_id: "PL-COST-2024-12-15",
      objective: "min_cost",
      total_cost: 53_640,        // ₹
      total_time_hours: 162.4,
      aggregate_risk: 0.989,     // P(>=1 leg fails)
      expected_disrupted_legs: 4.2,
      coverage_pct: 31.7,        // covered priority-kg / total priority-kg
      vehicles_tasked: 9,
      legs_planned: 9,
      depots_used: ["DEP-LEH","DEP-KARU"],
      vehicle_mix: { "Tata-LPTA": 4, "Stallion-4x4": 5, "Stallion-6x6": 0, "BharatBenz-HD": 0 },
      isolated_posts_remaining: 15,
      delivered_t: 31.4,
      shortfall_t: 67.8,
    },
    {
      plan_id: "PL-TIME-2024-12-15",
      objective: "min_time",
      total_cost: 58_910,
      total_time_hours: 138.8,
      aggregate_risk: 0.991,
      expected_disrupted_legs: 4.4,
      coverage_pct: 31.7,
      vehicles_tasked: 8,
      legs_planned: 8,
      depots_used: ["DEP-LEH","DEP-KARU"],
      vehicle_mix: { "Tata-LPTA": 1, "Stallion-4x4": 5, "Stallion-6x6": 2, "BharatBenz-HD": 0 },
      isolated_posts_remaining: 15,
      delivered_t: 31.4,
      shortfall_t: 67.8,
    },
    {
      plan_id: "PL-RISK-2024-12-15",
      objective: "min_risk",
      total_cost: 62_340,
      total_time_hours: 154.2,
      aggregate_risk: 0.978,
      expected_disrupted_legs: 3.6,
      coverage_pct: 31.7,
      vehicles_tasked: 7,
      legs_planned: 7,
      depots_used: ["DEP-LEH","DEP-KARU"],
      vehicle_mix: { "Tata-LPTA": 0, "Stallion-4x4": 3, "Stallion-6x6": 3, "BharatBenz-HD": 1 },
      isolated_posts_remaining: 15,
      delivered_t: 31.4,
      shortfall_t: 67.8,
    },
    {
      plan_id: "PL-BAL-2024-12-15",
      objective: "balanced",
      total_cost: 56_780,
      total_time_hours: 148.6,
      aggregate_risk: 0.984,
      expected_disrupted_legs: 3.9,
      coverage_pct: 31.7,
      vehicles_tasked: 8,
      legs_planned: 8,
      depots_used: ["DEP-LEH","DEP-KARU"],
      vehicle_mix: { "Tata-LPTA": 2, "Stallion-4x4": 4, "Stallion-6x6": 2, "BharatBenz-HD": 0 },
      isolated_posts_remaining: 15,
      delivered_t: 31.4,
      shortfall_t: 67.8,
    },
  ];

  // Sample legs for the selected plan (the comparison table). 9 for min_cost.
  const plan_legs = {
    "PL-COST-2024-12-15": [
      { seq: 1, vehicle_id: "VH-LEH-051", vehicle_class: "Tata-LPTA",    route_id: "RT-LEH-KHARDUNG",   from: "DEP-LEH",    to: "POST-023", sku_id: "RAT-005", qty: 220,  depart_date: "2024-12-16", expected_cost:  5800, expected_risk: 0.35, path_open: 0.65 },
      { seq: 2, vehicle_id: "VH-LEH-022", vehicle_class: "Stallion-4x4", route_id: "RT-LEH-KHARDUNG",   from: "DEP-LEH",    to: "POST-023", sku_id: "POL-001", qty: 1800, depart_date: "2024-12-16", expected_cost:  6900, expected_risk: 0.35, path_open: 0.65 },
      { seq: 3, vehicle_id: "VH-KAR-002", vehicle_class: "BharatBenz-HD",route_id: "RT-LEH-KARU",       from: "DEP-LEH",    to: "POST-022", sku_id: "RAT-001", qty: 4200, depart_date: "2024-12-16", expected_cost:  5400, expected_risk: 0.04, path_open: 0.96 },
      { seq: 4, vehicle_id: "VH-KAR-016", vehicle_class: "Stallion-4x4", route_id: "RT-KARU-TANGTSE",   from: "DEP-KARU",   to: "POST-009", sku_id: "RAT-005", qty: 280,  depart_date: "2024-12-16", expected_cost:  7100, expected_risk: 0.79, path_open: 0.21 },
      { seq: 5, vehicle_id: "VH-KAR-029", vehicle_class: "BharatBenz-HD",route_id: "RT-KARU-TANGTSE",   from: "DEP-KARU",   to: "POST-009", sku_id: "POL-001", qty: 2400, depart_date: "2024-12-16", expected_cost:  8400, expected_risk: 0.79, path_open: 0.21 },
      { seq: 6, vehicle_id: "VH-KAR-041", vehicle_class: "Tata-LPTA",    route_id: "RT-KARU-LUKUNG",    from: "DEP-KARU",   to: "POST-010", sku_id: "RAT-005", qty: 200,  depart_date: "2024-12-17", expected_cost:  5800, expected_risk: 0.79, path_open: 0.21 },
      { seq: 7, vehicle_id: "VH-PRT-007", vehicle_class: "Stallion-6x6", route_id: "RT-PARTAPUR-MURGO", from: "DEP-PARTAPUR",to:"POST-002", sku_id: "RAT-001", qty: 1600, depart_date: "2024-12-16", expected_cost:  4200, expected_risk: 0.35, path_open: 0.65 },
      { seq: 8, vehicle_id: "VH-PRT-018", vehicle_class: "Stallion-4x4", route_id: "RT-PARTAPUR-MURGO", from: "DEP-PARTAPUR",to:"POST-002", sku_id: "RAT-005", qty: 180,  depart_date: "2024-12-16", expected_cost:  3650, expected_risk: 0.35, path_open: 0.65 },
      { seq: 9, vehicle_id: "VH-LEH-014", vehicle_class: "Stallion-6x6", route_id: "RT-LEH-KARU",       from: "DEP-LEH",    to: "POST-022", sku_id: "POL-001", qty: 2600, depart_date: "2024-12-16", expected_cost:  6390, expected_risk: 0.04, path_open: 0.96 },
    ],
  };

  // ─────────────────────────────────────────────── Other snapshots (history)
  const snapshots = [
    { as_of_date: "2024-12-15", label: "canonical",  seed: 42, status: "current", alerts: 137, plans: 4, coverage_pct: 31.7, created_at: "2026-05-16T04:39:19Z" },
    { as_of_date: "2024-11-01", label: "mid-winter", seed: 42, status: "archived", alerts:  84, plans: 4, coverage_pct: 58.2, created_at: "2026-05-12T08:42:11Z" },
    { as_of_date: "2024-10-15", label: "shoulder",   seed: 42, status: "archived", alerts:  41, plans: 4, coverage_pct: 86.1, created_at: "2026-05-10T15:08:42Z" },
    { as_of_date: "2024-09-01", label: "summer",     seed: 42, status: "archived", alerts:  12, plans: 4, coverage_pct: 99.4, created_at: "2026-05-08T22:11:09Z" },
    { as_of_date: "2024-08-01", label: "summer",     seed: 42, status: "archived", alerts:   8, plans: 4, coverage_pct: 99.8, created_at: "2026-05-06T18:33:21Z" },
  ];

  // Sources (provenance)
  const sources = [
    { source_id: "imd_climatology_1991_2020",  name: "IMD Climatology 1991-2020",          tier: "tier_1_authoritative" },
    { source_id: "cag_2017_18",                name: "CAG Audit Report 2017-18 (Defence)", tier: "tier_1_authoritative" },
    { source_id: "bro_annual_2023",            name: "BRO Annual Report 2023",             tier: "tier_2_credible" },
    { source_id: "mospi_press_2022",           name: "MoSPI press notes (POL prices)",     tier: "tier_2_credible" },
    { source_id: "openstreetmap_2024",         name: "OpenStreetMap (extracts 2024-Q3)",   tier: "tier_2_credible" },
  ];

  // ─────────────────────────────────────────────────────────────────── Day-progression helper
  // Deterministic day-by-day evolution around the canonical 2024-12-15 snapshot.
  // offset 0 = canonical; positive = future ticks; negative = past ticks.
  // The shape mirrors what a daily cron + replan would actually do:
  //   stockout-risk alerts rise as forward-post stocks deplete, then reset on resupply days,
  //   pass closure probabilities drift with weather noise around the canonical baseline,
  //   coverage % degrades as buffers shrink behind closed passes.
  function effectiveDate(offset) {
    const d = new Date("2024-12-15T00:00:00Z");
    d.setUTCDate(d.getUTCDate() + offset);
    return d.toISOString().slice(0, 10);
  }

  // Deterministic pseudo-random (mulberry32) seeded by offset.
  function rng(seed) {
    let t = (seed + 0x6D2B79F5) >>> 0;
    return function () {
      t = (t + 0x6D2B79F5) >>> 0;
      let r = t;
      r = Math.imul(r ^ (r >>> 15), r | 1);
      r ^= r + Math.imul(r ^ (r >>> 7), r | 61);
      return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
    };
  }

  function computeDay(offset) {
    const rand = rng(42 + offset * 7919);
    // Alert evolution: deplete-and-resupply cycle every ~7 days.
    // Forward posts are on a 5-day fresh-meat cadence; modeled as a sawtooth + noise.
    const phase = ((offset % 7) + 7) % 7;
    const sawtooth = phase <= 4 ? phase / 4 : (6 - phase) / 2; // peak day 4, low day 6
    const stockoutBase = 128;
    const stockoutCrit = Math.max(0, Math.round(stockoutBase * (0.20 + 0.06 * sawtooth) + (rand() - 0.5) * 6));
    const stockoutWarn = Math.max(0, Math.round(stockoutBase * (0.75 + 0.10 * sawtooth) + (rand() - 0.5) * 10));
    const stockoutTotal = stockoutCrit + stockoutWarn;

    // Disruption alerts: passes drift more in deeper winter (offset around 0 we're mid-Dec)
    const disruptionTotal = Math.max(2, Math.min(5, 3 + Math.round((rand() - 0.5) * 2)));
    const disruptionCrit = disruptionTotal > 3 ? 2 : 1;
    const disruptionWarn = disruptionTotal - disruptionCrit;

    // Vehicle deadlines: drift slowly with age (linear in offset)
    const vehicleTotal = Math.max(4, Math.min(10, 6 + Math.round(offset * 0.15) + Math.round((rand() - 0.5) * 1.5)));
    const vehicleCrit = Math.max(0, Math.min(3, 2 + Math.round((rand() - 0.5) * 1)));
    const vehicleWarn = vehicleTotal - vehicleCrit;

    // Coverage % drifts inversely with sawtooth (more stockouts = less coverage)
    const coverage = Math.max(18, Math.min(48, 31.7 - sawtooth * 3 + (rand() - 0.5) * 2));

    // Isolated post count: ranges 13-17 depending on pass states
    const isolated = Math.max(11, Math.min(18, 15 + Math.round((rand() - 0.5) * 4)));

    return {
      date: effectiveDate(offset),
      alert_totals: {
        stockout_risk:    { critical: stockoutCrit, warning: stockoutWarn, info: 0, total: stockoutTotal },
        disruption:       { critical: disruptionCrit, warning: disruptionWarn, info: 0, total: disruptionTotal },
        vehicle_deadline: { critical: vehicleCrit, warning: vehicleWarn, info: 0, total: vehicleTotal },
        total: stockoutTotal + disruptionTotal + vehicleTotal,
        acknowledged: 0,
      },
      coverage_pct: parseFloat(coverage.toFixed(1)),
      isolated_posts: isolated,
      // Cycle marker for the replay-mode banner
      cycle_phase: phase,
      sawtooth,
    };
  }

  return {
    snapshot, models, heads, skus, depots, posts, passes, routes, hydro, lac,
    route_predictions, stockout_risk, vehicles, vehicle_summary,
    alerts, alert_totals, plans, plan_legs, snapshots, sources,
    effectiveDate, computeDay,
  };
})();
