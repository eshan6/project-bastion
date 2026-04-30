/**
 * statusDerivation.ts — maps days-to-stockout to a discrete post status.
 *
 * Two rules:
 * 1. If the scenario file specifies a status on a key projection day,
 *    use it. Scenario authors picked the status deliberately at inflection
 *    points; the engine should respect that.
 * 2. On all other days, derive from days-to-stockout thresholds.
 *
 * The thresholds match the operational tempo the demo wants to convey:
 *   > 30 days   -> ok        (no immediate concern)
 *   15–30 days  -> watch     (planning horizon engaged)
 *   5–15 days   -> critical  (resupply must launch)
 *   < 5 days    -> imminent  (system has failed if this hits)
 */

import type { PostStatus, ProjectionDay } from "@/types";

const THRESHOLD_OK_LOW = 30;
const THRESHOLD_WATCH_LOW = 15;
const THRESHOLD_CRITICAL_LOW = 5;

export function statusFromDaysToStockout(days: number): PostStatus {
  if (days >= THRESHOLD_OK_LOW) return "ok";
  if (days >= THRESHOLD_WATCH_LOW) return "watch";
  if (days >= THRESHOLD_CRITICAL_LOW) return "critical";
  return "imminent";
}

/**
 * Authored statuses in the scenarios JSON include a non-canonical value
 * "critical_for_winter_readiness" (S3 Day 16). We collapse that to
 * "critical" for the post-status state machine; the nuance is shown in
 * the `note` text on the projection day, not in the color.
 */
export function normalizeAuthoredStatus(
  s: ProjectionDay["status"],
): PostStatus {
  if (s === "critical_for_winter_readiness") return "critical";
  return s;
}

/**
 * Status priority for ordering in lists / picking the "worst" across a
 * cluster. Higher number = more severe.
 */
export const STATUS_PRIORITY: Record<PostStatus, number> = {
  ok: 0,
  watch: 1,
  critical: 2,
  imminent: 3,
};

export function worseStatus(a: PostStatus, b: PostStatus): PostStatus {
  return STATUS_PRIORITY[a] >= STATUS_PRIORITY[b] ? a : b;
}
