// Bastion FSP v2 — engine, atoms, and map.
// Exports go on `window` so the second babel script can use them.

const { useState, useMemo, useEffect, useRef } = React;

// =====================================================================
// Status math
// =====================================================================
const STATUS_PRIORITY = { ok: 0, watch: 1, critical: 2, imminent: 3 };
const STATUS_HEX = { ok: "#16a34a", watch: "#ca8a04", critical: "#dc2626", imminent: "#991b1b" };
const STATUS_BG  = { ok: "#f0fdf4", watch: "#fefce8", critical: "#fef2f2", imminent: "#fee2e2" };
const STATUS_LABEL = { ok: "OK", watch: "Watch", critical: "Critical", imminent: "Imminent" };
function statusFromDays(d) { if (d >= 30) return "ok"; if (d >= 15) return "watch"; if (d >= 5) return "critical"; return "imminent"; }
function normStatus(s) { return s === "critical_for_winter_readiness" ? "critical" : s; }
function worse(a, b) { return STATUS_PRIORITY[a] >= STATUS_PRIORITY[b] ? a : b; }
function parseDayKey(k) { const m = k.match(/^day_(\d+)/); return m ? parseInt(m[1], 10) : null; }

// =====================================================================
// Scenario engine — anchor + linear interpolation
// =====================================================================
function simulateSinglePost(scenario, day) {
  const fp = scenario.focal_post_projection;
  if (!fp) return null;
  const anchors = Object.entries(fp.key_projection_days)
    .map(([k, v]) => ({ d: parseDayKey(k), pd: v })).filter(a => a.d !== null)
    .sort((a, b) => a.d - b.d);
  if (!anchors.length) return null;
  const exact = anchors.find(a => a.d === day);
  const burn = fp.kerosene_daily_burn_L || (fp.kerosene_burn_phases ? (day < 30 ? fp.kerosene_burn_phases.summer_days_0_29.daily_burn_L : fp.kerosene_burn_phases.winter_days_30_plus.daily_burn_L) : 360);
  if (exact) {
    const dts = exact.pd.days_to_stockout_at_current_burn ?? exact.pd.days_to_stockout_summer_burn ?? exact.pd.days_to_stockout_winter_burn ?? exact.pd.days_to_winter_stockout_actual ?? null;
    return { post_id: fp.post_id, kerosene_stock_L: exact.pd.kerosene_stock_L ?? exact.pd.kerosene_stock_L_actual ?? null,
      days_to_stockout: dts, status: normStatus(exact.pd.status), daily_burn_L: burn, note: exact.pd.note, is_anchor_day: true };
  }
  const before = [...anchors].reverse().find(a => a.d < day);
  const after = anchors.find(a => a.d > day);
  let stock = null;
  const stockOf = (pd) => pd.kerosene_stock_L ?? pd.kerosene_stock_L_actual;
  if (before && after) {
    const bs = stockOf(before.pd), as = stockOf(after.pd);
    if (bs != null && as != null) { const t = (day - before.d) / (after.d - before.d); stock = bs + t * (as - bs); }
  } else if (before) {
    const bs = stockOf(before.pd); if (bs != null) stock = Math.max(0, bs - burn * (day - before.d));
  }
  const dts = stock != null && burn > 0 ? Math.floor(stock / burn) : null;
  return { post_id: fp.post_id, kerosene_stock_L: stock != null ? Math.round(stock) : null,
    days_to_stockout: dts, status: dts != null ? statusFromDays(dts) : "ok", daily_burn_L: burn, is_anchor_day: false };
}
function simulateCluster(scenario, day) {
  const fc = scenario.focal_cluster_projection;
  if (!fc) return new Map();
  const anchors = Object.entries(fc.key_projection_days).map(([k, v]) => ({ d: parseDayKey(k), pd: v }))
    .filter(a => a.d !== null && a.pd.cluster_stock_L != null).sort((a, b) => a.d - b.d);
  let clusterStock = 0; let authoredPd = null;
  const exact = anchors.find(a => a.d === day);
  if (exact) { clusterStock = exact.pd.cluster_stock_L; authoredPd = exact.pd; }
  else {
    const before = [...anchors].reverse().find(a => a.d < day);
    const after = anchors.find(a => a.d > day);
    if (before && after) { const t = (day - before.d) / (after.d - before.d); clusterStock = before.pd.cluster_stock_L + t * (after.pd.cluster_stock_L - before.pd.cluster_stock_L); }
    else if (before) clusterStock = Math.max(0, before.pd.cluster_stock_L - fc.cluster_burn_total_L_per_day * (day - before.d));
    else if (after) clusterStock = after.pd.cluster_stock_L;
  }
  const total = fc.cluster_burn_total_L_per_day; const out = new Map();
  for (const [postKey, perPost] of Object.entries(fc.daily_burn_L_by_post)) {
    const postId = postKey.split("_")[0];
    const share = perPost.burn_L_per_day / total;
    const stock = clusterStock * share; const burn = perPost.burn_L_per_day;
    const dts = burn > 0 ? Math.floor(stock / burn) : null;
    const status = authoredPd ? normStatus(authoredPd.status) : (dts != null ? statusFromDays(dts) : "ok");
    out.set(postId, { post_id: postId, kerosene_stock_L: Math.round(stock), days_to_stockout: dts,
      status, daily_burn_L: burn, note: authoredPd?.note, is_anchor_day: !!authoredPd });
  }
  return out;
}
function computeWorldState(scenario, day) {
  const clamped = Math.max(0, Math.min(day, scenario.duration_days));
  const active = scenario.disruption_events.filter(e => e.day <= clamped).sort((a, b) => a.day - b.day);
  const todays = active.filter(e => e.day === clamped);
  const closedEdges = new Set();
  for (const ev of active) if (ev.route_impacts) for (const [eid, st] of Object.entries(ev.route_impacts))
    if (eid !== "implication" && typeof st === "string" && st.toLowerCase() === "closed") closedEdges.add(eid);
  const closedLoCs = new Set(scenario.starting_state.closed_routes || []);
  const states = new Map();
  if (scenario.focal_post_projection) { const s = simulateSinglePost(scenario, clamped); if (s) states.set(s.post_id, s); }
  if (scenario.focal_cluster_projection) simulateCluster(scenario, clamped).forEach((v, k) => states.set(k, v));
  let worst = "ok"; states.forEach(s => { worst = worse(worst, s.status); });
  let activeAlert = null;
  if (scenario.resupply_options_at_day_12_alert && clamped >= 12) activeAlert = { trigger_day: 12, card: scenario.resupply_options_at_day_12_alert };
  else if (scenario.resupply_options_at_day_10_alert && clamped >= 10) activeAlert = { trigger_day: 10, card: scenario.resupply_options_at_day_10_alert };
  return { scenario_id: scenario.scenario_id, scenario_title: scenario.title, day: clamped,
    duration_days: scenario.duration_days, post_states: states, global_worst_status: worst,
    active_disruptions: active, todays_disruptions: todays, closed_edge_ids: closedEdges,
    closed_loc_ids: closedLoCs, active_alert: activeAlert };
}

// =====================================================================
// Atoms
// =====================================================================
function StatusPill({ status, size = "md" }) {
  return (
    <span className="status-pill" data-size={size}
      style={{ background: STATUS_BG[status], color: STATUS_HEX[status] }}>
      <span className="status-dot" style={{ background: STATUS_HEX[status] }} />
      {STATUS_LABEL[status]}
    </span>
  );
}
function Sparkline({ values, width = 120, height = 26, status = "ok" }) {
  if (!values || !values.length) return null;
  const min = Math.min(...values), max = Math.max(...values);
  const range = max - min || 1;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 4) - 2;
    return [x, y];
  });
  const d = "M " + pts.map(p => p.join(" ")).join(" L ");
  const last = pts[pts.length - 1];
  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <path d={d} fill="none" stroke={STATUS_HEX[status]} strokeWidth="1.5" />
      <circle cx={last[0]} cy={last[1]} r="2.5" fill={STATUS_HEX[status]} />
    </svg>
  );
}

// =====================================================================
// Map
// =====================================================================
const BBOX = [75.4, 32.5, 79.7, 35.5];
function project(coords, w, h, pad = 12) {
  const [west, south, east, north] = BBOX;
  const x = pad + ((coords[0] - west) / (east - west)) * (w - 2 * pad);
  const y = (h - pad) - ((coords[1] - south) / (north - south)) * (h - 2 * pad);
  return [x, y];
}

// Strategic axes — sourced from routes.json segment endpoints (sequential).
const STRATEGIC_AXES = [
  { loc: "LOC-WEST_ZOJILA", label: "NH-1D Srinagar–Leh", coords: [
    [74.7973, 34.0837], [75.2912, 34.3036], [75.4708, 34.2833],
    [75.7500, 34.4300], [76.1300, 34.5500], [76.8800, 34.3300], [77.5800, 34.1500] ],
    edges: ["EDGE-ZOJI-LEH", "EDGE-ZOJI-KARGIL"] },
  { loc: "LOC-SOUTH_MANALI", label: "NH-3 Manali–Leh", coords: [
    [77.1734, 32.2396], [77.3700, 32.4700], [77.4000, 32.9200],
    [77.4300, 33.1500], [77.5500, 33.4000], [77.5800, 34.1500] ],
    edges: ["EDGE-MANALI-LEH"] },
  { loc: "LOC-LEH-KARGIL-INTERNAL", label: "Leh–Kargil arterial", coords: [
    [77.5800, 34.1500], [76.8800, 34.3300], [76.1300, 34.5500] ], edges: [] },
];

// Tactical feeders connect depots to posts (kept light/dashed).
function tacticalFeeders(data) {
  const dById = Object.fromEntries(data.posts.depots.map(d => [d.depot_id, d]));
  const pById = Object.fromEntries(data.posts.posts.map(p => [p.post_id, p]));
  return [
    ["DEPOT-KARU","POST-002"], ["POST-002","POST-001"], ["DEPOT-KARU","POST-004"],
    ["DEPOT-KARU","POST-003"], ["DEPOT-KARU","POST-005"], ["POST-005","POST-006"],
    ["POST-005","POST-007"], ["DEPOT-KARU","POST-008"], ["DEPOT-HANLE","POST-010"],
    ["DEPOT-HANLE","POST-011"], ["DEPOT-KARGIL","POST-012"], ["POST-012","POST-015"],
    ["DEPOT-KARGIL","POST-014"],
  ].map(([a, b]) => {
    const ac = (dById[a] || pById[a]).coords, bc = (dById[b] || pById[b]).coords;
    return { a, b, coords: [ac, bc] };
  });
}

// Named chokepoints (passes / tunnels) from routes.json.
const CHOKEPOINTS = [
  { name: "Zoji La",    alt: 3528, coords: [75.4708, 34.2833], axis: "LOC-WEST_ZOJILA" },
  { name: "Fotu La",    alt: 4108, coords: [76.5500, 34.4000], axis: "LOC-WEST_ZOJILA" },
  { name: "Atal Tunnel",alt: 3100, coords: [77.3700, 32.4700], axis: "LOC-SOUTH_MANALI" },
  { name: "Baralacha La",alt: 4890, coords: [77.4300, 32.7800], axis: "LOC-SOUTH_MANALI" },
  { name: "Taglang La", alt: 5359, coords: [77.5500, 33.4000], axis: "LOC-SOUTH_MANALI" },
  { name: "Khardung La",alt: 5359, coords: [77.6043, 34.2778], axis: "DSDBO" },
  { name: "Chang La",   alt: 5360, coords: [77.9000, 33.9500], axis: "PANGONG" },
];

// Post markers: shape by type
function postShape(type) {
  if (type.includes("forward_base") || type.includes("brigade_hq") || type.includes("garrison")) return "ring";
  if (type.includes("subdepot") || type.includes("transit")) return "square";
  return "dot"; // OPs, pickets, patrol posts
}

// Per-post label placement overrides — anchor side around the marker
// to resolve collisions for clusters. Default = right.
// Sides: 'r' (right), 'l' (left), 't' (top), 'b' (bottom), 'tr','tl','br','bl'.
const LABEL_SIDE = {
  // Kargil cluster — fan out to avoid label pile-up
  // West→east order: Drass(75.75) -> Tiger Hill(75.90) -> Mushkoh(76.10) -> Kargil(76.13)
  "POST-012": "l",    // Drass Garrison -> left (away from Tiger Hill, clears Zoji La line)
  "POST-015": "tl",   // Tiger Hill OP -> up-left
  "POST-014": "t",    // Mushkoh Valley OP -> straight up (Kargil depot label takes the right)
  // DBO axis
  "POST-002": "l",    // Murgo (along Shyok)
  "POST-001": "r",    // DBO base
  "POST-003": "r",    // Galwan
  "POST-004": "l",    // PP-North-1
  // Pangong/Chushul cluster
  "POST-005": "b",    // Chushul Garrison
  "POST-006": "r",    // Rezang La OP
  "POST-007": "tr",   // Spanggur Gap
  "POST-008": "l",    // Finger Area OP
  // Demchok / Hanle
  "POST-010": "b",    // Demchok Picket
  "POST-011": "r",    // Loma
};

// Posts whose marker should be hidden because they are co-located with a depot.
// The depot symbol already represents this location; rendering both stacks them.
const HIDDEN_POSTS = new Set([
  "POST-013",  // Kargil Sector HQ — coincident with DEPOT-KARGIL
  "POST-009",  // Hanle Forward Camp — coincident with DEPOT-HANLE
]);

const DEPOT_LABEL_SIDE = {
  "DEPOT-LEH": "r",
  "DEPOT-KARU": "br",     // below-right (Karu sits SE of Leh)
  "DEPOT-HANLE": "r",
  "DEPOT-KARGIL": "r",
};

function labelAnchor(side, r) {
  // Returns {dx, dy, anchor} for SVG <text> placement.
  const off = r + 6;
  switch (side) {
    case "l":  return { dx: -off, dy: 3, anchor: "end" };
    case "r":  return { dx:  off, dy: 3, anchor: "start" };
    case "t":  return { dx: 0, dy: -off - 2, anchor: "middle" };
    case "b":  return { dx: 0, dy:  off + 8, anchor: "middle" };
    case "tl": return { dx: -off, dy: -off + 2, anchor: "end" };
    case "tr": return { dx:  off, dy: -off + 2, anchor: "start" };
    case "bl": return { dx: -off, dy:  off + 6, anchor: "end" };
    case "br": return { dx:  off, dy:  off + 6, anchor: "start" };
    default:   return { dx:  off, dy: 3, anchor: "start" };
  }
}

function MapView({ data, worldState, selectedPostId, onSelectPost, showProvenance, onSelectSegment }) {
  const wrapRef = useRef(null);
  const svgRef = useRef(null);
  const [size, setSize] = useState({ w: 800, h: 600 });
  const [hoverId, setHoverId] = useState(null);
  const [tooltip, setTooltip] = useState(null);
  const [view, setView] = useState({ k: 1, tx: 0, ty: 0 }); // zoom + pan
  const [legendOpen, setLegendOpen] = useState(true);
  const dragRef = useRef(null);

  const resetView = () => setView({ k: 1, tx: 0, ty: 0 });
  const zoomBy = (factor, cx, cy) => {
    setView(v => {
      const nextK = Math.max(0.7, Math.min(4, v.k * factor));
      // zoom around (cx, cy) so that point stays put
      const dx = cx - v.tx, dy = cy - v.ty;
      const ratio = nextK / v.k;
      return { k: nextK, tx: cx - dx * ratio, ty: cy - dy * ratio };
    });
  };

  const onWheel = (e) => {
    if (!svgRef.current) return;
    e.preventDefault();
    const rect = svgRef.current.getBoundingClientRect();
    const cx = e.clientX - rect.left, cy = e.clientY - rect.top;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    zoomBy(factor, cx, cy);
  };
  const onMouseDown = (e) => {
    if (e.button !== 0) return;
    // ignore drags that start on a marker (those handle clicks)
    if (e.target.closest("[data-mark]")) return;
    dragRef.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onMouseMove = (e) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.x, dy = e.clientY - dragRef.current.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) dragRef.current.moved = true;
    setView(v => ({ ...v, tx: dragRef.current.tx + dx, ty: dragRef.current.ty + dy }));
  };
  const onMouseUp = () => { dragRef.current = null; };
  useEffect(() => {
    if (!wrapRef.current) return;
    const initialW = wrapRef.current.getBoundingClientRect().width;
    setLegendOpen(initialW >= 760);
    const ro = new ResizeObserver(es => { for (const e of es) {
      const r = e.contentRect; setSize({ w: Math.max(400, r.width), h: Math.max(300, r.height) });
    }});
    ro.observe(wrapRef.current); return () => ro.disconnect();
  }, []);
  const { w, h } = size;
  const closed = worldState.closed_edge_ids;
  const manaliClosed = worldState.closed_loc_ids.has("LOC-SOUTH_MANALI");
  const zojiClosed = closed.has("EDGE-ZOJI-LEH") || closed.has("EDGE-ZOJI-KARGIL");
  const tactical = useMemo(() => tacticalFeeders(data), [data]);

  // graticule
  const grats = [];
  for (let lon = 76; lon <= 79; lon++) { // graticule labels skip 75 (off-grid edge)
    const [x] = project([lon, 33], w, h);
    grats.push(<line key={`gx${lon}`} x1={x} y1="0" x2={x} y2={h} stroke="#eef2f7" strokeWidth="1" />);
    grats.push(<text key={`tx${lon}`} x={x + 3} y="11" fontSize="9" fill="#cbd5e1">{lon}°E</text>);
  }  for (let lat = 33; lat <= 35; lat++) {
    const [, y] = project([76, lat], w, h);
    grats.push(<line key={`gy${lat}`} x1="0" y1={y} x2={w} y2={y} stroke="#eef2f7" strokeWidth="1" />);
    grats.push(<text key={`ty${lat}`} x="3" y={y - 3} fontSize="9" fill="#cbd5e1">{lat}°N</text>);
  }

  // valley shading (Indus + Shyok ribbons)
  const indus = [[76.13,34.55],[76.88,34.33],[77.58,34.15],[78.0,33.5],[79.00,32.78],[79.45,32.70]].map(c => project(c, w, h)).map(p => p.join(",")).join(" ");
  const shyok = [[77.74,33.94],[77.83,34.45],[77.83,35.34]].map(c => project(c, w, h)).map(p => p.join(",")).join(" ");

  return (
    <div ref={wrapRef} style={{ position: "absolute", inset: 0 }}>
      <svg ref={svgRef} width={w} height={h}
        style={{ display: "block", background: "#f1f5f9", cursor: dragRef.current ? "grabbing" : "grab", userSelect: "none" }}
        onWheel={onWheel} onMouseDown={onMouseDown} onMouseMove={onMouseMove}
        onMouseUp={onMouseUp} onMouseLeave={onMouseUp}>
        <defs>
          <pattern id="contour" width="56" height="56" patternUnits="userSpaceOnUse">
            <path d="M0 42 Q14 32 28 42 T56 42 M0 26 Q14 16 28 26 T56 26 M0 10 Q14 0 28 10 T56 10" fill="none" stroke="#e9eef4" strokeWidth="0.7" opacity="0.7" />
          </pattern>
          <filter id="soft-shadow" x="-50%" y="-50%" width="200%" height="200%">
            <feDropShadow dx="0" dy="1" stdDeviation="0.8" floodColor="#0f172a" floodOpacity="0.18" />
          </filter>
        </defs>

        <rect x="0" y="0" width={w} height={h} fill="#f6f8fb" />
        <rect x="0" y="0" width={w} height={h} fill="url(#contour)" />
        <g transform={`translate(${view.tx},${view.ty}) scale(${view.k})`} style={{ transition: dragRef.current ? "none" : "transform 80ms ease-out" }}>
        {grats}

        {/* Valley ribbons */}
        <polyline points={indus} stroke="#bae6fd" strokeWidth="6" fill="none" opacity="0.65" />
        <polyline points={shyok} stroke="#bae6fd" strokeWidth="5" fill="none" opacity="0.6" />
        <text x={project([78.6, 33.4], w, h)[0]} y={project([78.6, 33.4], w, h)[1]} fontSize="9" fill="#0284c7" opacity="0.9" fontStyle="italic">Indus</text>
        <text x={project([77.85, 34.7], w, h)[0]} y={project([77.85, 34.7], w, h)[1]} fontSize="9" fill="#0284c7" opacity="0.9" fontStyle="italic">Shyok</text>

        {/* LAC reference (illustrative) */}
        <path d={"M " + [[77.95,35.5],[78.15,34.85],[78.7,34.3],[78.95,33.6],[79.5,32.7]].map(c => project(c,w,h).join(" ")).join(" L ")}
          fill="none" stroke="#94a3b8" strokeWidth="1" strokeDasharray="2 4" opacity="0.6" />
        <text x={project([78.95, 33.55], w, h)[0]} y={project([78.95, 33.55], w, h)[1]} fontSize="9" fill="#475569" opacity="0.7">LAC (ref)</text>

        {/* Strategic axes (open) */}
        {STRATEGIC_AXES.map(ax => {
          const isClosed = (ax.loc === "LOC-SOUTH_MANALI" && manaliClosed) ||
                           (ax.loc === "LOC-WEST_ZOJILA" && zojiClosed);
          if (isClosed) return null;
          const pts = ax.coords.map(c => project(c, w, h)).map(p => p.join(",")).join(" ");
          return <g key={ax.loc}>
            <polyline points={pts} fill="none" stroke="#fff" strokeWidth="6" />
            <polyline points={pts} fill="none" stroke="#475569" strokeWidth="2.5" />
          </g>;
        })}
        {/* Tactical feeders — dimmer; only the relevant one highlights when a post is selected */}
        {tactical.map(t => {
          const pts = t.coords.map(c => project(c, w, h)).map(p => p.join(",")).join(" ");
          const isHot = selectedPostId && (t.a === selectedPostId || t.b === selectedPostId);
          return <polyline key={`${t.a}-${t.b}`} points={pts} fill="none"
            stroke={isHot ? "#2563eb" : "#cbd5e1"} strokeWidth={isHot ? "1.8" : "1"}
            strokeDasharray={isHot ? "4 2" : "2 4"} opacity={isHot ? 0.95 : 0.55} />;
        })}
        {/* Closed strategic — red dashed on top */}
        {STRATEGIC_AXES.map(ax => {
          const isClosed = (ax.loc === "LOC-SOUTH_MANALI" && manaliClosed) ||
                           (ax.loc === "LOC-WEST_ZOJILA" && zojiClosed);
          if (!isClosed) return null;
          const pts = ax.coords.map(c => project(c, w, h)).map(p => p.join(",")).join(" ");
          return <g key={`${ax.loc}-closed`}>
            <polyline points={pts} fill="none" stroke="#fff" strokeWidth="6" />
            <polyline points={pts} fill="none" stroke={STATUS_HEX.critical} strokeWidth="2.8" strokeDasharray="6 5" />
          </g>;
        })}

        {/* Strategic axis labels — placed off the road, not on it */}
        <text x={project([74.95, 34.18], w, h)[0]} y={project([74.95, 34.18], w, h)[1] - 6} fontSize="9.5" fill="#475569" fontWeight="600" opacity={zojiClosed ? 0.5 : 0.9} stroke="#fff" strokeWidth="3" strokeLinejoin="round" style={{ paintOrder: "stroke fill" }}>NH-1D</text>
        <text x={project([77.18, 32.30], w, h)[0]} y={project([77.18, 32.30], w, h)[1] + 14} fontSize="9.5" fill="#475569" fontWeight="600" opacity={manaliClosed ? 0.5 : 0.9} stroke="#fff" strokeWidth="3" strokeLinejoin="round" style={{ paintOrder: "stroke fill" }}>NH-3</text>

        {/* Chokepoint markers — labels show only on hover or when their axis is closed */}
        {CHOKEPOINTS.map(cp => {
          const [x, y] = project(cp.coords, w, h);
          const isAxisClosed = (cp.axis === "LOC-WEST_ZOJILA" && zojiClosed) ||
                               (cp.axis === "LOC-SOUTH_MANALI" && manaliClosed);
          const fill = isAxisClosed ? STATUS_HEX.critical : "#475569";
          const cpHov = hoverId === `cp:${cp.name}`;
          // Always-on labels for the major / closure-relevant passes; others on hover.
          const ALWAYS = new Set(["Zoji La", "Khardung La", "Atal Tunnel", "Taglang La"]);
          const showLbl = ALWAYS.has(cp.name) || cpHov || isAxisClosed;
          // Per-pass label side overrides to avoid colliding with posts/depots.
          const SIDE = { "Zoji La": "t", "Fotu La": "t", "Atal Tunnel": "l", "Baralacha La": "l", "Taglang La": "l", "Khardung La": "tr", "Chang La": "t" }[cp.name] || "r";
          const dx = SIDE === "l" ? -7 : SIDE === "r" ? 7 : 0;
          const dy = SIDE === "t" ? -8 : SIDE === "b" ? 14 : -2;
          const anchor = SIDE === "l" ? "end" : SIDE === "r" ? "start" : "middle";
          return (
            <g key={cp.name}
              style={{ cursor: "default" }}
              onMouseEnter={() => setHoverId(`cp:${cp.name}`)}
              onMouseLeave={() => setHoverId(null)}>
              <polygon points={`${x},${y-5} ${x-4},${y+3} ${x+4},${y+3}`} fill={fill} stroke="#fff" strokeWidth="1.2" />
              {showLbl && (
                <g>
                  <text x={x + dx} y={y + dy} fontSize="9" fill="#fff" stroke="#fff" strokeWidth="3" strokeLinejoin="round" textAnchor={anchor} fontWeight="600" style={{ paintOrder: "stroke fill" }}>{cp.name}</text>
                  <text x={x + dx} y={y + dy} fontSize="9" fill="#0f172a" textAnchor={anchor} fontWeight="600">{cp.name}</text>
                  <text x={x + dx} y={y + dy + 9} fontSize="8" fill="#fff" stroke="#fff" strokeWidth="3" strokeLinejoin="round" textAnchor={anchor} style={{ paintOrder: "stroke fill" }}>{cp.alt}m</text>
                  <text x={x + dx} y={y + dy + 9} fontSize="8" fill="#64748b" textAnchor={anchor}>{cp.alt}m</text>
                </g>
              )}
              <circle cx={x} cy={y} r="10" fill="transparent" />
            </g>
          );
        })}

        {/* Depots */}
        {data.posts.depots.map(d => {
          const [x, y] = project(d.coords, w, h);
          const tier = d.tier;
          const color = tier === "corps_main" ? "#1d4ed8" : tier === "brigade_main" ? "#2563eb" : "#3b82f6";
          const sz = tier === "corps_main" ? 9 : 7;
          const dHov = hoverId === d.depot_id;
          const labelSide = DEPOT_LABEL_SIDE[d.depot_id] || "r";
          // Compute label position from side
          const off = sz + 4;
          const ldx = labelSide === "l" ? -off : labelSide === "r" ? off : labelSide === "br" ? off : labelSide === "bl" ? -off : 0;
          const ldy = labelSide.startsWith("b") ? off + 6 : labelSide.startsWith("t") ? -off - 4 : -3;
          const lAnchor = labelSide === "l" || labelSide === "bl" || labelSide === "tl" ? "end" : labelSide === "r" || labelSide === "br" || labelSide === "tr" ? "start" : "middle";
          const subLabel = tier === "corps_main" ? "Corps Main" : tier === "brigade_main" ? (d.notional_formation?.split("(")[0].trim() || "Brigade Main") : "Sub-Depot";
          const shortName = d.name.replace(/ Main Depot| Sub-Depot| ASC Depot/, "");
          const labelEl = (
            <g>
              <text x={x + ldx} y={y + ldy} fontSize="10.5" fill="#fff" stroke="#fff" strokeWidth="3.5" strokeLinejoin="round" textAnchor={lAnchor} fontWeight="700" style={{ paintOrder: "stroke fill" }}>{shortName}</text>
              <text x={x + ldx} y={y + ldy} fontSize="10.5" fill="#0f172a" textAnchor={lAnchor} fontWeight="700">{shortName}</text>
              <text x={x + ldx} y={y + ldy + 10} fontSize="8.5" fill="#fff" stroke="#fff" strokeWidth="3" strokeLinejoin="round" textAnchor={lAnchor} style={{ paintOrder: "stroke fill" }}>{subLabel}</text>
              <text x={x + ldx} y={y + ldy + 10} fontSize="8.5" fill="#64748b" textAnchor={lAnchor}>{subLabel}</text>
            </g>
          );
          const handlers = {
            onMouseEnter: () => { setHoverId(d.depot_id); setTooltip({ x, y, depot: d }); },
            onMouseLeave: () => { setHoverId(null); setTooltip(null); },
          };
          if (tier === "brigade_main") {
            return <g key={d.depot_id} filter="url(#soft-shadow)" {...handlers} style={{ cursor: "default" }}>
              <polygon points={`${x},${y-sz} ${x+sz},${y} ${x},${y+sz} ${x-sz},${y}`} fill={color} stroke="#fff" strokeWidth="2" />
              {labelEl}
              <circle cx={x} cy={y} r={sz + 4} fill="transparent" />
            </g>;
          }
          return <g key={d.depot_id} filter="url(#soft-shadow)" {...handlers} style={{ cursor: "default" }}>
            <rect x={x - sz} y={y - sz} width={sz * 2} height={sz * 2} fill={color} stroke="#fff" strokeWidth="2" rx="2" />
            {labelEl}
            <circle cx={x} cy={y} r={sz + 4} fill="transparent" />
          </g>;
        })}

        {/* Posts */}
        {data.posts.posts.filter(p => !HIDDEN_POSTS.has(p.post_id)).map(p => {
          const [x, y] = project(p.coords, w, h);
          const snap = worldState.post_states.get(p.post_id);
          const status = snap?.status ?? "ok";
          const color = STATUS_HEX[status];
          const sel = p.post_id === selectedPostId;
          const hov = p.post_id === hoverId;
          const tracked = !!snap;
          const trackedAlert = tracked && status !== "ok";
          const shape = postShape(p.type);
          const r = sel || hov ? 7 : (tracked ? 5.5 : 4);
          // Show label when: selected, hovered, tracked-with-non-ok-status
          const showLabel = sel || hov || trackedAlert;
          const side = LABEL_SIDE[p.post_id] || "r";
          const lp = labelAnchor(side, r);
          return (
            <g key={p.post_id} style={{ cursor: "pointer" }}
              onClick={(ev) => { ev.stopPropagation(); onSelectPost(p.post_id); }}
              onMouseEnter={(ev) => {
                setHoverId(p.post_id);
                const wrapRect = wrapRef.current?.getBoundingClientRect();
                setTooltip({ x: x, y: y, post: p, snap });
              }}
              onMouseLeave={() => { setHoverId(null); setTooltip(null); }}>
              {(sel || trackedAlert || hov) && (
                <circle cx={x} cy={y} r={r + 5} fill="none" stroke={color}
                  strokeWidth={sel ? 2 : 1.2} opacity={sel ? 0.55 : (hov ? 0.45 : 0.32)} />
              )}
              {shape === "ring"   && <circle cx={x} cy={y} r={r} fill="#fff" stroke={tracked ? color : "#94a3b8"} strokeWidth={sel || hov ? 3 : 2.5} />}
              {shape === "square" && <rect x={x - r} y={y - r} width={r * 2} height={r * 2} fill={tracked ? color : "#94a3b8"} stroke="#fff" strokeWidth={sel || hov ? 2.5 : 2} rx="1" />}
              {shape === "dot"    && <circle cx={x} cy={y} r={r} fill={tracked ? color : "#94a3b8"} stroke="#fff" strokeWidth={sel || hov ? 2.5 : 2} />}
              {showLabel && (
                <g>
                  {/* white halo behind label for legibility */}
                  <text x={x + lp.dx} y={y + lp.dy} fontSize="9.5" fill="#fff"
                    stroke="#fff" strokeWidth="3" strokeLinejoin="round"
                    textAnchor={lp.anchor} fontWeight={sel || hov ? 600 : 500}
                    style={{ paintOrder: "stroke fill" }}>
                    {p.name}
                  </text>
                  <text x={x + lp.dx} y={y + lp.dy} fontSize="9.5" fill="#0f172a"
                    textAnchor={lp.anchor} fontWeight={sel || hov ? 600 : 500}>
                    {p.name}
                  </text>
                </g>
              )}
              {showProvenance && showLabel && (
                <text x={x + lp.dx} y={y + lp.dy + 10} fontSize="8" fill="#64748b"
                  textAnchor={lp.anchor} fontFamily="ui-monospace,Menlo,monospace">grade {p.provenance_grade}</text>
              )}
              {/* invisible larger hit target for easier hover/click */}
              <circle cx={x} cy={y} r={Math.max(r + 6, 11)} fill="transparent" />
            </g>
          );
        })}
        </g>
      </svg>

      {/* Zoom controls */}
      <div className="map-zoom">
        <button onClick={() => zoomBy(1.3, w/2, h/2)} aria-label="Zoom in">＋</button>
        <button onClick={() => zoomBy(1/1.3, w/2, h/2)} aria-label="Zoom out">−</button>
        <button onClick={resetView} aria-label="Reset view">⟲</button>
      </div>

      {/* Map overlays */}
      <div className={`map-legend ${legendOpen ? "" : "map-legend--closed"}`}>
        <button className="legend-toggle" onClick={() => setLegendOpen(o => !o)} aria-label={legendOpen ? "Collapse legend" : "Expand legend"}>
          <span className="legend-toggle-label">{legendOpen ? "Legend" : "?"}</span>
          {legendOpen && <span className="legend-toggle-chev">×</span>}
        </button>
        {legendOpen && <>
        <div className="legend-title">Symbols</div>
        <div className="legend-row"><span className="legend-glyph"><svg width="14" height="14"><polygon points="7,2 12,7 7,12 2,7" fill="#2563eb" /></svg></span><span>Brigade Main</span></div>
        <div className="legend-row"><span className="legend-glyph"><svg width="14" height="14"><rect x="3" y="3" width="8" height="8" fill="#1d4ed8" rx="1" /></svg></span><span>Corps / Sub-Depot</span></div>
        <div className="legend-row"><span className="legend-glyph"><svg width="14" height="14"><circle cx="7" cy="7" r="4" fill="#fff" stroke="#475569" strokeWidth="2" /></svg></span><span>Garrison / FB</span></div>
        <div className="legend-row"><span className="legend-glyph"><svg width="14" height="14"><circle cx="7" cy="7" r="3.5" fill="#475569" /></svg></span><span>OP / Patrol</span></div>
        <div className="legend-row"><span className="legend-glyph"><svg width="14" height="14"><polygon points="7,2 11,10 3,10" fill="#475569" /></svg></span><span>Pass / chokepoint</span></div>
        <div className="legend-divider" />
        <div className="legend-title">Status</div>
        {["ok","watch","critical","imminent"].map(s => (
          <div key={s} className="legend-row">
            <span className="legend-glyph"><span className="legend-pill" style={{ background: STATUS_HEX[s] }} /></span>
            <span>{STATUS_LABEL[s]}</span>
          </div>
        ))}
        <div className="legend-divider" />
        <div className="legend-row"><span className="legend-glyph"><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke="#475569" strokeWidth="2" /></svg></span><span>LoC open</span></div>
        <div className="legend-row"><span className="legend-glyph"><svg width="20" height="6"><line x1="0" y1="3" x2="20" y2="3" stroke={STATUS_HEX.critical} strokeWidth="2" strokeDasharray="4 3" /></svg></span><span>LoC closed</span></div>
        </>}
      </div>

      <div className="map-meta">
        <div><span className="meta-label">AOI</span> Eastern Ladakh · XIV Corps</div>
        <div><span className="meta-label">CRS</span> EPSG:4326</div>
        <div><span className="meta-label">BBox</span> {BBOX[0]}–{BBOX[2]}°E · {BBOX[1]}–{BBOX[3]}°N</div>
      </div>

      <div className="map-scale">
        <div className="scale-bar"><div /><div /><div /><div /></div>
        <div className="scale-label">0    50   100 km (approx)</div>
      </div>

      <div className="map-north">
        <svg width="32" height="32" viewBox="0 0 32 32">
          <circle cx="16" cy="16" r="14" fill="#fff" stroke="#cbd5e1" strokeWidth="1" />
          <polygon points="16,4 19,16 16,13 13,16" fill={STATUS_HEX.critical} />
          <polygon points="16,28 19,16 16,19 13,16" fill="#475569" />
          <text x="16" y="11" textAnchor="middle" fontSize="8" fontWeight="700" fill="#0f172a">N</text>
        </svg>
      </div>

      {tooltip && (() => {
        const ttX = Math.max(110, Math.min(w - 110, tooltip.x));
        const ttY = Math.max(80, tooltip.y);
        if (tooltip.post) {
          const p = tooltip.post; const s = tooltip.snap;
          const status = s?.status ?? "ok";
          const typePretty = p.type.replace(/_/g, " ");
          return (
            <div className="map-tooltip" style={{ left: ttX, top: ttY }}>
              <div className="mt-name">{p.name}</div>
              <div className="mt-row"><span>{typePretty}</span><span className="v">{p.altitude_m}m</span></div>
              <div className="mt-row"><span className="upper-xs">{p.altitude_band}</span><span className="muted-mono">{p.post_id}</span></div>
              {s && (
                <>
                  <div className="mt-divider" />
                  <div className="mt-row"><span>Stock</span><span className="v">{s.kerosene_stock_L != null ? `${s.kerosene_stock_L.toLocaleString()} L` : "—"}</span></div>
                  <div className="mt-row"><span>Burn</span><span className="v">{Math.round(s.daily_burn_L)} L/d</span></div>
                  <div className="mt-row"><span>DTS</span><span className="v">{s.days_to_stockout != null ? `${s.days_to_stockout} d` : "—"}</span></div>
                  <div className="mt-row"><span>Status</span><span className="mt-status" style={{ color: STATUS_HEX[status] }}><span className="d" style={{ background: STATUS_HEX[status] }} />{STATUS_LABEL[status]}</span></div>
                </>
              )}
              <div className="mt-hint">Click to focus on this post</div>
            </div>
          );
        }
        if (tooltip.depot) {
          const d = tooltip.depot;
          const tierLabel = d.tier === "corps_main" ? "Corps Main Depot" : d.tier === "brigade_main" ? "Brigade Main Depot" : "Division Sub-Depot";
          return (
            <div className="map-tooltip" style={{ left: ttX, top: ttY }}>
              <div className="mt-name">{d.name}</div>
              <div className="mt-row"><span>{tierLabel}</span><span className="v">{d.altitude_m}m</span></div>
              <div className="mt-row"><span className="muted-mono">{d.depot_id}</span><span className="upper-xs">grade {d.provenance_grade}</span></div>
              {d.notional_formation && <><div className="mt-divider" /><div className="mt-row" style={{ display: "block" }}>{d.notional_formation}</div></>}
            </div>
          );
        }
        return null;
      })()}
    </div>
  );
}

Object.assign(window, {
  STATUS_PRIORITY, STATUS_HEX, STATUS_BG, STATUS_LABEL,
  computeWorldState, parseDayKey,
  StatusPill, Sparkline, MapView,
});
