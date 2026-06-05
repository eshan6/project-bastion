// Project Bastion — shared UI components.
// All names global on window so other Babel scripts can use them.

const { useState, useEffect, useMemo, useRef } = React;

// ─────────────────────────────────────────────── Icons (small inline)
const Icon = ({ d, size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    {Array.isArray(d) ? d.map((dd, i) => <path key={i} d={dd} />) : <path d={d} />}
  </svg>
);
const Icons = {
  overview:   "M3 3h7v7H3zM14 3h7v7h-7zM14 14h7v7h-7zM3 14h7v7H3z",
  alert:      "M12 9v4M12 17h.01M10.29 3.86l-8.39 14.5A2 2 0 0 0 3.61 21h16.78a2 2 0 0 0 1.71-3.05L13.71 3.86a2 2 0 0 0-3.42 0Z",
  plans:      ["M3 7h18M3 12h18M3 17h18","M8 4v3M16 4v3M8 13v3M16 13v3"],
  risk:       "M9 11l3 3l8-8M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
  map:        ["M1 6v15l7-3 8 3 7-3V3l-7 3-8-3-7 3z","M8 3v15M16 6v15"],
  vehicles:   ["M5 17h-2v-6l2-5h9l4 5h2v6h-2","M5 17a2 2 0 1 0 4 0","M15 17a2 2 0 1 0 4 0"],
  models:     "M12 2v20M5 6l14 12M19 6L5 18",
  snapshots:  "M3 3v18h18M7 14l4-4 4 4 5-5",
  source:     ["M21 12c0 1.66-4 3-9 3s-9-1.34-9-3","M3 5c0-1.66 4-3 9-3s9 1.34 9 3v14c0 1.66-4 3-9 3s-9-1.34-9-3Z","M3 12V5"],
  chevron:    "M6 9l6 6 6-6",
  chevronR:   "M9 18l6-6-6-6",
  close:      "M18 6L6 18M6 6l12 12",
  search:     ["M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16Z","M21 21l-4.35-4.35"],
  refresh:    ["M3 12a9 9 0 1 0 3-6.7","M3 4v5h5"],
  filter:     "M3 6h18M6 12h12M10 18h4",
  external:   ["M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6","M15 3h6v6","M10 14 21 3"],
  bell:       ["M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9","M13.73 21a2 2 0 0 1-3.46 0"],
  cog:        ["M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Z","M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"],
  info:       ["M12 22c5.523 0 10-4.477 10-10S17.523 2 12 2 2 6.477 2 12s4.477 10 10 10Z","M12 16v-4M12 8h.01"],
  check:      "M20 6L9 17l-5-5",
  zap:        "M13 2L3 14h9l-1 8 10-12h-9l1-8z",
  cloud:      "M16 18a4 4 0 0 0 0-8c-.65 0-1.27.13-1.83.36A6 6 0 0 0 3 16a4 4 0 0 0 4 4h9z",
};

// ─────────────────────────────────────────────── Status pill
function Pill({ tone = "info", children }) {
  return (
    <span className={`pill ${tone}`}>
      <span className="dot" />{children}
    </span>
  );
}

// Stockout-status semantic (ok/rationing/stockout)
function StatusPill({ status }) {
  const map = { ok: ["ok", "OK"], rationing: ["warn", "Rationing"], stockout: ["crit", "Stockout"] };
  const [tone, label] = map[status] || ["info", status];
  return <Pill tone={tone}>{label}</Pill>;
}

// Severity pill
function SeverityBadge({ severity }) {
  const map = { critical: ["crit", "Critical"], warning: ["warn", "Warning"], info: ["info", "Info"] };
  const [tone, label] = map[severity] || ["info", severity];
  return <Pill tone={tone}>{label}</Pill>;
}

// Provenance grade chip
function Grade({ grade }) {
  return <span className={`grade ${grade}`}>{grade}</span>;
}

// Tag (monospace label)
function Tag({ tone = "default", children, title }) {
  return <span className={`tag ${tone === "default" ? "" : tone}`} title={title}>{children}</span>;
}

// ─────────────────────────────────────────────── Stat card
function Stat({ label, value, unit, sub, delta, tone, icon }) {
  return (
    <div className={`stat ${tone === "critical" ? "critical" : ""}`}>
      <div className="stat-label">
        {icon && <Icon d={icon} size={12} />}
        <span>{label}</span>
      </div>
      <div className="stat-value">
        {value}{unit && <span className="unit"> {unit}</span>}
      </div>
      {delta && <div className={`stat-delta ${delta.tone || "flat"}`}>{delta.text}</div>}
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────── Card
function Card({ title, count, sub, actions, children, padded = true }) {
  return (
    <div className="card">
      {(title || actions) && (
        <div className="card-head">
          <div className="card-title">
            {title}
            {count != null && <span className="count">({count.toLocaleString()})</span>}
          </div>
          <div className="card-actions">{actions}</div>
        </div>
      )}
      {sub && <div className="card-sub">{sub}</div>}
      <div className={padded ? "card-body" : "card-body flush"}>{children}</div>
    </div>
  );
}

// ─────────────────────────────────────────────── Segmented control
function Segmented({ value, onChange, options }) {
  return (
    <div className="segmented">
      {options.map((o) => (
        <button
          key={o.value}
          className={o.value === value ? "active" : ""}
          onClick={() => onChange(o.value)}
          type="button"
        >
          {o.label}{o.count != null && <span style={{ marginLeft: 4, opacity: 0.6 }}>{o.count}</span>}
        </button>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────── Search input
function Search({ value, onChange, placeholder = "Search…" }) {
  return (
    <div className="search-input">
      <Icon d={Icons.search} size={13} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </div>
  );
}

// ─────────────────────────────────────────────── Bar (for table cells)
function Bar({ value, max, tone }) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <span className={`bar ${tone || ""}`} title={`${value} / ${max}`}>
      <i style={{ width: `${pct}%` }} />
    </span>
  );
}

// ─────────────────────────────────────────────── Half-circle gauge
function Gauge({ value, label, sub, tone = "crit" }) {
  // value 0..100
  const v = Math.max(0, Math.min(100, value));
  const r = 38;
  const cx = 50, cy = 50;
  const a0 = Math.PI, a1 = 0; // half circle from left to right
  const startA = a0, endA = a0 - (v / 100) * Math.PI;
  const x1 = cx + r * Math.cos(startA), y1 = cy + r * Math.sin(startA);
  const x2 = cx + r * Math.cos(endA),   y2 = cy + r * Math.sin(endA);
  const largeArc = v > 50 ? 1 : 0;
  const color = tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--accent)";
  return (
    <div className="card-body" style={{ padding: 0 }}>
      <div className="gauge">
        <svg width="200" height="110" viewBox="0 0 100 60">
          {/* Track */}
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`}
            fill="none" stroke="var(--surface-alt)" strokeWidth="8" strokeLinecap="round"
          />
          {/* Fill */}
          {v > 0 && (
            <path
              d={`M ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2}`}
              fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
            />
          )}
        </svg>
        <div className="gauge-num">
          {v.toFixed(1)}<span className="unit">%</span>
        </div>
      </div>
      <div className="gauge-sub">{label}</div>
      {sub && <div className="gauge-sub" style={{ color: "var(--ink-faint)" }}>{sub}</div>}
    </div>
  );
}

// ─────────────────────────────────────────────── Header
function Header({ snapshot, onSnapshotClick, alertTotal, onReplan, dayOffset, day, onAdvance, onRetreat, onReset }) {
  const [tickOpen, setTickOpen] = useState(false);
  const dateLabel = day ? day.date : snapshot.as_of_date;
  const offsetLabel = dayOffset === 0
    ? "canonical"
    : dayOffset > 0 ? `+${dayOffset}d` : `${dayOffset}d`;
  return (
    <header className="header">
      <div className="header-left">
        <div className="brand">
          <div className="brand-mark">B</div>
          <div className="brand-text">
            <div className="brand-name">Bastion</div>
            <div className="brand-tag">/ ops — internal</div>
          </div>
        </div>

        <button className="snapshot-picker" onClick={onSnapshotClick}>
          <span className="sp-label">As of</span>
          <span className="sp-date">{dateLabel}</span>
          <span style={{ color: "var(--ink-faint)" }}>·</span>
          <span className="sp-label">seed</span>
          <span className="sp-date">{snapshot.seed}</span>
          {dayOffset !== 0 && <span className="sp-offset">{offsetLabel}</span>}
          <Icon d={Icons.chevron} size={12} />
        </button>

        <div className="day-stepper" role="group" aria-label="Day stepper">
          <button className="ds-btn" type="button" onClick={onRetreat} title="Step back one day (rewind tick)">‹</button>
          <button className="ds-btn ds-today" type="button" onClick={onReset} title="Snap to canonical (today)" disabled={dayOffset === 0}>
            Today
          </button>
          <button className="ds-btn" type="button" onClick={onAdvance} title="Step forward one day (manual tick)">›</button>
        </div>

        <span className="meta-chip"><b>stage3</b> v1.0</span>
        <span className="meta-chip"><b>stage4</b> v1.0</span>
        <span className="meta-chip live"><b>{alertTotal}</b> open alerts</span>
      </div>

      <div className="header-right">
        <div className="tick-wrap">
          <button className="btn ghost sm" type="button" onClick={() => setTickOpen((v) => !v)}>
            <Icon d={Icons.refresh} size={12} />
            How ticks work
          </button>
          {tickOpen && (
            <div className="tick-pop">
              <div className="tp-eyebrow">Daily tick</div>
              <div style={{ marginBottom: 8 }}>
                In production: runs <b>automatically once per day</b> via Supabase cron / GitHub Actions. The dashboard always shows the latest tick.
                In this build: use the <b>‹ Today ›</b> stepper above to manually advance or rewind a tick. Each step replays the full pipeline against a synthetic-world day.
              </div>
              <div className="tp-eyebrow">Steps per tick</div>
              <div className="tp-step"><span className="num">1</span><span>Generator advances world by 1 day</span></div>
              <div className="tp-step"><span className="num">2</span><span>Demand forecasts re-run (P10/P50/P90)</span></div>
              <div className="tp-step"><span className="num">3</span><span>Route-availability classifier re-runs</span></div>
              <div className="tp-step"><span className="num">4</span><span>Vehicle reliability scores update</span></div>
              <div className="tp-step"><span className="num">5</span><span>Risk evaluator composes <code>stockout_risk</code></span></div>
              <div className="tp-step"><span className="num">6–7</span><span>Disruption + vehicle alerts emitted</span></div>
              <div className="tp-step manual"><span className="num">8</span><span><b style={{ color: "var(--accent)" }}>Optimizer is manual</b> — click <i>Replan now</i> to emit fresh plans.</span></div>
              <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid var(--line)", fontSize: 11, color: "var(--ink-faint)" }}>
                Per masterplan v3 §4 settled decision #5: batch with manual replan trigger. No live event streams.
              </div>
            </div>
          )}
        </div>
        <button className="btn primary" type="button" onClick={onReplan}>
          <Icon d={Icons.zap} size={12} />
          Replan now
        </button>
        <button className="icon-btn" title="Notifications" type="button">
          <Icon d={Icons.bell} size={14} />
        </button>
        <button className="icon-btn" title="Settings" type="button">
          <Icon d={Icons.cog} size={14} />
        </button>
        <div className="avatar">EG</div>
      </div>
    </header>
  );
}

// Banner shown under header when offset ≠ 0, explaining replay mode.
function ReplayBanner({ dayOffset, day, onReset }) {
  if (dayOffset === 0) return null;
  const sign = dayOffset > 0 ? "+" : "";
  return (
    <div className="replay-banner">
      <div className="rb-left">
        <span className="rb-tag">REPLAY MODE</span>
        <span>You're {dayOffset > 0 ? "projecting forward" : "rewinding back"} <b>{sign}{dayOffset}</b> day{Math.abs(dayOffset) === 1 ? "" : "s"} from canonical. Showing simulated tick state for <b>{day.date}</b>.</span>
      </div>
      <button className="btn sm" type="button" onClick={onReset}>Return to today</button>
    </div>
  );
}

// ─────────────────────────────────────────────── Left rail nav
function LeftRail({ route, onRoute, counts }) {
  const items = [
    { id: "overview",  icon: Icons.overview,  label: "Overview" },
    { id: "alerts",    icon: Icons.alert,     label: "Alerts", badge: counts.alerts, badgeTone: "crit" },
    { id: "plans",     icon: Icons.plans,     label: "Resupply plans", badge: counts.plans },
    { id: "risk",      icon: Icons.risk,      label: "Risk inspector", badge: counts.risk },
    { id: "map",       icon: Icons.map,       label: "Posts & routes" },
    { id: "vehicles",  icon: Icons.vehicles,  label: "Vehicles", badge: counts.vehicles },
  ];
  const items2 = [
    { id: "models",    icon: Icons.models,    label: "Models & eval" },
    { id: "snapshots", icon: Icons.snapshots, label: "Snapshots", badge: counts.snapshots },
    { id: "sources",   icon: Icons.source,    label: "Sources" },
  ];

  const renderItem = (it) => (
    <button
      key={it.id}
      className={`rail-item ${route === it.id ? "active" : ""}`}
      onClick={() => onRoute(it.id)}
      type="button"
    >
      <Icon d={it.icon} size={14} />
      <span>{it.label}</span>
      {it.badge != null && (
        <span className={`badge ${it.badgeTone || ""}`}>{it.badge.toLocaleString()}</span>
      )}
    </button>
  );

  return (
    <nav className="rail">
      <div className="rail-section">
        <div className="rail-eyebrow">Operations</div>
        {items.map(renderItem)}
      </div>
      <div className="rail-section">
        <div className="rail-eyebrow">System</div>
        {items2.map(renderItem)}
      </div>
      <div className="rail-footer">
        <div>Build-phase mock · synthetic data</div>
        <div className="small-tag mt-2">seed=42 · git 13645ff</div>
        <div className="mt-2" style={{ color: "var(--ink-faint)" }}>Per masterplan v3 §6 stage 5.</div>
      </div>
    </nav>
  );
}

// ─────────────────────────────────────────────── Page chrome
function Page({ eyebrow, title, sub, actions, children }) {
  return (
    <div className="page">
      <div className="page-inner">
        <div className="page-head">
          <div className="page-head-left">
            {eyebrow && <div className="page-eyebrow">{eyebrow}</div>}
            <div className="page-title">{title}</div>
            {sub && <div className="page-sub">{sub}</div>}
          </div>
          {actions && <div className="page-actions">{actions}</div>}
        </div>
        {children}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────── Callout
function Callout({ tone = "info", icon, title, children, actions }) {
  const iconD = icon || (tone === "crit" ? Icons.alert : tone === "warn" ? Icons.alert : Icons.info);
  return (
    <div className={`callout ${tone}`}>
      <div className="callout-icon"><Icon d={iconD} size={16} /></div>
      <div style={{ flex: 1 }}>
        <div className="callout-title">{title}</div>
        <div className="callout-body">{children}</div>
        {actions && <div className="callout-actions">{actions}</div>}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────── Lineage drawer
function LineageDrawer({ open, kind, payload, onClose }) {
  if (!open) return null;

  const nodes = buildLineageNodes(kind, payload);

  return (
    <aside className="lineage-drawer">
      <div className="drawer-head">
        <div>
          <div className="drawer-eyebrow">Lineage · alert → risk → forecast → model → snapshot</div>
          <div className="drawer-title">{nodes[0]?.headline || "Trace"}</div>
          <div className="drawer-sub">{nodes[0]?.sub}</div>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close" type="button">
          <Icon d={Icons.close} size={13} />
        </button>
      </div>
      <div className="drawer-body">
        {nodes.map((n, i) => (
          <div key={i} className="lineage-node">
            <div className="lineage-node-head">
              <span className="lineage-step">{n.step}</span>
              <span className="lineage-kind">{n.kind}</span>
            </div>
            <div className="lineage-kv">
              {n.fields.map(([k, v]) => (
                <React.Fragment key={k}>
                  <div className="k">{k}</div>
                  <div className="v">{v}</div>
                </React.Fragment>
              ))}
            </div>
            {n.note && <div className="mt-2" style={{ fontSize: 11.5, color: "var(--ink-muted)", lineHeight: 1.5 }}>{n.note}</div>}
          </div>
        ))}
        <div className="mt-3" style={{ fontSize: 11, color: "var(--ink-faint)", lineHeight: 1.55 }}>
          All five hops persist in <code>bastion.v_prediction_lineage</code>. Re-running training writes the same trees; every prediction row carries <code>model_version</code>, <code>snapshot_date</code>, <code>generated_at</code>, <code>data_snapshot_seed</code>.
        </div>
      </div>
    </aside>
  );
}

// Build the lineage trace for a given source row.
function buildLineageNodes(kind, payload) {
  const B = window.B;
  const snap = B.snapshot;
  const out = [];

  if (kind === "alert") {
    const a = payload;
    out.push({
      step: "01 · alert",
      kind: a.alert_type,
      headline: a.message.split(":")[0],
      sub: a.message,
      fields: [
        ["alert_id",         a.alert_id],
        ["alert_type",       a.alert_type],
        ["severity",         a.severity],
        ["trigger_metric",   a.trigger_metric],
        ["trigger_value",    String(a.trigger_value)],
        ["created_at",       a.created_at],
        ["acknowledged",     "false"],
      ],
    });
    // Source — risk OR route OR vehicle
    if (a.alert_type === "stockout_risk" && a.source_risk_id) {
      const r = B.stockout_risk.find((x) => x.risk_id === a.source_risk_id);
      if (r) {
        out.push({
          step: "02 · stockout_risk",
          kind: `composed risk @ horizon ${r.horizon_days}d`,
          fields: [
            ["risk_id",                       r.risk_id],
            ["post_id / sku_id",              `${r.post_id} / ${r.sku}`],
            ["head / tier",                   `${r.head} / Tier ${r.tier}`],
            ["current_stock",                 r.current_stock.toLocaleString()],
            ["current_days_of_cover",         r.current_days_of_cover.toFixed(1)],
            ["projected_days_of_cover_p50",   r.projected_days_of_cover_p50.toFixed(2)],
            ["projected_days_of_cover_p90",   r.projected_days_of_cover_p90.toFixed(2)],
            ["isolation_probability",         r.isolation_probability.toFixed(3)],
            ["predicted_status",              r.predicted_status],
            ["predicted_status_worstcase",    r.predicted_status_worstcase],
            ["tier_alert_fired",              String(r.tier_alert_fired)],
          ],
        });
        out.push({
          step: "03 · demand_forecast",
          kind: "P10 / P50 / P90 weekly",
          fields: [
            ["forecast slice",   `band=${B.posts.find(p=>p.post_id===r.post_id)?.band} / head=${r.head}`],
            ["p10 / p50 / p90",  `${r.p10} / ${r.p50} / ${r.p90}`],
            ["target_week",      "2024-12-16"],
            ["calibration",      "conformal additive offset (per slice)"],
            ["sku_id (feature)", r.sku],
          ],
        });
      }
    } else if (a.alert_type === "disruption" && a.pass_name) {
      const ps = B.route_predictions.filter((x) => x.pass_name === a.pass_name);
      const wp = ps.reduce((m, x) => (m.p_closed > x.p_closed ? m : x), ps[0]);
      out.push({
        step: "02 · route_prediction",
        kind: `binary GBM (pass × horizon)`,
        fields: [
          ["pass_name",     a.pass_name],
          ["target_date",   wp.date],
          ["horizon_days",  String(wp.horizon)],
          ["p_open",        wp.p_open.toFixed(3)],
          ["p_closed",      wp.p_closed.toFixed(3)],
          ["threshold",     "P(closed) > 0.60 (masterplan)"],
        ],
        note: "Posts beyond this pass compound P(closed) along the leg's pass chain. Independence assumption is conservative — under-predicts cascades.",
      });
    } else if (a.alert_type === "vehicle_deadline" && a.vehicle_id) {
      const v = B.vehicles.find((x) => x.vehicle_id === a.vehicle_id);
      out.push({
        step: "02 · vehicle_reliability",
        kind: `rule-based Weibull survival`,
        fields: [
          ["vehicle_id",            v.vehicle_id],
          ["vehicle_class",         v.class_id],
          ["home_depot_id",         v.home_depot_id],
          ["effective_age_days",    v.effective_age_days.toLocaleString()],
          ["events_to_date",        String(v.events_to_date)],
          ["p_deadline (7d)",       v.p_deadline.toFixed(4)],
          ["reliability_score",     v.reliability_score.toFixed(4)],
          ["threshold",             "P(deadline) > 0.05 (SYNTHETIC-INFERRED)"],
        ],
        note: "Scorer Brier skill ≈ 0 by design. The rule contains no information beyond the unconditional rate — the slot is hot-swappable when real altitude/breakdown data arrives.",
      });
    }
    // Model + snapshot tail (always)
    const m = (
      a.alert_type === "stockout_risk" ? B.models.find((x) => x.kind === "risk_evaluator") :
      a.alert_type === "disruption"    ? B.models.find((x) => x.kind === "route_availability") :
                                         B.models.find((x) => x.kind === "vehicle_reliability")
    );
    out.push({
      step: "04 · model_version",
      kind: `${m.kind} · ${m.name}`,
      fields: [
        ["algorithm",       m.algorithm],
        ["trained_at",      m.trained_at],
        ["git_sha",         m.git_sha],
        ["slices",          String(m.slices)],
        ["artifacts",       String(m.artifacts)],
      ],
    });
    out.push({
      step: "05 · data_snapshot",
      kind: "Stage 2 world (frozen)",
      fields: [
        ["snapshot_id",         snap.snapshot_id],
        ["label",               snap.label],
        ["seed",                String(snap.seed)],
        ["as_of_date",          snap.as_of_date],
        ["generator_version",   snap.generator_version],
        ["row_counts.posts",    snap.row_counts.posts.toLocaleString()],
        ["row_counts.stocks",   snap.row_counts.stock_level.toLocaleString()],
        ["row_counts.consumption", snap.row_counts.consumption_event.toLocaleString()],
      ],
      note: "Re-running generator with seed=42 produces byte-identical output. The lineage chain stops here.",
    });
  }

  return out;
}

// ─────────────────────────────────────────────── Helpers
function fmtInt(n)   { return n == null ? "—" : Math.round(n).toLocaleString(); }
function fmtPct(n)   { return n == null ? "—" : `${(n * 100).toFixed(1)}%`; }
function fmtPctI(n)  { return n == null ? "—" : `${(n * 100).toFixed(0)}%`; }
function fmtCur(n)   { return n == null ? "—" : `₹${Math.round(n).toLocaleString()}`; }
function fmtHours(n) { return n == null ? "—" : `${n.toFixed(1)}h`; }
function fmtFloat(n, d = 2) { return n == null ? "—" : n.toFixed(d); }

// Export to window
Object.assign(window, {
  Icon, Icons,
  Pill, StatusPill, SeverityBadge, Grade, Tag,
  Stat, Card, Segmented, Search, Bar, Gauge,
  Header, ReplayBanner, LeftRail, Page, Callout, LineageDrawer,
  fmtInt, fmtPct, fmtPctI, fmtCur, fmtHours, fmtFloat,
});
