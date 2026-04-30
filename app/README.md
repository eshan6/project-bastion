# Bastion FSP — Demo App

Forward Stockout Predictor demo for Project Bastion. Reads the locked FSP
content from `data/fsp/*.json` (single source of truth at repo root) and
renders an interactive web app deployed to Vercel.

> See `BASTION_MASTERPLAN_v2.md` Part 5 (Phase 1, Wks 5–16) for full context.
> See `data/fsp/methodology.md` for the provenance and scope discipline.

## Status

Wk7 of 12 (Path C). App skeleton + data wiring. Map renders posts and
depots from the locked content files. No time-varying state yet — that
arrives in Wk8 (timeline scrubber, scenario selector, status colors).

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
│   └── sync-fsp-data.mjs       # copy script (see below)
└── src/
    ├── main.tsx                # React entry
    ├── App.tsx                 # top-level layout
    ├── index.css               # Tailwind + MapLibre overrides
    ├── types/
    │   ├── posts.ts
    │   ├── routes.ts
    │   ├── skus.ts
    │   ├── vehicles.ts
    │   ├── scenarios.ts
    │   └── index.ts
    ├── hooks/
    │   └── useFspData.ts       # loads + validates all 5 files
    └── components/
        └── MapView.tsx         # MapLibre canvas + markers
```

## Data flow

1. `data/fsp/*.json` (repo root) is the **single source of truth**.
2. `scripts/sync-fsp-data.mjs` copies those files into `app/public/data/`
   on every `npm run dev` and `npm run build` (via npm pre-hooks).
3. `useFspData()` fetches them at runtime from `/data/posts.json` etc.
4. Validation: the hook asserts the locked counts (15 posts, 4 depots,
   3 LoCs, 30 SKUs, 9 vehicles, 3 scenarios) and fails loud if violated.

**Never edit files in `app/public/data/` directly** — they're overwritten
on the next build. Edit `data/fsp/*.json` at the repo root.

**Why copy instead of bundling JSON into JS:** the demo's provenance story
depends on users being able to inspect the raw data files. Serving them as
static assets at predictable URLs (`/data/posts.json`) makes that possible.
A user clicking a number in the UI can be linked to the file it came from.

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

## Wk7 deferred items (handled in later weeks)

- **Wk8** — Scenario engine, timeline scrubber, status-colored markers,
  drill-down panels, route segment polylines.
- **Wk9** — Resupply options card, provenance click-through, SITREP export
  stub.
- **Wk13** — Design polish, self-hosted PMTiles basemap, hex-binning of
  posts by status (if it improves clarity), localized Inter font.
- **Wk14** — Provenance UI proper (the "click any number, see its source"
  feature that's the Palantir-grade differentiator).
- **Wk15** — Unscripted what-if mode (operator injects arbitrary disruptions).
- **Wk16** — Polish, Loom walkthrough, Vercel production deploy.
