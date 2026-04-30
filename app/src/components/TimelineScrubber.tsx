/**
 * TimelineScrubber — 0..duration_days slider.
 *
 * Approach: a native <input type="range"> for accessibility + keyboard
 * support, with a custom visual track rendered behind it. The native
 * slider stays invisible but receives interaction. This is the pattern
 * Linear/Stripe use for sliders that need custom marks.
 *
 * Disruption events show as tick marks above the track at their respective
 * days. Hovering a tick reveals a tooltip with the event description.
 */
import type { DisruptionEvent } from "@/types";

interface TimelineScrubberProps {
  day: number;
  durationDays: number;
  disruptions: DisruptionEvent[];
  onDayChange: (day: number) => void;
}

export function TimelineScrubber({
  day,
  durationDays,
  disruptions,
  onDayChange,
}: TimelineScrubberProps) {
  const pct = (day / durationDays) * 100;

  return (
    <div className="w-full">
      <div className="mb-2 flex items-baseline justify-between">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
          Timeline
        </div>
        <div className="text-xs text-ink-muted">
          Day <span className="font-semibold text-ink">{day}</span> of {durationDays}
        </div>
      </div>

      <div className="relative h-12">
        {/* Disruption ticks (rendered above the track) */}
        <div className="absolute left-0 right-0 top-0 h-3">
          {disruptions.map((d) => {
            const tickPct = (d.day / durationDays) * 100;
            return (
              <div
                key={`${d.day}-${d.type}`}
                className="group absolute -translate-x-1/2"
                style={{ left: `${tickPct}%` }}
                title={`Day ${d.day}: ${d.description}`}
              >
                <div className="h-3 w-px bg-ink-faint" />
                <div className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap text-[10px] font-medium text-ink-faint">
                  D{d.day}
                </div>
              </div>
            );
          })}
        </div>

        {/* Track */}
        <div className="absolute left-0 right-0 top-5 h-1 rounded-full bg-line">
          <div
            className="h-full rounded-full bg-accent"
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Thumb (visual) */}
        <div
          className="pointer-events-none absolute top-3 h-5 w-5 -translate-x-1/2 rounded-full border-2 border-accent bg-canvas shadow-card"
          style={{ left: `${pct}%` }}
        />

        {/* Native input (transparent, captures interaction) */}
        <input
          type="range"
          min={0}
          max={durationDays}
          step={1}
          value={day}
          onChange={(e) => onDayChange(parseInt(e.target.value, 10))}
          className="absolute left-0 right-0 top-3 z-10 h-5 w-full cursor-pointer opacity-0"
          aria-label={`Day ${day} of ${durationDays}`}
        />
      </div>

      {/* Day labels at start, mid, end */}
      <div className="mt-1 flex justify-between text-[10px] text-ink-faint">
        <span>D0</span>
        <span>D{Math.floor(durationDays / 2)}</span>
        <span>D{durationDays}</span>
      </div>
    </div>
  );
}
