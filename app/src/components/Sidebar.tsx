/**
 * Sidebar — left panel containing all scenario controls and selection state.
 *
 * Layout (top to bottom):
 *   1. Scenario selector (3 buttons)
 *   2. Timeline scrubber + day readout
 *   3. Post status list (sorted by severity, drives selection)
 *   4. Selected post detail panel (when a post is selected)
 *   5. Methodology link footer
 */
import type { FspData } from "@/hooks/useFspData";
import type { ScenarioId } from "@/types";
import type { ScenarioWorldState } from "@/lib/scenarioEngine";
import { ScenarioSelector } from "./ScenarioSelector";
import { TimelineScrubber } from "./TimelineScrubber";
import { PostDetailPanel } from "./PostDetailPanel";
import { StatusPill } from "./StatusPill";
import { STATUS_PRIORITY } from "@/lib/statusDerivation";

interface SidebarProps {
  data: FspData;
  scenarioId: ScenarioId;
  setScenarioId: (id: ScenarioId) => void;
  day: number;
  setDay: (d: number) => void;
  worldState: ScenarioWorldState;
  selectedPostId: string | null;
  onSelectPost: (postId: string | null) => void;
}

export function Sidebar({
  data,
  scenarioId,
  setScenarioId,
  day,
  setDay,
  worldState,
  selectedPostId,
  onSelectPost,
}: SidebarProps) {
  const selectedPost = selectedPostId
    ? data.posts.posts.find((p) => p.post_id === selectedPostId)
    : null;
  const selectedSnap = selectedPostId ? worldState.post_states.get(selectedPostId) : undefined;

  // Posts sorted by status severity, then by post_id for stability.
  const postsRanked = [...data.posts.posts].sort((a, b) => {
    const sa = worldState.post_states.get(a.post_id)?.status ?? "ok";
    const sb = worldState.post_states.get(b.post_id)?.status ?? "ok";
    const diff = STATUS_PRIORITY[sb] - STATUS_PRIORITY[sa];
    if (diff !== 0) return diff;
    return a.post_id.localeCompare(b.post_id);
  });

  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-hidden border-r border-line bg-canvas">
      {/* Top section: scenario + scrubber */}
      <div className="space-y-4 border-b border-line p-4">
        <ScenarioSelector
          scenarios={data.scenarios.scenarios}
          selectedId={scenarioId}
          onSelect={setScenarioId}
        />
        <TimelineScrubber
          day={day}
          durationDays={worldState.duration_days}
          disruptions={data.scenarios.scenarios.find((s) => s.scenario_id === scenarioId)?.disruption_events ?? []}
          onDayChange={setDay}
        />
      </div>

      {/* Middle section: scrollable post list */}
      <div className="flex-1 overflow-y-auto">
        <div className="border-b border-line p-4">
          <div className="mb-2 flex items-baseline justify-between">
            <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
              Posts ({data.posts.posts.length})
            </div>
            <div className="text-xs text-ink-faint">
              by status
            </div>
          </div>

          <ul className="-mx-1 space-y-0.5">
            {postsRanked.map((p) => {
              const snap = worldState.post_states.get(p.post_id);
              const status = snap?.status ?? "ok";
              const isSelected = p.post_id === selectedPostId;
              return (
                <li key={p.post_id}>
                  <button
                    type="button"
                    onClick={() => onSelectPost(isSelected ? null : p.post_id)}
                    className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left transition ${
                      isSelected ? "bg-accent-soft" : "hover:bg-surface"
                    }`}
                  >
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium text-ink">
                        {p.name}
                      </div>
                      <div className="truncate text-xs text-ink-muted">
                        {p.post_id} · {p.altitude_m}m
                      </div>
                    </div>
                    <StatusPill status={status} size="sm" />
                  </button>
                </li>
              );
            })}
          </ul>
        </div>

        {selectedPost && (
          <PostDetailPanel
            post={selectedPost}
            snapshot={selectedSnap}
            onClose={() => onSelectPost(null)}
          />
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-line p-3 text-xs text-ink-faint">
        Synthetic + public-data demo. See{" "}
        <a
          href="/data/methodology.md"
          className="text-accent hover:text-accent-hover"
          target="_blank"
          rel="noreferrer"
        >
          methodology
        </a>
        .
      </div>
    </aside>
  );
}
