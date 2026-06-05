// Map: stylized SVG of Eastern Ladakh AOI for the Posts & Routes screen.
// Pan + zoom + hover + click on posts, passes, depots.

const BBOX = [75.0, 32.4, 80.0, 36.0]; // [w, s, e, n]

function projectMap(coords, vw, vh) {
  const [w, s, e, n] = BBOX;
  const x = ((coords[0] - w) / (e - w)) * vw;
  const y = vh - ((coords[1] - s) / (n - s)) * vh;
  return [x, y];
}

const STATUS_HEX = {
  ok: "#16a34a",
  rationing: "#ca8a04",
  stockout: "#dc2626",
};

const TERRAIN = [
  { d: "M 0 0 L 100 0 L 100 28 L 0 22 Z",   fill: "#e2e8f0" },
  { d: "M 5 48 L 60 50 L 60 58 L 5 56 Z",   fill: "#eef2f6" },
  { d: "M 60 70 L 100 70 L 100 100 L 60 100 Z", fill: "#e2e8f0" },
  { d: "M 0 55 L 22 58 L 22 100 L 0 100 Z", fill: "#e2e8f0" },
];

function PostsMap({ posts, depots, passes, routes, hydro, lac, postStatus, selectedPostId, onSelectPost, isolatedSet, onSelectPass }) {
  const ref = React.useRef(null);
  const svgRef = React.useRef(null);
  const [size, setSize] = React.useState({ w: 1200, h: 540 });
  const [view, setView] = React.useState({ x: 0, y: 0, k: 1 }); // pan + zoom
  const [drag, setDrag] = React.useState(null);
  const [hover, setHover] = React.useState(null); // { kind, id, sx, sy }

  React.useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) {
        const cr = e.contentRect;
        setSize({ w: Math.max(400, cr.width), h: Math.max(300, cr.height) });
      }
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);

  const W = size.w, H = size.h;
  const VW = 100;
  const VH = (H / W) * 100;

  const passByName = Object.fromEntries(passes.map((p) => [p.pass_name, p]));

  // pan/zoom interaction
  const onWheel = (e) => {
    e.preventDefault();
    const rect = svgRef.current.getBoundingClientRect();
    const mx = (e.clientX - rect.left) / rect.width * VW;
    const my = (e.clientY - rect.top) / rect.height * VH;
    const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
    const nk = Math.max(1, Math.min(8, view.k * factor));
    const ratio = nk / view.k;
    // anchor zoom on cursor
    const nx = mx - (mx - view.x) * ratio;
    const ny = my - (my - view.y) * ratio;
    setView(clampView({ x: nx, y: ny, k: nk }, VW, VH));
  };
  const onDown = (e) => {
    if (e.button !== 0) return;
    setDrag({ sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y });
  };
  const onMove = (e) => {
    if (!drag) return;
    const rect = svgRef.current.getBoundingClientRect();
    const dx = (e.clientX - drag.sx) / rect.width * VW;
    const dy = (e.clientY - drag.sy) / rect.height * VH;
    setView(clampView({ x: drag.vx + dx, y: drag.vy + dy, k: view.k }, VW, VH));
  };
  const onUp  = () => setDrag(null);

  // event coords → world coords (already factor of viewBox transform)
  // transform-origin for zoom: we use `transform` on a <g>. world point (wx, wy) maps to (view.x + wx*k, view.y + wy*k).

  // Tooltip positioning (screen-space px relative to container)
  const renderTooltip = () => {
    if (!hover) return null;
    if (hover.kind === "post") {
      const p = posts.find((x) => x.post_id === hover.id);
      const status = postStatus[p.post_id] || "ok";
      const isolated = isolatedSet.has(p.post_id);
      return (
        <div className="map-tooltip" style={{ left: hover.sx + 12, top: hover.sy + 12 }}>
          <div className="mt-eyebrow">{p.post_id} · {p.band}</div>
          <div className="mt-title">{p.name}</div>
          <div className="mt-row"><span>Axis</span><span>{p.axis}</span></div>
          <div className="mt-row"><span>Elev</span><span className="mono">{p.elev_m.toLocaleString()}m</span></div>
          <div className="mt-row"><span>Troops</span><span className="mono">{p.troops}</span></div>
          <div className="mt-row"><span>Status (worst-case)</span><span style={{ color: STATUS_HEX[status] }}>{status}</span></div>
          {isolated && <div className="mt-row" style={{ color: "var(--crit)" }}><span>Road</span><span>isolated</span></div>}
          <div className="mt-hint">Click to inspect</div>
        </div>
      );
    }
    if (hover.kind === "pass") {
      const pa = passes.find((x) => x.pass_name === hover.id);
      return (
        <div className="map-tooltip" style={{ left: hover.sx + 12, top: hover.sy + 12 }}>
          <div className="mt-eyebrow">PASS</div>
          <div className="mt-title">{pa.pass_name}</div>
          <div className="mt-row"><span>Elev</span><span className="mono">{pa.elev_m.toLocaleString()}m</span></div>
          <div className="mt-row"><span>Axis</span><span>{pa.axis}</span></div>
          <div className="mt-row"><span>P(open) 14d</span><span className="mono" style={{ color: "var(--ok)" }}>{(pa.p_open * 100).toFixed(0)}%</span></div>
          <div className="mt-row"><span>P(closed) 14d</span><span className="mono" style={{ color: "var(--crit)" }}>{(pa.p_closed * 100).toFixed(0)}%</span></div>
          <div className="mt-hint">Click to inspect lineage</div>
        </div>
      );
    }
    if (hover.kind === "depot") {
      const d = depots.find((x) => x.depot_id === hover.id);
      return (
        <div className="map-tooltip" style={{ left: hover.sx + 12, top: hover.sy + 12 }}>
          <div className="mt-eyebrow">DEPOT</div>
          <div className="mt-title">{d.name}</div>
          <div className="mt-row"><span>ID</span><span className="mono">{d.depot_id}</span></div>
          <div className="mt-row"><span>Axis</span><span>{d.axis}</span></div>
          <div className="mt-row"><span>Elev</span><span className="mono">{d.elev_m.toLocaleString()}m</span></div>
        </div>
      );
    }
    return null;
  };

  const transform = `translate(${view.x}, ${view.y}) scale(${view.k})`;
  // Counter-scale so labels and markers stay visually constant while zooming
  const inv = 1 / view.k;
  // helper: capture screen coords from event
  const screen = (e) => {
    const rect = ref.current.getBoundingClientRect();
    return { sx: e.clientX - rect.left, sy: e.clientY - rect.top };
  };

  return (
    <div ref={ref} className="map-stage">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VW} ${VH}`}
        preserveAspectRatio="xMidYMid slice"
        className="map-svg"
        onWheel={onWheel}
        onMouseDown={onDown}
        onMouseMove={onMove}
        onMouseUp={onUp}
        onMouseLeave={() => { onUp(); setHover(null); }}
        style={{ cursor: drag ? "grabbing" : "grab" }}
      >
        <rect x="0" y="0" width={VW} height={VH} fill="#f1f5f9" />

        <g transform={transform}>
          {/* Terrain */}
          <g opacity="0.7">
            {TERRAIN.map((p, i) => {
              const scaled = p.d.replace(/(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)/g, (m, a, b) =>
                `${(parseFloat(a) / 100) * VW} ${(parseFloat(b) / 100) * VH}`
              );
              return <path key={i} d={scaled} className="terrain" fill={p.fill} />;
            })}
          </g>

          {/* Graticule */}
          {[33, 34, 35].map((lat) => {
            const [, y] = projectMap([BBOX[0], lat], VW, VH);
            return (
              <g key={`lat-${lat}`}>
                <line x1="0" y1={y} x2={VW} y2={y} className="gridline" />
                <text x="0.6" y={y - 0.3} className="gridlabel" style={{ fontSize: `${0.8 * inv}px` }}>{lat}°N</text>
              </g>
            );
          })}
          {[76, 77, 78, 79].map((lon) => {
            const [x] = projectMap([lon, BBOX[1]], VW, VH);
            return (
              <g key={`lon-${lon}`}>
                <line x1={x} y1="0" x2={x} y2={VH} className="gridline" />
                <text x={x + 0.3} y={VH - 0.4} className="gridlabel" style={{ fontSize: `${0.8 * inv}px` }}>{lon}°E</text>
              </g>
            );
          })}

          {/* Hydro */}
          {hydro.map((lake) => {
            const pts = lake.points.map((c) => projectMap(c, VW, VH).join(",")).join(" ");
            const [lx, ly] = projectMap(lake.points[Math.floor(lake.points.length / 2)], VW, VH);
            return (
              <g key={lake.name}>
                <polygon points={pts} className="hydro" />
                <text x={lx} y={ly} className="hydro-label" textAnchor="middle" style={{ fontSize: `${0.85 * inv}px` }}>{lake.name}</text>
              </g>
            );
          })}

          {/* LAC */}
          <polyline points={lac.map((c) => projectMap(c, VW, VH).join(",")).join(" ")} className="lac" style={{ strokeWidth: 0.15 * inv, strokeDasharray: `${0.7 * inv},${0.4 * inv}` }} />

          {/* Routes */}
          {routes.map((rt) => {
            const fromPt = (depots.find((d) => d.depot_id === rt.from) || posts.find((p) => p.post_id === rt.from));
            const toPt   = (depots.find((d) => d.depot_id === rt.to)   || posts.find((p) => p.post_id === rt.to));
            if (!fromPt || !toPt) return null;
            const viaPts = (rt.via || []).map((pn) => passByName[pn]?.coords).filter(Boolean);
            const path = [fromPt.coords, ...viaPts, toPt.coords].map((c) => projectMap(c, VW, VH).join(","));
            const dashStyle = rt.status === "crit" ? { strokeDasharray: `${1*inv},${0.5*inv}`, strokeWidth: 0.3 * inv } : { strokeWidth: (rt.status === "warn" ? 0.2 : 0.1) * inv };
            return (
              <polyline
                key={rt.route_id}
                points={path.join(" ")}
                className={`route ${rt.status === "crit" ? "crit" : rt.status === "warn" ? "warn" : ""}`}
                style={dashStyle}
              />
            );
          })}

          {/* Pass markers */}
          {passes.map((p) => {
            const [x, y] = projectMap(p.coords, VW, VH);
            const isHov = hover && hover.kind === "pass" && hover.id === p.pass_name;
            return (
              <g key={p.pass_name} transform={`translate(${x}, ${y})`} style={{ cursor: "pointer" }}
                 onMouseEnter={(e) => setHover({ kind: "pass", id: p.pass_name, ...screen(e) })}
                 onMouseMove={(e) => setHover((h) => h ? { ...h, ...screen(e) } : h)}
                 onMouseLeave={() => setHover(null)}
                 onClick={(e) => { e.stopPropagation(); onSelectPass && onSelectPass(p); }}>
                {/* invisible hit area */}
                <circle r={3.0 * inv} fill="transparent" />
                <circle r={1.4 * inv} className={`pass-marker ${p.status}`} style={{ strokeWidth: (isHov ? 0.25 : 0.15) * inv }} />
                {(isHov || view.k > 1.5) && (
                  <>
                    <text x={2 * inv} y={0.4 * inv} className="pass-label" style={{ fontSize: `${0.85 * inv}px`, strokeWidth: 0.28 * inv }}>{p.pass_name}</text>
                    <text x={2 * inv} y={1.6 * inv} className="pass-label" style={{ fill: "var(--ink-muted)", fontWeight: 400, fontSize: `${0.7 * inv}px`, strokeWidth: 0.28 * inv }}>
                      P(closed) {(p.p_closed * 100).toFixed(0)}%
                    </text>
                  </>
                )}
              </g>
            );
          })}

          {/* Depots */}
          {depots.map((d) => {
            const [x, y] = projectMap(d.coords, VW, VH);
            const isHov = hover && hover.kind === "depot" && hover.id === d.depot_id;
            return (
              <g key={d.depot_id} transform={`translate(${x}, ${y})`} style={{ cursor: "pointer" }}
                 onMouseEnter={(e) => setHover({ kind: "depot", id: d.depot_id, ...screen(e) })}
                 onMouseMove={(e) => setHover((h) => h ? { ...h, ...screen(e) } : h)}
                 onMouseLeave={() => setHover(null)}>
                <rect x={-2.0 * inv} y={-2.0 * inv} width={4.0 * inv} height={4.0 * inv} fill="transparent" />
                <rect x={-1.0 * inv} y={-1.0 * inv} width={2.0 * inv} height={2.0 * inv} rx={0.2 * inv} className="depot-marker"
                      style={{ strokeWidth: (isHov ? 0.35 : 0.22) * inv }} />
                <text x={1.4 * inv} y={0.4 * inv} className="depot-label" style={{ fontSize: `${0.9 * inv}px`, strokeWidth: 0.28 * inv }}>{d.name}</text>
              </g>
            );
          })}

          {/* Posts */}
          {posts.map((p) => {
            const [x, y] = projectMap(p.coords, VW, VH);
            const status = postStatus[p.post_id] || "ok";
            const isolated = isolatedSet.has(p.post_id);
            const selected = p.post_id === selectedPostId;
            const isHov = hover && hover.kind === "post" && hover.id === p.post_id;
            const baseR = selected || isHov ? 1.1 : 0.85;
            const r = baseR * inv;
            return (
              <g key={p.post_id} transform={`translate(${x}, ${y})`} style={{ cursor: "pointer" }}
                 onMouseEnter={(e) => setHover({ kind: "post", id: p.post_id, ...screen(e) })}
                 onMouseMove={(e) => setHover((h) => h ? { ...h, ...screen(e) } : h)}
                 onMouseLeave={() => setHover(null)}
                 onClick={(e) => { e.stopPropagation(); onSelectPost(p.post_id); }}>
                {/* invisible hit area */}
                <circle r={2.4 * inv} fill="transparent" />
                {isolated && <circle r={2.0 * inv} className="isolation-ring" style={{ strokeWidth: 0.1 * inv, strokeDasharray: `${0.3*inv},${0.2*inv}` }} />}
                <circle r={r} fill={STATUS_HEX[status] || "#94a3b8"}
                        className={`post-marker ${selected ? "selected" : ""}`}
                        style={{ strokeWidth: (selected ? 0.35 : 0.22) * inv }} />
                {(selected || isHov || p.troops > 200 || view.k > 2) && (
                  <text x={1.3 * inv} y={0.4 * inv} className="post-label" style={{ fontSize: `${0.9 * inv}px`, strokeWidth: 0.28 * inv }}>{p.name}</text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {renderTooltip()}

      {/* Legend */}
      <div className="map-overlay map-legend">
        <div className="lg-eyebrow">Posts</div>
        <div className="lg-row"><span className="lg-dot" style={{ background: "#16a34a" }} /><span>OK</span></div>
        <div className="lg-row"><span className="lg-dot" style={{ background: "#ca8a04" }} /><span>Rationing (worst-case)</span></div>
        <div className="lg-row"><span className="lg-dot" style={{ background: "#dc2626" }} /><span>Stockout (worst-case)</span></div>
        <div className="lg-sep" />
        <div className="lg-eyebrow">Topology</div>
        <div className="lg-row"><span className="lg-square" /><span>Depot</span></div>
        <div className="lg-row"><span style={{ width: 14, height: 14, borderRadius: "50%", border: "1.5px solid var(--crit)", background: "white" }} /><span>Pass · P(closed) ≥ 60%</span></div>
        <div className="lg-row"><span className="lg-line" /><span>Road · degraded</span></div>
        <div className="lg-row"><span style={{ width: 16, height: 16, border: "1px dashed var(--crit)", borderRadius: "50%", flexShrink: 0 }} /><span>Road-isolated post</span></div>
      </div>

      {/* Zoom controls */}
      <div className="map-overlay map-zoom">
        <button type="button" className="zoom-btn" onClick={() => setView((v) => clampView({ ...v, k: Math.min(8, v.k * 1.3) }, VW, VH))} title="Zoom in">+</button>
        <button type="button" className="zoom-btn" onClick={() => setView((v) => clampView({ ...v, k: Math.max(1, v.k / 1.3) }, VW, VH))} title="Zoom out">−</button>
        <button type="button" className="zoom-btn" onClick={() => setView({ x: 0, y: 0, k: 1 })} title="Reset view">⊙</button>
      </div>

      <div className="map-overlay map-scale">
        <div className="map-scale-bar" />
        <div className="map-scale-label">~{Math.round(50 / view.k)} km</div>
      </div>

      <div className="map-attrib">
        Eastern Ladakh AOI · {posts.length} posts · {passes.length} passes · seed 42
        <span style={{ marginLeft: 8, color: "var(--ink-faint)" }}>scroll to zoom · drag to pan</span>
      </div>
    </div>
  );
}

// Clamp pan so we never reveal more than 50% of empty canvas on any side.
function clampView({ x, y, k }, VW, VH) {
  const mx = VW * (k - 1);
  const my = VH * (k - 1);
  return {
    k,
    x: Math.min(0, Math.max(-mx, x)),
    y: Math.min(0, Math.max(-my, y)),
  };
}

window.PostsMap = PostsMap;
