# Bastion FSP — Demo (Vercel deploy)

The Forward Stockout Predictor demo for Project Bastion. This folder is a
**static site** — no build step, no Node, no npm install on Vercel's side.
React + Babel are loaded from CDN, JSX is compiled in the browser, and the
five locked content files in `data/fsp/` are fetched at runtime.

## What's in here

```
fsp-demo/
├── index.html                 # entry: shell + CSS + script tags
├── app.jsx                    # top-level App, scenario selection, layout
├── lib.jsx                    # scenario engine, atoms, MapView
├── tweaks-panel.jsx           # floating dev panel (scenario / day / display toggles)
├── vercel.json                # static config + cache headers
└── data/fsp/
    ├── posts.json             # 15 posts + 4 depots + 3 LoC axes
    ├── routes.json            # 16 strategic + 13 tactical edges
    ├── skus.json              # 30 SKUs across 6 stock heads
    ├── vehicles.json          # 9 vehicle classes
    └── scenarios.json         # 3 scripted scenarios with cascade math
```

## Deploy to Vercel

Two paths depending on your repo layout.

### Option 1 — fresh repo (cleanest)

1. Create a new GitHub repo, e.g. `bastion-fsp-demo`.
2. Drop the contents of this `fsp-demo/` folder into the repo root.
3. Go to https://vercel.com/new, "Import Git Repository", select your repo.
4. **Framework Preset:** Other (or "No framework" — Vercel auto-detects).
5. **Build Command:** leave blank.
6. **Output Directory:** leave blank (Vercel serves the repo root).
7. Click Deploy. Done.

You get a URL like `bastion-fsp-demo.vercel.app` in ~30 seconds.

### Option 2 — drop into your existing `project-bastion` repo

1. Place this entire `fsp-demo/` folder at the root of `project-bastion`.
2. Commit + push.
3. On Vercel, "Import Git Repository", select `project-bastion`.
4. Set **Root Directory** to `fsp-demo`.
5. Framework Preset: Other. Build/Output: blank.
6. Deploy.

This keeps the existing `app/` (Wks 7-8 React/Vite app) untouched, and the
`bastion/` Python ingestion code stays where it is.

## Custom domain (optional, post-deploy)

Vercel → Project → Settings → Domains. Add `silverpotdefence.com` or
`bastion.silverpot.in` once DNS is configured. iDEX submission can use
either the auto-generated `*.vercel.app` URL or a custom domain.

## Local preview

Open `index.html` directly in a browser **won't work** — `fetch()` against
`file://` is blocked by browsers for the JSON files. Use any tiny local
server. Simplest: from inside `fsp-demo/`, use Python:

```
python3 -m http.server 8000
```

Then open `http://localhost:8000`. (This is the only "command" in this
project; everything else is just files.)

## What you'll see

- **Top bar.** Logo, scenario selector, day counter, fleet readiness, global status pill.
- **Left rail.** All 15 posts ranked by status severity.
- **Map.** Hand-drawn AOI illustration (no live tile dependencies — fully self-contained).
  Posts colored by status. Depots as squares. Click a marker to select.
- **Right rail.** Five tabs — Brief, Forecast, Disruptions, Routes, Fleet — driven by
  the selected post or scenario world-state.
- **Bottom dock.** Timeline scrubber across the 90-day window with disruption-event
  ticks. Drag to scrub.
- **Tweaks panel (top-right).** Floating dev overlay — change scenario, day, toggles.

Three scenarios:
1. **Normal ops** — surfaces a latent vehicle-reliability risk on the DBO axis.
2. **Zoji La cascade** — late-October blizzard, Kargil cluster runs out of kerosene.
3. **Vehicle deadline cascade** — three Stallions deadline before the DBO surge convoy.

## Data freshness

`data/fsp/*.json` are the locked Wk6 demo content files. Edit them in this
folder and commit; Vercel will redeploy and the live demo updates within
~30 seconds. Cache headers in `vercel.json` keep the JSON cache short
(60 seconds) so changes propagate fast.

## Troubleshooting

- **Blank page on first load.** Check the browser console. If it's "failed
  to fetch posts.json", the file paths are off — verify `data/fsp/` is at
  the same level as `index.html`.
- **CSP errors blocking `unsafe-eval`.** Some hosts inject a strict CSP
  that breaks Babel-standalone. Vercel doesn't by default, but if you put
  this behind Cloudflare or another proxy with strict CSP, you'll need to
  whitelist `'unsafe-eval'` for the Babel transform to run.
- **Fonts missing.** The HTML preconnects to Google Fonts. If your
  network blocks Google Fonts, the page falls back to system fonts —
  layout still works, just looks slightly different.
