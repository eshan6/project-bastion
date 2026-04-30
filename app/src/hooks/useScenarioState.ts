/**
 * useScenarioState — selected scenario id + current day, with derived
 * world-state computed by lib/scenarioEngine.computeWorldState().
 *
 * This is the only place in the app that mutates scenario UI state. The
 * components below the App tree consume it read-only via props.
 */
import { useMemo, useState } from "react";
import type { FspData } from "./useFspData";
import type { ScenarioId } from "@/types";
import { computeWorldState, type ScenarioWorldState } from "@/lib/scenarioEngine";

export interface UseScenarioStateReturn {
  scenarioId: ScenarioId;
  setScenarioId: (id: ScenarioId) => void;
  day: number;
  setDay: (d: number) => void;
  worldState: ScenarioWorldState;
}

export function useScenarioState(data: FspData): UseScenarioStateReturn {
  // Default to S2 — the headline scenario for the demo (Zoji La cascade).
  // Reviewers see the most differentiated value when they open the app.
  const [scenarioId, setScenarioId] = useState<ScenarioId>("SCEN-02-ZOJI_LA_CASCADE");
  const [day, setDay] = useState<number>(0);

  const worldState = useMemo(() => {
    const scenario = data.scenarios.scenarios.find((s) => s.scenario_id === scenarioId);
    if (!scenario) {
      // Fallback should never happen — locked invariants guarantee 3 scenarios.
      return computeWorldState(data.scenarios.scenarios[0], day, data.posts, data.skus);
    }
    return computeWorldState(scenario, day, data.posts, data.skus);
  }, [data, scenarioId, day]);

  // When the scenario changes, snap day back to 0. Without this, scrubbing
  // to Day 60 in S2 then switching to S1 leaves you at Day 60 of S1 — which
  // is technically valid but disorienting for a reviewer.
  const setScenarioWithReset = (id: ScenarioId) => {
    setScenarioId(id);
    setDay(0);
  };

  return {
    scenarioId,
    setScenarioId: setScenarioWithReset,
    day,
    setDay,
    worldState,
  };
}
