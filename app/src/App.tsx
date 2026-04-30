/**
 * App — top-level shell.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────┐
 *   │  Header: product name, env, version              │
 *   ├──────────────┬───────────────────────────────────┤
 *   │              │                                    │
 *   │   Sidebar    │            MapView                 │
 *   │  (Wk8 will   │                                    │
 *   │   add the    │                                    │
 *   │   scenario   │                                    │
 *   │   scrubber)  │                                    │
 *   │              │                                    │
 *   └──────────────┴───────────────────────────────────┘
 *
 * Wk7 deliberately leaves the sidebar mostly empty — its content (timeline
 * scrubber, scenario selector, post drill-down) is the entire point of Wk8.
 * Putting placeholder copy there now makes the empty-state visible to anyone
 * reviewing the demo and keeps the layout from feeling broken.
 */
import { MapView } from "@/components/MapView";
import { useFspData } from "@/hooks/useFspData";

export function App() {
  const state = useFspData();

  return (
    <div className="flex h-full w-full flex-col">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <main className="flex-1 bg-surface">
          {state.status === "loading" && <LoadingPanel />}
          {state.status === "error" && <ErrorPanel error={state.error} />}
          {state.status === "ready" && <MapView data={state.data.posts} />}
        </main>
      </div>
    </div>
  );
}

// ---- Header ----

function Header() {
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
        <span className="rounded border border-line bg-surface px-2 py-0.5 font-medium">
          DEMO
        </span>
        <span>XIV Corps AOI · Eastern Ladakh</span>
        <span className="text-ink-faint">v0.1 · Wk7</span>
      </div>
    </header>
  );
}

// ---- Sidebar ----

function Sidebar() {
  return (
    <aside className="flex w-72 shrink-0 flex-col border-r border-line bg-canvas">
      <div className="border-b border-line p-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
          Scenario
        </div>
        <div className="mt-2 rounded border border-line bg-surface p-3 text-sm text-ink-muted">
          Scenario controls and the 90-day timeline scrubber appear here in
          Wk8. For now the map shows posts and depots without time-varying
          status.
        </div>
      </div>
      <div className="border-b border-line p-4">
        <div className="text-xs font-semibold uppercase tracking-wider text-ink-faint">
          Selection
        </div>
        <div className="mt-2 text-sm text-ink-muted">
          Click a marker on the map to see post or depot details.
        </div>
      </div>
      <div className="mt-auto border-t border-line p-4 text-xs text-ink-faint">
        Synthetic + public-data demo. See the methodology document at{" "}
        <a
          href="/data/methodology.md"
          className="text-accent hover:text-accent-hover"
          target="_blank"
          rel="noreferrer"
        >
          /data/methodology.md
        </a>
        .
      </div>
    </aside>
  );
}

// ---- Loading + error states ----

function LoadingPanel() {
  return (
    <div className="flex h-full items-center justify-center text-sm text-ink-muted">
      Loading FSP data…
    </div>
  );
}

function ErrorPanel({ error }: { error: string }) {
  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-2xl rounded-md border border-status-critical-soft bg-status-critical-soft p-4">
        <div className="text-sm font-semibold text-status-critical">
          Could not load demo data
        </div>
        <pre className="mt-2 whitespace-pre-wrap font-mono text-xs text-ink-muted">
          {error}
        </pre>
      </div>
    </div>
  );
}
