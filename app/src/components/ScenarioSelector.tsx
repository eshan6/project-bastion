/**
 * ScenarioSelector — segmented control for the three scenarios.
 * Conservative SaaS chrome: white background, slate borders, blue accent
 * only on the selected option.
 */
import type { ScenariosFile, ScenarioId } from "@/types";

interface ScenarioSelectorProps {
  scenarios: ScenariosFile["scenarios"];
  selectedId: ScenarioId;
  onSelect: (id: ScenarioId) => void;
}

const SHORT_TITLES: Record<ScenarioId, string> = {
  "SCEN-01-NORMAL_OPS": "Normal ops",
  "SCEN-02-ZOJI_LA_CASCADE": "Zoji La cascade",
  "SCEN-03-VEHICLE_DEADLINE_CASCADE": "Vehicle cascade",
};

export function ScenarioSelector({
  scenarios,
  selectedId,
  onSelect,
}: ScenarioSelectorProps) {
  return (
    <div>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-faint">
        Scenario
      </div>
      <div className="flex flex-col gap-1.5">
        {scenarios.map((s) => {
          const isSelected = s.scenario_id === selectedId;
          return (
            <button
              key={s.scenario_id}
              type="button"
              onClick={() => onSelect(s.scenario_id)}
              className={`w-full rounded border px-3 py-2 text-left transition ${
                isSelected
                  ? "border-accent bg-accent-soft"
                  : "border-line bg-canvas hover:bg-surface"
              }`}
            >
              <div
                className={`text-sm font-semibold ${
                  isSelected ? "text-accent" : "text-ink"
                }`}
              >
                {SHORT_TITLES[s.scenario_id]}
              </div>
              <div className="mt-0.5 text-xs leading-snug text-ink-muted">
                {s.narrative_one_liner}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
