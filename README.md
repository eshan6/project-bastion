# Project Bastion — Ops UI (v3 mock)

Internal operations console for Project Bastion's v3 substrate — the Forward Stockout Predictor for Indian Army high-altitude logistics. Static React + Babel SPA, no build step.

## What's in here

- `index.html` — entry point
- `styles.css` — design tokens + components
- `data.js` — canonical 2024-12-15 snapshot (synthetic, mirrors the real `stage3_models/output/snapshot_2024-12-15/`)
- `components.jsx` — shared UI primitives (pills, cards, tags, gauge, header, rail, lineage drawer)
- `map.jsx` — Eastern Ladakh stylized topo SVG
- `screens-ops.jsx` — Overview · Alerts · Plans · Risk inspector
- `screens-sys.jsx` — Posts & routes · Vehicles · Models · Snapshots · Sources
- `app.jsx` — router + shell
- `vercel.json` — static-site config

## Deploy to Vercel

```bash
npm i -g vercel
vercel
```

Or drop the folder into the Vercel dashboard ("New Project" → import directly). No framework preset needed — it's a plain static site. Output directory is the repo root.

## Data lineage (what the UI surfaces)

```
alert ──→ stockout_risk ──→ demand_forecast ──→ model_version ──→ data_snapshot
              ╲      ╲       route_prediction   (stage3-v1.0)     (seed=42, frozen)
               ╲      ╲      vehicle_reliability
                ↓      ↓
              isolation_probability (∏ P(pass closed))
              + current stock + per-capita burn
```

The lineage drawer (click any alert) walks all five hops. Every value is sourced from a real artifact in the v3 repo; numbers come from `stage3_models/reports/evaluation_report.md` and `stage4_planning/README.md` findings.

## Honest disclosures the UI surfaces

- **Demand forecast** — weighted MAPE 29.4% vs masterplan target <20%. MAE/median 0.14–0.25 across forward SKUs is the more honest framing.
- **Route availability** — Brier 0.06–0.14 (headline); AUC 0.63–0.83 (unstable on sparse closure days).
- **Vehicle reliability** — Brier skill ≈ 0. Rule-based scorer is documented as a hot-swappable slot; no information beyond unconditional rate.
- **Optimizer** — 31.7% best achievable road coverage. 15 of 30 at-risk posts are road-isolated. The optimizer surfaces shortfall explicitly rather than failing silently.
