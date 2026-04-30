# Bastion FSP — Demo App

Forward Stockout Predictor demo for Project Bastion. Reads the locked FSP
content from `data/fsp/*.json` (single source of truth at repo root) and
renders an interactive web app deployed to Vercel.

> See `BASTION_MASTERPLAN_v2.md` Part 5 (Phase 1, Wks 5–16) for full context.
> See `data/fsp/methodology.md` for the provenance and scope discipline.

## Status

**Wk8 of 12 (Path C).** Scenario engine + timeline scrubber. Three scenarios
walkable end-to-end. Status colors flip on the right days. Disruption events
fire on day-of. Closed strategic-axis routes render as red dashed polylines.
Click a post to see its current snapshot in the sidebar.

**Wk9 next:** resupply-options card, provenance click-through panel, SITREP
markdown export stub.

## Stack

- React 18 + TypeScript (strict)
- Vite (dev server + build)
- Tailwind CSS (light enterprise theme — no dark HUD, no defense-tech aesthetic)
- MapLibre GL JS (no Mapbox token, no auth surface)
- Inter font (Google Fonts; localized in Wk13)

The basemap is currently MapLibre's hosted demo tiles. The Wk13 design pass
should replace this with a self-hosted PMTiles file clipped to the AOI bbox.

## Folder structure

```
app/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js          # light SaaS palette + Inter
├── postcss.config.js
├── index.html
├── vercel.json                 # SPA rewrites + cache headers
├── public/
│   └── data/                   # synced from /data/fsp/ at build time
├── scripts/
│   └── sync-fsp-data.mjs       # copy script
└── src/
    ├── main.tsx                # React entry
    ├── App.tsx                 # top-level layout, header, loaded/error states
    ├── index.css               # Tailwind + MapLibre overrides
    ├── types/
    │   ├── posts.ts
    │   ├── routes.ts
    │   ├── skus.ts
    │   ├── vehicles.ts
    │   ├── scenarios.ts
    │   └── index.ts
    ├── hooks/
    │   ├── useFspData.ts       # loads + validates all 5 files
    │   └── useScenarioState.ts # selected scenario + day; derives world-state    [Wk8]
    ├── lib/                                                                       [Wk8]
    │   ├── consumption.ts      # kerosene burn math, terrain class lookup
    │   ├── statusDerivation.ts # days-to-stockout → status mapping
    │   └── scenarioEngine.ts   # daily simulation, world-state per (scenario, day)
    └── components/
        ├── MapView.tsx         # MapLibre canvas + status-colored markers + closed routes
        ├── Sidebar.tsx         # scenario controls + post list + detail panel    [Wk8]
        ├── ScenarioSelector.tsx                                                   [Wk8]
        ├── TimelineScrubber.tsx                                                   [Wk8]
        ├── DisruptionBanner.tsx                                                   [Wk8]
        ├── PostDetailPanel.tsx                                                    [Wk8]
        └── StatusPill.tsx      # reusable status indicator + STATUS_HEX export   [Wk8]
```

## Scenario engine — how it works

`lib/scenarioEngine.ts` exposes `computeWorldState(scenario, day, posts, skus)`
which returns a `ScenarioWorldState` snapshot for any (scenario, day) pair.

The engine **anchors to the `key_projection_days` values authored in
`scenarios.json`** when one exists for the requested day. Between anchors it
linearly interpolates stocks, using the daily burn formula in
`lib/consumption.ts` (mirrors the calc strings in scenarios.json).

This means:
- Day 5 of S2 (an authored anchor) shows exactly what `scenarios.json` says.
- Day 6 of S2 shows a coherent interpolation between Day 5 and Day 12.
- Day 12 of S2 shows exactly what the file says again.
- An advisor can scrub to any day and see plausible numbers.

The Wk9 provenance UI will surface "this number came from the authored anchor
at Day N" vs "this number was interpolated" so reviewers can audit the path.

## Design language

Light. Boring. Conservative. The palette is slate grays + a single blue
accent + four desaturated status colors (green/yellow/red). Inter font.
No glow, no gradients, no dark mode.

The intent is that a Brigadier's staff officer reviewing the demo feels
they've used a tool like this before — Linear, Notion, a Govt of India
dashboard. Not Palantir, not a Hollywood war room. The credibility comes
from the data discipline and provenance UI, not from the chrome.

(Lighthouse, the sister product, retains the dark HUD aesthetic. Bastion
deliberately doesn't.)

## Wk8 deferred items (handled in later weeks)

- **Wk9** — Resupply options card with three options per active alert,
  provenance click-through showing the lineage from any number back to its
  source data file, SITREP markdown export (stub formatting; final polish Wk14).
- **Wk13** — Design polish, self-hosted PMTiles basemap, hex-binning of
  posts by status (only if it adds clarity), localized Inter font, tactical
  edge polylines (currently only strategic-axis closures render as lines).
- **Wk14** — Provenance UI proper (the "click any number, see its source"
  feature that's the Palantir-grade differentiator).
- **Wk15** — Unscripted what-if mode (operator injects arbitrary disruptions
  beyond the three scripted scenarios; live re-simulation).
- **Wk16** — Polish, recorded Loom walkthrough, Vercel production deploy.
