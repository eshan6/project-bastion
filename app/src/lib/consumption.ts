/**
 * consumption.ts — burn-rate math for the scenario engine.
 *
 * Reproduces the calculations documented in scenarios.json' calc strings,
 * e.g. "1200 hc x 0.80 L/soldier/day x 1.6 winter_uplift = 1536 L/day".
 *
 * Why this is its own file: the same math is used in three places —
 * scenario simulation (lib/scenarioEngine.ts), drill-down panels
 * (PostDetailPanel.tsx), and the eventual Wk9 resupply-options sourcing.
 * Keeping it pure and isolated makes it cheap to verify against the
 * scenarios.json key_projection_days values.
 */

import type { SKU, TerrainClass, PerSoldierPerDay } from "@/types";

// ---- Terrain class resolution ------------------------------------------

/**
 * skus.json defines a post_to_terrain_class map but uses extended classes
 * (e.g. "HA_extreme_cold", "SHA_to_ECC") that aren't keys in the
 * per-soldier-per-day consumption maps. Normalize to the four canonical
 * classes used in consumption rates: Plains, HA, SHA, ECC.
 */
export function canonicalizeTerrainClass(
  tc: TerrainClass,
): "Plains" | "HA" | "SHA" | "ECC" {
  switch (tc) {
    case "Plains":
    case "HA":
    case "SHA":
    case "ECC":
      return tc;
    case "HA_extreme_cold":
      // Drass Garrison: technically HA by altitude (3,280m) but consumption
      // pattern is closer to SHA due to extreme winter cold. Treat as HA
      // for off-season; winter uplift handles the seasonal load.
      return "HA";
    case "HA_to_SHA_boundary":
      // Hanle, Loma, Demchok (~4150-4380m). Bias toward SHA — these posts
      // operate above the standard HA threshold for most of the year.
      return "SHA";
    case "SHA_to_ECC":
      // POST-001 DBO Base, POST-015 Tiger Hill (>5000m). ECC behavior.
      return "ECC";
    default:
      // Compile-time exhaustiveness guard.
      const _exhaustive: never = tc;
      return _exhaustive;
  }
}

// ---- Season ------------------------------------------------------------

export type Season = "summer" | "winter";

/**
 * Winter uplift kicks in roughly Day 30+ in scenarios where the season
 * transitions during the 90-day window. Each scenario specifies its own
 * threshold via the focal projection's `kerosene_burn_phases`; this is
 * the fallback for scenarios that don't.
 *
 * In Eastern Ladakh real-world: winter starts ~late Oct at SHA, mid-Nov
 * at HA. Demo simplifies to a single transition day per scenario.
 */
export function defaultSeasonForDay(
  day: number,
  scenarioStart: string,
): Season {
  // Months in the season_start string drive this. The scenarios use:
  // S1 "August (Day 0 = 1 Aug)" -> summer through Day 90 (ends ~30 Oct)
  //   Real Eastern Ladakh: ECC posts (POST-001 DBO) feel winter from Oct 1,
  //   so Days 60+ in S1 do edge into early-winter rates.
  // S2 "October (Day 0 = 15 Oct)" -> winter from Day 0
  // S3 "September (Day 0 = 5 Sep)" -> summer through ~Day 30, winter Day 30+
  const lower = scenarioStart.toLowerCase();
  if (lower.includes("october") || lower.includes("november") || lower.includes("december")) {
    return "winter";
  }
  if (lower.includes("september")) {
    return day >= 30 ? "winter" : "summer";
  }
  if (lower.includes("august")) {
    return day >= 60 ? "winter" : "summer";
  }
  return "summer";
}

// ---- Kerosene burn (the dominant SHA/ECC consumable) -------------------

/**
 * Daily kerosene burn in litres for a given headcount + terrain class +
 * season. Mirrors the formula in scenarios.json calc strings.
 *
 * Formula: hc × per_soldier_per_day(terrain) × winter_uplift_if_winter
 *
 * The kerosene SKU has winter_uplift_factor = 1.6 in skus.json. The same
 * 1.6 appears in scenarios.json focal_cluster_projection.winter_uplift_factor.
 */
export function dailyKeroseneBurnL(
  headcount: number,
  terrainClass: TerrainClass,
  season: Season,
  keroseneSku: SKU,
): number {
  const tc = canonicalizeTerrainClass(terrainClass);
  const perSoldier = keroseneSku.consumption_baseline_per_soldier_per_day?.[tc];
  if (perSoldier === undefined) {
    return 0;
  }
  const uplift = season === "winter" ? keroseneSku.winter_uplift_factor : 1.0;
  return headcount * perSoldier * uplift;
}

// ---- Generic per-soldier-per-day consumption ---------------------------

/**
 * For SKUs other than kerosene (rations, dal, oil, etc.) the same shape
 * applies. Returns 0 if the SKU doesn't use a per-soldier-per-day model.
 */
export function dailyPerSoldierBurn(
  headcount: number,
  terrainClass: TerrainClass,
  season: Season,
  sku: SKU,
): number {
  const map: PerSoldierPerDay | undefined =
    sku.consumption_baseline_per_soldier_per_day;
  if (!map) return 0;
  const tc = canonicalizeTerrainClass(terrainClass);
  const perSoldier = map[tc];
  if (perSoldier === undefined) return 0;
  const uplift = season === "winter" ? sku.winter_uplift_factor : 1.0;
  return headcount * perSoldier * uplift;
}
