/**
 * scenarioEngine.ts — given (scenario, day), produces a coherent
 * world-state snapshot for the rest of the UI to render against.
 *
 * Core idea:
 *   For each focal post in the scenario, simulate kerosene stock day-by-day
 *   from Day 0. Anchor to the key_projection_days values that the scenario
 *   author specified; interpolate stocks between anchors using the
 *   documented daily burn formula and any disruption events that fire
 *   between anchors.
 *
 * Why anchor instead of pure forward simulation:
 *   The cascade math in the scenarios encodes things the burn formula alone
 *   doesn't (e.g. S2 Day 18 "Drass cold-snap +30%", S3 Day 16 convoy delivery
 *   of 27kL). Rather than try to model every authored event, we trust the
 *   author's anchor values and use the formula to fill day-by-day gaps.
 *   Result: Day 5 (an anchor) shows exactly what the file says, Day 6 shows
 *   a coherent interpolation, Day 12 (another anchor) shows what the file
 *   says again. No surprises for advisor inspection.
 *
 * What the engine returns:
 *   ScenarioWorldState — a typed snapshot that includes:
 *     - day (0..duration_days)
 *     - per-post status + days-to-stockout + current stock
 *     - active disruptions (those whose day <= current day)
 *     - closed routes (derived from disruption route_impacts)
 *     - the "active alert" if a resupply-options card should be visible today
 *
 * Determinism: same (scenario, day) -> same state. No hidden randomness.
 */

import type {
  Scenario,
  PostStatus,
  ProjectionDay,
  DisruptionEvent,
  ResupplyOptionsCard,
  PostsFile,
  Post,
  SkusFile,
} from "@/types";
import { normalizeAuthoredStatus, statusFromDaysToStockout, worseStatus } from "./statusDerivation";
import { dailyKeroseneBurnL, defaultSeasonForDay, type Season } from "./consumption";

// ---- Public types ------------------------------------------------------

export interface PostStateSnapshot {
  post_id: string;
  post_name: string;
  /** Current kerosene stock (litres) on this day. May be 0 if depleted. */
  kerosene_stock_L: number | null;
  /** Days remaining at current burn rate. null when no projection exists. */
  days_to_stockout: number | null;
  status: PostStatus;
  /** Current daily burn rate (L/day). Useful for the drill-down panel. */
  daily_burn_L: number | null;
  /** Optional note attached by the scenario author at this day. */
  note?: string;
  /** True if today's status came from an authored key_projection_day. */
  is_anchor_day: boolean;
}

export interface ScenarioWorldState {
  scenario_id: string;
  scenario_title: string;
  day: number;
  duration_days: number;
  season: Season;
  /** Per-post snapshots, keyed by post_id. Includes only posts the scenario tracks. */
  post_states: Map<string, PostStateSnapshot>;
  /** Worst status across all tracked posts (drives the global header indicator). */
  global_worst_status: PostStatus;
  /** Disruption events that have fired on or before today, in chronological order. */
  active_disruptions: DisruptionEvent[];
  /** Disruptions firing today (subset of active_disruptions, day === current day). */
  todays_disruptions: DisruptionEvent[];
  /** Edge ids that are currently closed (derived from disruption route_impacts). */
  closed_edge_ids: Set<string>;
  /** Active resupply-options card (visible if a critical alert was reached). */
  active_alert: ScenarioAlert | null;
}

export interface ScenarioAlert {
  trigger_day: number;
  card: ResupplyOptionsCard;
}

// ---- Engine ------------------------------------------------------------

/**
 * Compute world-state for the given scenario at the given day.
 */
export function computeWorldState(
  scenario: Scenario,
  day: number,
  postsFile: PostsFile,
  skusFile: SkusFile,
): ScenarioWorldState {
  const clampedDay = Math.max(0, Math.min(day, scenario.duration_days));
  const season = defaultSeasonForDay(clampedDay, scenario.season_start);

  // ---- 1. Disruptions
  const activeDisruptions = scenario.disruption_events
    .filter((e) => e.day <= clampedDay)
    .sort((a, b) => a.day - b.day);
  const todaysDisruptions = activeDisruptions.filter((e) => e.day === clampedDay);

  // ---- 2. Closed routes (cumulative over all active disruptions)
  const closedEdgeIds = new Set<string>();
  for (const dev of activeDisruptions) {
    if (!dev.route_impacts) continue;
    for (const [edgeId, state] of Object.entries(dev.route_impacts)) {
      if (edgeId === "implication") continue; // skip the prose field
      if (typeof state === "string" && state.toLowerCase() === "closed") {
        closedEdgeIds.add(edgeId);
      }
    }
  }
  // Scenario's starting_state.closed_routes are LoC ids, not edge ids — keep
  // them in a separate set if needed by the route layer. For Wk8 we only
  // close edges that are explicitly named in disruption route_impacts, since
  // those are the ones the route polylines key off.

  // ---- 3. Per-post stock simulation
  const postStates = simulatePostStocks(scenario, clampedDay, postsFile, skusFile, season);

  // ---- 4. Worst status across tracked posts
  let globalWorst: PostStatus = "ok";
  for (const snap of postStates.values()) {
    globalWorst = worseStatus(globalWorst, snap.status);
  }

  // ---- 5. Active alert (resupply-options card)
  const activeAlert = findActiveAlert(scenario, clampedDay);

  return {
    scenario_id: scenario.scenario_id,
    scenario_title: scenario.title,
    day: clampedDay,
    duration_days: scenario.duration_days,
    season,
    post_states: postStates,
    global_worst_status: globalWorst,
    active_disruptions: activeDisruptions,
    todays_disruptions: todaysDisruptions,
    closed_edge_ids: closedEdgeIds,
    active_alert: activeAlert,
  };
}

// ---- Per-post simulation -----------------------------------------------

/**
 * Build a Day -> PostStateSnapshot map for each post the scenario tracks.
 *
 * Tracking source priority:
 *   1. focal_post_projection (S1, S3) — single post, key_projection_days
 *   2. focal_cluster_projection (S2) — multiple posts, cluster key_projection_days
 *      In this case we attribute the cluster total to the cluster_posts in
 *      proportion to their daily_burn_L_by_post share, so individual posts
 *      get plausible per-post stocks.
 */
function simulatePostStocks(
  scenario: Scenario,
  day: number,
  postsFile: PostsFile,
  skusFile: SkusFile,
  season: Season,
): Map<string, PostStateSnapshot> {
  const out = new Map<string, PostStateSnapshot>();
  const keroseneSku = skusFile.skus.find((s) => s.sku_id === "SKU-POL-002");

  if (scenario.focal_post_projection) {
    const fp = scenario.focal_post_projection;
    const post = postsFile.posts.find((p) => p.post_id === fp.post_id);
    if (post && keroseneSku) {
      const snap = simulateSinglePost(
        post,
        fp.headcount,
        fp.key_projection_days,
        day,
        season,
        keroseneSku,
        skusFile,
      );
      out.set(post.post_id, snap);
    }
  }

  if (scenario.focal_cluster_projection) {
    const fc = scenario.focal_cluster_projection;
    const burnByPost = fc.daily_burn_L_by_post;
    const totalBurn = fc.cluster_burn_total_L_per_day;

    // Build the cluster-level day-by-day stock projection.
    const clusterStockByDay = simulateClusterStocks(fc.key_projection_days, day, totalBurn);

    // Attribute cluster stock to individual posts by burn share.
    for (const [postKey, perPost] of Object.entries(burnByPost)) {
      // Keys look like "POST-013_Kargil_HQ_HA" — first segment is the post id.
      const postId = postKey.split("_")[0];
      const realPostId = postKey.startsWith("POST-")
        ? `POST-${postKey.split("-")[1].split("_")[0]}`
        : postId;
      const post = postsFile.posts.find((p) => p.post_id === realPostId);
      if (!post) continue;

      const burnShare = perPost.burn_L_per_day / totalBurn;
      const stock = clusterStockByDay * burnShare;
      const dailyBurn = perPost.burn_L_per_day;
      const dts = dailyBurn > 0 ? Math.floor(stock / dailyBurn) : null;

      // Anchor status from cluster key day if present
      const anchorKey = `day_${day}`;
      const authored = fc.key_projection_days[anchorKey];
      const status: PostStatus = authored
        ? normalizeAuthoredStatus(authored.status)
        : dts !== null
          ? statusFromDaysToStockout(dts)
          : "ok";

      out.set(post.post_id, {
        post_id: post.post_id,
        post_name: post.name,
        kerosene_stock_L: Math.round(stock),
        days_to_stockout: dts,
        status,
        daily_burn_L: dailyBurn,
        note: authored?.note,
        is_anchor_day: !!authored,
      });
    }
  }

  return out;
}

// ---- Single-post simulation --------------------------------------------

function simulateSinglePost(
  post: Post,
  headcount: number,
  keyDays: Record<string, ProjectionDay>,
  day: number,
  season: Season,
  keroseneSku: import("@/types").SKU,
  skusFile: SkusFile,
): PostStateSnapshot {
  // Sort anchor days numerically.
  const anchors: Array<{ d: number; pd: ProjectionDay }> = Object.entries(keyDays)
    .map(([k, v]) => ({ d: parseDayKey(k), pd: v }))
    .filter((a) => a.d !== null)
    .map((a) => ({ d: a.d as number, pd: a.pd }))
    .sort((a, b) => a.d - b.d);

  if (anchors.length === 0) {
    return {
      post_id: post.post_id,
      post_name: post.name,
      kerosene_stock_L: null,
      days_to_stockout: null,
      status: "ok",
      daily_burn_L: null,
      is_anchor_day: false,
    };
  }

  // Authored anchor on the requested day?
  const exact = anchors.find((a) => a.d === day);
  if (exact) {
    const stock = exact.pd.kerosene_stock_L ?? null;
    const dts =
      exact.pd.days_to_stockout_at_current_burn ??
      exact.pd.days_to_stockout_summer_burn ??
      exact.pd.days_to_stockout_winter_burn ??
      exact.pd.days_to_winter_stockout_actual ??
      null;
    const terrainClass = skusFile._meta.post_to_terrain_class[post.post_id];
    const dailyBurn = terrainClass
      ? dailyKeroseneBurnL(headcount, terrainClass, season, keroseneSku)
      : null;
    return {
      post_id: post.post_id,
      post_name: post.name,
      kerosene_stock_L: stock,
      days_to_stockout: dts,
      status: normalizeAuthoredStatus(exact.pd.status),
      daily_burn_L: dailyBurn,
      note: exact.pd.note,
      is_anchor_day: true,
    };
  }

  // No exact anchor — interpolate between bracketing anchors using a linear
  // stock decline at the current burn rate. This is the "trust the formula
  // between anchors" path documented in the file header.
  const before = [...anchors].reverse().find((a) => a.d < day);
  const after = anchors.find((a) => a.d > day);

  const terrainClass = skusFile._meta.post_to_terrain_class[post.post_id];
  const dailyBurn = terrainClass
    ? dailyKeroseneBurnL(headcount, terrainClass, season, keroseneSku)
    : 0;

  let stock: number | null = null;
  if (before && after) {
    // Linear interpolation between authored stock values.
    const beforeStock = before.pd.kerosene_stock_L ?? null;
    const afterStock = after.pd.kerosene_stock_L ?? null;
    if (beforeStock !== null && afterStock !== null) {
      const t = (day - before.d) / (after.d - before.d);
      stock = beforeStock + t * (afterStock - beforeStock);
    }
  } else if (before) {
    // Past the last anchor — extrapolate forward at current burn rate.
    const beforeStock = before.pd.kerosene_stock_L ?? null;
    if (beforeStock !== null) {
      stock = Math.max(0, beforeStock - dailyBurn * (day - before.d));
    }
  } else if (after) {
    // Before the first anchor (rare). Extrapolate backward.
    const afterStock = after.pd.kerosene_stock_L ?? null;
    if (afterStock !== null) {
      stock = afterStock + dailyBurn * (after.d - day);
    }
  }

  const dts = stock !== null && dailyBurn > 0 ? Math.floor(stock / dailyBurn) : null;
  const status = dts !== null ? statusFromDaysToStockout(dts) : "ok";

  return {
    post_id: post.post_id,
    post_name: post.name,
    kerosene_stock_L: stock !== null ? Math.round(stock) : null,
    days_to_stockout: dts,
    status,
    daily_burn_L: dailyBurn || null,
    is_anchor_day: false,
  };
}

// ---- Cluster simulation ------------------------------------------------

function simulateClusterStocks(
  keyDays: Record<string, ProjectionDay>,
  day: number,
  totalBurn: number,
): number {
  const anchors = Object.entries(keyDays)
    .map(([k, v]) => ({ d: parseDayKey(k), pd: v }))
    .filter((a) => a.d !== null && (a.pd.cluster_stock_L !== undefined))
    .map((a) => ({ d: a.d as number, stock: a.pd.cluster_stock_L as number }))
    .sort((a, b) => a.d - b.d);

  if (anchors.length === 0) return 0;

  const exact = anchors.find((a) => a.d === day);
  if (exact) return exact.stock;

  const before = [...anchors].reverse().find((a) => a.d < day);
  const after = anchors.find((a) => a.d > day);

  if (before && after) {
    const t = (day - before.d) / (after.d - before.d);
    return before.stock + t * (after.stock - before.stock);
  }
  if (before) {
    return Math.max(0, before.stock - totalBurn * (day - before.d));
  }
  if (after) {
    return after.stock + totalBurn * (after.d - day);
  }
  return 0;
}

// ---- Alert detection ---------------------------------------------------

/**
 * Each scenario has at most one resupply_options_at_day_N_alert. Find the
 * trigger day from the field name ("resupply_options_at_day_12_alert" -> 12)
 * and return the card if today >= that day.
 */
function findActiveAlert(scenario: Scenario, day: number): ScenarioAlert | null {
  // Walk known alert keys. Adding a new alert day later means adding a key here.
  const candidates: Array<{ day: number; card: ResupplyOptionsCard | undefined }> = [
    { day: 12, card: scenario.resupply_options_at_day_12_alert },
    { day: 10, card: scenario.resupply_options_at_day_10_alert },
  ];
  // System recommendation in S1 fires at Day 18 — model as an alert too.
  if (scenario.system_recommendation_at_day_18 && day >= 18) {
    // S1's "alert" isn't a resupply-options card per se but a recommendation.
    // For Wk8 we surface it through a different banner; leave the alert
    // null here so the resupply-options panel doesn't pop on S1.
  }

  for (const c of candidates) {
    if (c.card && day >= c.day) {
      return { trigger_day: c.day, card: c.card };
    }
  }
  return null;
}

// ---- Helpers -----------------------------------------------------------

/**
 * Parse day keys like "day_0", "day_18", "day_75_with_remediation" into a
 * numeric day. Suffixes like "_with_remediation" are stripped — they're
 * authored-side annotations, not separate days.
 */
function parseDayKey(key: string): number | null {
  const m = key.match(/^day_(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}
