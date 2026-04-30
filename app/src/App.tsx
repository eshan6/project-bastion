/**
 * App (Wk8) — top-level shell, now scenario-aware.
 *
 * State owned here:
 *   - selectedPostId (drives map highlight + sidebar detail panel)
 *
 * Scenario state (selected scenario, current day, derived world-state)
 * is in useScenarioState, loaded from useFspData.
 */
import { useState } from "react";
import { MapView } from "@/components/MapView";
import { Sidebar } from "@/components/Sidebar";
import { DisruptionBanner } from "@/components/DisruptionBanner";
import { StatusPill } from "@/components/StatusPill";
import { useFspData, type FspData } from "@/hooks/useFspData";
import { useScenarioState } from "@/hooks/useScenarioState";

export function App() {
  const state = useFspData();

  return (
    <div className="flex h-full w-full flex-col">
      {state.status === "loading" && (
        <>
          <Header />
          <main className="flex flex-1 items-center justify-center bg-surface text-sm text-ink-muted">
            Loading FSP data…
          </main>
        </>
      )}
      {state.status === "error" && (
        <>
          <Header />
          <main className="flex flex-1 items-center justify-center bg-surface p-8">
            <div className="max-w-2xl rounded-md border border-status-critical-soft bg-status-critical-soft p-4">
              <div className="text-sm font-semibold text-status-critical">
                Could not load demo data
              </div>
              <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-ink-muted">
                {state.error}
              </pre>
            </div>
          </main>
        </>
      )}
      {state.status === "ready" && <Loaded data={state.data} />}
    </div>
  );
}

function Loaded({ data }: { data: FspData }) {
  const { scenarioId, setScenarioId, day, setDay, worldState } = useScenarioState(data);
  const [selectedPostId, setSelectedPostId] = useState<string | null>(null);

  return (
    <>
      <Header
        scenarioTitle={worldState.scenario_title}
        worstStatus={worldState.global_worst_status}
        day={worldState.day}
        durationDays={worldState.duration_days}
      />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          data={data}
          scenarioId={scenarioId}
          setScenarioId={setScenarioId}
          day={day}
          setDay={setDay}
          worldState={worldState}
          selectedPostId={selectedPostId}
          onSelectPost={setSelectedPostId}
        />
        <main className="flex flex-1 flex-col bg-surface">
          {worldState.todays_disruptions.length > 0 && (
            <DisruptionBanner events={worldState.todays_disruptions} />
          )}
          <div className="relative flex-1">
            <MapView
              posts={data.posts}
              routes={data.routes}
              worldState={worldState}
              selectedPostId={selectedPostId}
              onSelectPost={setSelectedPostId}
            />
          </div>
        </main>
      </div>
    </>
  );
}

interface HeaderProps {
  scenarioTitle?: string;
  worstStatus?: import("@/types").PostStatus;
  day?: number;
  durationDays?: number;
}

function Header({ scenarioTitle, worstStatus, day, durationDays }: HeaderProps) {
  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-canvas px-4">
      <div className="flex items-center gap-3">
        <div className="flex h-6 w-6 items-center justify-center rounded bg-accent text-xs font-semibold text-white">
          B
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-ink">Bastion FSP</span>
          <span className="text-xs text-ink-muted">Forward Stockout Predictor</span>
        </div>
      </div>
      <div className="flex items-center gap-3 text-xs text-ink-muted">
        {scenarioTitle && (
          <span className="max-w-md truncate text-ink">
            {scenarioTitle}
          </span>
        )}
        {day !== undefined && durationDays !== undefined && (
          <span className="rounded border border-line bg-surface px-2 py-0.5 font-mono">
            D{day}/{durationDays}
          </span>
        )}
        {worstStatus && <StatusPill status={worstStatus} size="sm" />}
        <span className="rounded border border-line bg-surface px-2 py-0.5 font-medium">
          DEMO
        </span>
        <span className="text-ink-faint">v0.2 · Wk8</span>
      </div>
    </header>
  );
}
