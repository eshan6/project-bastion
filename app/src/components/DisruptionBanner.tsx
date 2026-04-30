/**
 * DisruptionBanner — small banner above the map that surfaces disruptions
 * firing today. Stays visible only when day === disruption.day so it
 * functions as a "this just happened" indicator while the operator scrubs.
 */
import type { DisruptionEvent } from "@/types";

const TYPE_LABELS: Record<string, string> = {
  vehicle_reliability_signal: "Vehicle reliability signal",
  weather_minor: "Weather (minor)",
  demand_uplift: "Demand uplift",
  weather_severe: "Weather (severe)",
  demand_recognition: "System alert",
  secondary_disruption: "Secondary disruption",
  vehicle_deadline: "Vehicle deadline",
};

const TYPE_TONE: Record<string, "info" | "warn" | "critical"> = {
  vehicle_reliability_signal: "info",
  weather_minor: "info",
  demand_uplift: "info",
  weather_severe: "critical",
  demand_recognition: "warn",
  secondary_disruption: "warn",
  vehicle_deadline: "critical",
};

const TONE_CLASSES = {
  info: "border-line bg-surface",
  warn: "border-status-watch/30 bg-status-watch-soft",
  critical: "border-status-critical/30 bg-status-critical-soft",
};

export function DisruptionBanner({ events }: { events: DisruptionEvent[] }) {
  if (events.length === 0) return null;

  return (
    <div className="space-y-1.5 px-4 pt-3">
      {events.map((e, idx) => {
        const tone = TYPE_TONE[e.type] ?? "info";
        return (
          <div
            key={`${e.day}-${e.type}-${idx}`}
            className={`flex items-start gap-3 rounded border px-3 py-2 text-sm ${TONE_CLASSES[tone]}`}
          >
            <div className="shrink-0 text-xs font-semibold uppercase tracking-wider text-ink-faint">
              D{e.day}
            </div>
            <div className="flex-1">
              <div className="text-xs font-semibold text-ink">
                {TYPE_LABELS[e.type] ?? e.type}
              </div>
              <div className="text-xs leading-snug text-ink-muted">
                {e.description}
              </div>
              {e.non_obvious_insight && (
                <div className="mt-1 text-xs italic leading-snug text-ink-muted">
                  Insight: {e.non_obvious_insight}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
