// Bastion FSP v2 — analyst panels and shell.
const { useState, useMemo, useEffect } = React;
const { StatusPill, Sparkline, MapView, computeWorldState, parseDayKey, STATUS_HEX, STATUS_PRIORITY, STATUS_LABEL } = window;

// =====================================================================
// Top bar
// =====================================================================
const SHORT_TITLES = {
  "SCEN-01-NORMAL_OPS": "S1 · Normal ops baseline",
  "SCEN-02-ZOJI_LA_CASCADE": "S2 · Zoji La cascade",
  "SCEN-03-VEHICLE_DEADLINE_CASCADE": "S3 · Vehicle deadline cascade",
};
function TopBar({ scenarios, scenarioId, onSelect, worldState }) {
  return (
    <header className="topbar">
      <div className="topbar-l">
        <div className="logo">B</div>
        <div className="brand-block">
          <div className="brand">Bastion <span className="brand-mod">FSP</span></div>
          <div className="brand-sub">Forward Stockout Predictor · v0.2 · Wk8</div>
        </div>
        <div className="divider-v" />
        <select className="scn-select" value={scenarioId} onChange={e => onSelect(e.target.value)}>
          {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{SHORT_TITLES[s.scenario_id]}</option>)}
        </select>
      </div>
      <div className="topbar-r">
        {worldState && (
          <>
            <div className="kpi"><span className="kpi-l">Day</span><span className="kpi-v">{String(worldState.day).padStart(2,"0")} / {worldState.duration_days}</span></div>
            <div className="kpi"><span className="kpi-l">Worst</span><StatusPill status={worldState.global_worst_status} size="sm" /></div>
            <div className="kpi"><span className="kpi-l">Tracked</span><span className="kpi-v">{worldState.post_states.size}/15</span></div>
            <div className="kpi"><span className="kpi-l">Closed LoCs</span><span className="kpi-v">{worldState.closed_loc_ids.size + worldState.closed_edge_ids.size}</span></div>
          </>
        )}
        <span className="badge demo">DEMO</span>
      </div>
    </header>
  );
}

// =====================================================================
// Left rail — posts list
// =====================================================================
function PostsRail({ data, worldState, selectedId, onSelect }) {
  const ranked = [...data.posts.posts].sort((a, b) => {
    const sa = worldState.post_states.get(a.post_id)?.status ?? "ok";
    const sb = worldState.post_states.get(b.post_id)?.status ?? "ok";
    const d = STATUS_PRIORITY[sb] - STATUS_PRIORITY[sa]; if (d) return d;
    const da = worldState.post_states.get(a.post_id)?.days_to_stockout ?? 999;
    const db = worldState.post_states.get(b.post_id)?.days_to_stockout ?? 999;
    if (da !== db) return da - db;
    return a.post_id.localeCompare(b.post_id);
  });
  const tracked = ranked.filter(p => worldState.post_states.has(p.post_id));
  const untracked = ranked.filter(p => !worldState.post_states.has(p.post_id));
  return (
    <aside className="rail rail-l">
      <div className="rail-head">
        <span className="rail-title">Posts</span>
        <span className="rail-sub">{tracked.length} tracked · {untracked.length} static</span>
      </div>
      <div className="rail-scroll">
        {tracked.length > 0 && <div className="rail-section-l">Tracked this scenario</div>}
        {tracked.map(p => <PostRow key={p.post_id} post={p} snap={worldState.post_states.get(p.post_id)} selected={p.post_id === selectedId} onClick={() => onSelect(p.post_id === selectedId ? null : p.post_id)} />)}
        <div className="rail-section-l">All posts</div>
        {untracked.map(p => <PostRow key={p.post_id} post={p} snap={undefined} selected={p.post_id === selectedId} onClick={() => onSelect(p.post_id === selectedId ? null : p.post_id)} />)}
      </div>
    </aside>
  );
}
function PostRow({ post, snap, selected, onClick }) {
  const status = snap?.status ?? "ok";
  return (
    <button onClick={onClick} className={`post-row ${selected ? "post-row--selected" : ""}`}>
      <div className="post-row-main">
        <div className="post-row-title">{post.name}</div>
        <div className="post-row-meta">
          <span className="muted-mono">{post.post_id}</span>
          <span className="dot-sep">·</span>
          <span>{post.altitude_m}m</span>
          <span className="dot-sep">·</span>
          <span className="upper-xs">{post.altitude_band}</span>
        </div>
      </div>
      <div className="post-row-tail">
        <StatusPill status={status} size="sm" />
        {snap && snap.days_to_stockout != null && (
          <div className="dts-mini">{snap.days_to_stockout}d</div>
        )}
      </div>
    </button>
  );
}

// =====================================================================
// Right panel — tabbed analyst panel
// =====================================================================
function AnalystPanel({ scenario, worldState, data, selectedPost }) {
  const [tab, setTab] = useState("brief");
  const tabs = [
    ["brief", "Brief"], ["stock", "Stock & Burn"], ["coa", "Resupply COAs"],
    ["routes", "Routes"], ["fleet", "Fleet"],
  ];
  return (
    <aside className="rail rail-r">
      <div className="tab-row">
        {tabs.map(([k, l]) => (
          <button key={k} onClick={() => setTab(k)} className={`tab ${tab === k ? "tab--active" : ""}`}>
            {l}
            {k === "coa" && worldState.active_alert && <span className="tab-dot" />}
            {k === "brief" && worldState.todays_disruptions.length > 0 && <span className="tab-dot tab-dot--warn" />}
          </button>
        ))}
      </div>
      <div className="rail-scroll rail-scroll--r">
        {tab === "brief"  && <BriefTab scenario={scenario} worldState={worldState} />}
        {tab === "stock"  && <StockBurnTab scenario={scenario} worldState={worldState} data={data} selectedPost={selectedPost} />}
        {tab === "coa"    && <COATab scenario={scenario} worldState={worldState} />}
        {tab === "routes" && <RoutesTab worldState={worldState} />}
        {tab === "fleet"  && <FleetTab scenario={scenario} worldState={worldState} />}
      </div>
    </aside>
  );
}

// ---------------------------- Brief -----------------------------------
const TYPE_LABELS = {
  vehicle_reliability_signal: "Vehicle reliability signal", weather_minor: "Weather (minor)",
  demand_uplift: "Demand uplift", weather_severe: "Weather (severe)",
  demand_recognition: "System alert", secondary_disruption: "Secondary disruption",
  vehicle_deadline: "Vehicle deadline",
};
const TYPE_TONE = {
  vehicle_reliability_signal: "info", weather_minor: "info", demand_uplift: "info",
  weather_severe: "critical", demand_recognition: "warn",
  secondary_disruption: "warn", vehicle_deadline: "critical",
};
function BriefTab({ scenario, worldState }) {
  const upcoming = scenario.disruption_events.filter(e => e.day > worldState.day).slice(0, 3);
  const sysRec = scenario.system_recommendation_at_day_18 && worldState.day >= 18 ? scenario.system_recommendation_at_day_18 : null;
  return (
    <div className="panel">
      <Section label="Scenario">
        <div className="card">
          <div className="card-title">{scenario.title}</div>
          <p className="prose">{scenario.narrative_one_liner}</p>
          <div className="kv-grid">
            <KV label="Season" value={scenario.season_start} />
            <KV label="Window" value={`${scenario.duration_days} days`} />
          </div>
          <div className="prose subtle">{scenario.weather_assumption}</div>
        </div>
      </Section>

      <Section label={`Today · Day ${worldState.day}`}>
        {worldState.todays_disruptions.length === 0 && (
          <div className="empty">No new disruption events today. Scrub timeline to advance.</div>
        )}
        {worldState.todays_disruptions.map((e, i) => <EventCard key={i} ev={e} />)}
      </Section>

      {sysRec && (
        <Section label="ATTP recommendation · D18">
          <div className="card card--accent">
            <div className="card-title accent">{sysRec.trigger}</div>
            <div className="prose"><span className="lbl">Insight: </span>{sysRec.non_obvious_insight}</div>
            <div className="prose"><span className="lbl">Action: </span>{sysRec.recommended_action}</div>
            <div className="prose subtle"><span className="lbl">Why this matters: </span>{sysRec.operator_value}</div>
          </div>
        </Section>
      )}

      {upcoming.length > 0 && (
        <Section label="Upcoming events">
          <div className="upcoming-list">
            {upcoming.map((e, i) => (
              <div key={i} className="upcoming-row">
                <div className="upcoming-day">D{e.day}</div>
                <div>
                  <div className="upcoming-type">{TYPE_LABELS[e.type] ?? e.type}</div>
                  <div className="upcoming-desc">{e.description}</div>
                </div>
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section label="Starting state">
        <div className="kv-grid">
          {Object.entries(scenario.starting_state).filter(([k,v]) => typeof v !== "object").map(([k, v]) => (
            <KV key={k} label={k.replace(/_/g, " ")} value={String(v)} />
          ))}
        </div>
        {scenario.starting_state.closed_routes_reason && (
          <div className="callout">{scenario.starting_state.closed_routes_reason}</div>
        )}
      </Section>
    </div>
  );
}
function EventCard({ ev }) {
  const tone = TYPE_TONE[ev.type] ?? "info";
  return (
    <div className={`event-card event-card--${tone}`}>
      <div className="event-card-head">
        <span className={`event-tag tag-${tone}`}>{TYPE_LABELS[ev.type] ?? ev.type}</span>
        <span className="event-day">D{ev.day}</span>
      </div>
      <div className="prose">{ev.description}</div>
      {ev.non_obvious_insight && (
        <div className="prose subtle"><span className="lbl">Non-obvious insight: </span>{ev.non_obvious_insight}</div>
      )}
      {ev.fleet_impact && <div className="prose subtle"><span className="lbl">Fleet impact: </span>{ev.fleet_impact}</div>}
      {ev.horizon_impact && <div className="prose subtle"><span className="lbl">Horizon impact: </span>{ev.horizon_impact}</div>}
      {ev.operator_visibility_without_bastion && (
        <div className="provenance-row">
          <span>Visibility without Bastion: </span>
          <span className={`vis-badge vis-${ev.operator_visibility_without_bastion}`}>{ev.operator_visibility_without_bastion}</span>
          {ev.data_source && <span className="src-mono">· src: {ev.data_source}</span>}
        </div>
      )}
    </div>
  );
}

// ---------------------------- Stock & Burn ----------------------------
function StockBurnTab({ scenario, worldState, data, selectedPost }) {
  const fc = scenario.focal_cluster_projection;
  const fp = scenario.focal_post_projection;

  // Build per-day cluster/post stock series for sparkline
  const series = useMemo(() => {
    const arr = [];
    for (let d = 0; d <= scenario.duration_days; d += 2) {
      const ws = computeWorldState(scenario, d);
      let total = 0; ws.post_states.forEach(s => { total += (s.kerosene_stock_L || 0); });
      arr.push(total);
    }
    return arr;
  }, [scenario.scenario_id]);

  const target = selectedPost && worldState.post_states.get(selectedPost.post_id);
  return (
    <div className="panel">
      {fp && (
        <Section label="Focal post · burn model">
          <div className="card">
            <div className="card-title">{fp.post_name} <span className="muted-mono">({fp.post_id})</span></div>
            <div className="kv-grid kv-grid--3">
              <KV label="Headcount" value={fp.headcount} />
              <KV label="Terrain" value={fp.terrain_class} />
              <KV label="Season" value={fp.season} />
            </div>
            {fp.kerosene_burn_calc && <div className="formula">{fp.kerosene_burn_calc}</div>}
            {fp.kerosene_burn_phases && (
              <div className="formula">
                summer (D0–29): {fp.kerosene_burn_phases.summer_days_0_29.daily_burn_L} L/d · {fp.kerosene_burn_phases.summer_days_0_29.calc}<br/>
                winter (D30+): {fp.kerosene_burn_phases.winter_days_30_plus.daily_burn_L} L/d · {fp.kerosene_burn_phases.winter_days_30_plus.calc}
              </div>
            )}
          </div>
        </Section>
      )}
      {fc && (
        <Section label="Focal cluster · burn model">
          <div className="card">
            <div className="card-title">{fc.cluster_name}</div>
            <div className="kv-grid kv-grid--3">
              <KV label="Posts" value={fc.cluster_posts.length} />
              <KV label="Headcount" value={fc.cluster_total_headcount} />
              <KV label="Winter uplift" value={`×${fc.winter_uplift_factor}`} />
            </div>
            <table className="data-table">
              <thead><tr><th>Post</th><th>Hc</th><th>Burn (L/d)</th><th>Calc</th></tr></thead>
              <tbody>
                {Object.entries(fc.daily_burn_L_by_post).map(([k, v]) => (
                  <tr key={k}><td>{k.split("_").slice(1, -1).join(" ")}</td><td>{v.hc}</td><td className="mono">{v.burn_L_per_day}</td><td className="mono subtle">{v.calc}</td></tr>
                ))}
                <tr className="row-total"><td>Total</td><td></td><td className="mono">{fc.cluster_burn_total_L_per_day}</td><td></td></tr>
              </tbody>
            </table>
          </div>
        </Section>
      )}

      <Section label="Cluster stock projection (90d)">
        <div className="card">
          <Sparkline values={series} width={300} height={48} status={worldState.global_worst_status} />
          <div className="formula">{series[0]?.toLocaleString()} L → {series[series.length-1]?.toLocaleString()} L</div>
        </div>
      </Section>

      <Section label="Authored anchor days">
        <div className="anchor-list">
          {Object.entries(fc?.key_projection_days || fp?.key_projection_days || {}).map(([k, pd]) => {
            const d = parseDayKey(k);
            const isCurrent = d === worldState.day;
            const stock = pd.cluster_stock_L ?? pd.kerosene_stock_L ?? pd.kerosene_stock_L_actual;
            const dts = pd.days_to_stockout ?? pd.days_to_stockout_at_current_burn ?? pd.days_to_stockout_summer_burn ?? pd.days_to_stockout_winter_burn ?? pd.days_to_winter_stockout_actual;
            const status = pd.status ? (pd.status === "critical_for_winter_readiness" ? "critical" : pd.status) : "ok";
            return (
              <div key={k} className={`anchor-row ${isCurrent ? "anchor-row--current" : ""}`}>
                <div className="anchor-day">D{d}</div>
                <div className="anchor-body">
                  <div className="anchor-stats">
                    {stock != null && <span className="mono">{stock.toLocaleString()} L</span>}
                    {dts != null && <span className="dts-tag">DTS {dts}d</span>}
                    {pd.status && <StatusPill status={status} size="sm" />}
                  </div>
                  {pd.note && <div className="prose subtle">{pd.note}</div>}
                </div>
              </div>
            );
          })}
        </div>
      </Section>

      {target && (
        <Section label={`Selection · ${target.post_id}`}>
          <div className="card">
            <div className="kv-grid kv-grid--2">
              <KV label="Stock" value={target.kerosene_stock_L != null ? `${target.kerosene_stock_L.toLocaleString()} L` : "—"} />
              <KV label="Daily burn" value={`${Math.round(target.daily_burn_L)} L/d`} />
              <KV label="DTS" value={target.days_to_stockout != null ? `${target.days_to_stockout} d` : "—"} />
              <KV label="Status" value={<StatusPill status={target.status} size="sm" />} />
            </div>
            {target.note && <div className="callout">{target.is_anchor_day ? "Authored: " : ""}{target.note}</div>}
          </div>
        </Section>
      )}
    </div>
  );
}

// ---------------------------- COA -------------------------------------
function COATab({ scenario, worldState }) {
  const alert = worldState.active_alert;
  if (!alert) {
    return (
      <div className="panel">
        <div className="empty">
          <div className="empty-title">No active resupply alert</div>
          <div>Scrub timeline forward to a critical event. S2 alerts at D12, S3 at D10.</div>
        </div>
      </div>
    );
  }
  const card = alert.card;
  const sorted = [...card.options].sort((a, b) => b.risk_P_complete - a.risk_P_complete);
  const best = sorted[0];
  return (
    <div className="panel">
      <Section label={`Resupply COAs · alert raised D${alert.trigger_day}`}>
        <div className="card card--accent">
          <div className="prose">{card.context}</div>
        </div>
      </Section>
      <Section label="Compare options">
        <table className="coa-compare">
          <thead><tr><th>Option</th><th>Tonnes</th><th>Cost ₹L</th><th>Time</th><th>P</th></tr></thead>
          <tbody>
            {card.options.map(o => (
              <tr key={o.option_id} className={o === best ? "row-best" : ""}>
                <td>{o.option_id.split("-").pop()}<span className="muted-mono"> · {o.name.split(" ").slice(0,3).join(" ")}</span></td>
                <td className="mono">{o.tonnes_delivered}</td>
                <td className="mono">{o.cost_INR_lakhs}</td>
                <td className="mono">{o.time_days}d</td>
                <td className="mono"><span className="p-bar"><span style={{ width: `${o.risk_P_complete*100}%` }} /></span> {o.risk_P_complete.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      {card.options.map(o => (
        <Section key={o.option_id} label={o.option_id}>
          <div className="coa-card">
            <div className="coa-head">
              <div>
                <div className="card-title">{o.name}</div>
                <div className="prose subtle">{o.plan}</div>
              </div>
              {o === best && <span className="recommend-tag">Highest P</span>}
            </div>
            <div className="kv-grid kv-grid--4">
              <KV label="Tonnes" value={o.tonnes_delivered} />
              <KV label="Cost" value={`₹${o.cost_INR_lakhs} L`} />
              <KV label="Time" value={`${o.time_days} d`} />
              <KV label="P(complete)" value={o.risk_P_complete.toFixed(2)} />
            </div>
            {o.cost_breakdown && <div className="formula"><span className="lbl">Cost: </span>{o.cost_breakdown}</div>}
            {o.tonnes_breakdown && <div className="formula"><span className="lbl">Tonnes: </span>{o.tonnes_breakdown}</div>}
            <div className="prose"><span className="lbl">Risk: </span>{o.risk_drivers}</div>
            <div className="prose"><span className="lbl">Why: </span>{o.why_recommended}</div>
            <div className="coa-actions">
              <button className="btn btn-primary">Recommend to Brigadier</button>
              <button className="btn btn-ghost">Show lineage</button>
            </div>
          </div>
        </Section>
      ))}
      <Section label="Tradeoff summary">
        <div className="callout">{card.tradeoff_summary}</div>
        <div className="prose subtle">Decision support · the system does not pick. The Brigadier picks.</div>
      </Section>
    </div>
  );
}

// ---------------------------- Routes ----------------------------------
const ROUTES = [
  { id: "LOC-WEST_ZOJILA", name: "Western LoC · Srinagar–Zoji La–Kargil–Leh", km: 434, chokepoint: "Zoji La 3528m", season: "Closed Dec–Apr · open May–Nov", drivers: "snow_avalanche_dec_apr · heavy_snowfall_nov", grade: "A" },
  { id: "LOC-SOUTH_MANALI", name: "Southern LoC · Manali–Atal–Baralacha–Taglang–Leh", km: 472, chokepoint: "Taglang La 5359m", season: "Open May–Oct only", drivers: "multi-pass winter closure", grade: "A" },
  { id: "LOC-AIR_LEH", name: "Air Bridge · Hindon/Chandigarh→Leh KBR", km: 720, chokepoint: "VILH wx", season: "Year-round, weather-constrained", drivers: "winter clear-wx avail ~0.75–0.78", grade: "A", costX: "5–10× road" },
  { id: "EDGE-KARU-DBO", name: "DSDBO · Karu–Murgo–DBO", km: 255, chokepoint: "Saser Brangsa · Shyok crossings", season: "Open ~May–early-Nov", drivers: "Shyok river · winter snow", grade: "A" },
  { id: "EDGE-KARU-CHUSHUL", name: "Karu–Chang La–Chushul", km: 165, chokepoint: "Chang La 5360m", season: "Open Apr–Nov typical", drivers: "Chang La snow", grade: "A" },
  { id: "EDGE-HANLE-DEMCHOK", name: "Hanle–Demchok", km: 70, chokepoint: "Indus crossings", season: "Open year-round (low traffic winter)", drivers: "snow patches", grade: "B" },
];
function RoutesTab({ worldState }) {
  return (
    <div className="panel">
      <Section label="Strategic axes">
        <div className="route-list">
          {ROUTES.map(r => {
            let status = "ok";
            if (r.id === "LOC-SOUTH_MANALI" && worldState.closed_loc_ids.has(r.id)) status = "imminent";
            if (r.id === "LOC-WEST_ZOJILA" && (worldState.closed_edge_ids.has("EDGE-ZOJI-LEH") || worldState.closed_edge_ids.has("EDGE-ZOJI-KARGIL"))) status = "imminent";
            return (
              <div key={r.id} className="route-card">
                <div className="route-head">
                  <div>
                    <div className="card-title">{r.name}</div>
                    <div className="muted-mono">{r.id} · {r.km} km</div>
                  </div>
                  <StatusPill status={status === "imminent" ? "imminent" : "ok"} size="sm" />
                </div>
                <div className="kv-grid kv-grid--2">
                  <KV label="Key chokepoint" value={r.chokepoint} />
                  <KV label="Seasonal" value={r.season} />
                  <KV label="Closure drivers" value={r.drivers} />
                  <KV label="Provenance" value={<span className="muted-mono">grade {r.grade}</span>} />
                </div>
                {r.costX && <div className="formula">Cost vs road: {r.costX}</div>}
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
}

// ---------------------------- Fleet -----------------------------------
const VEHICLES = [
  { id: "VEH-STALLION", name: "Stallion 4×4 (AL 7.5T)", payload: "7.5 t", derate5k: "0.82×", reliab: "0.8 / 1.4 / 1.8 / 3.5", cost: "1.0×", surf: "paved · unpaved · track" },
  { id: "VEH-TOPAZ", name: "Topaz 6×6 (AL 10T)", payload: "10 t", derate5k: "0.78×", reliab: "1.0 / 1.8 / 2.2 / 4.5", cost: "1.2×", surf: "paved · unpaved · track" },
  { id: "VEH-MI17", name: "Mi-17 V5 helo", payload: "4 t (sea-lvl) → 1.8 t (DBO)", derate5k: "0.45×", reliab: "wx-avail 0.78 (winter)", cost: "9.0×", surf: "air corridor" },
  { id: "VEH-C17", name: "C-17 strategic lift", payload: "70 t (Hindon→Leh ≈55 t)", derate5k: "n/a", reliab: "wx-avail 0.75 (winter Leh)", cost: "8.5×", surf: "air corridor" },
  { id: "VEH-MULE", name: "Mule pack train", payload: "70 kg/animal", derate5k: "0.85×", reliab: "avail 0.95 summer · 0.6 winter", cost: "3.0×", surf: "track · foot" },
];
function FleetTab({ scenario, worldState }) {
  const dl = scenario.disruption_events.filter(e => e.type === "vehicle_deadline" && e.day <= worldState.day);
  return (
    <div className="panel">
      <Section label="Deadlines today">
        {dl.length === 0 ? (
          <div className="empty">No vehicle deadlines this scenario yet.</div>
        ) : (
          <div className="dl-list">
            {dl.map((e, i) => (
              <div key={i} className="dl-row">
                <div className="dl-day">D{e.day}</div>
                <div>
                  <div className="prose">{e.description}</div>
                  {e.fleet_impact && <div className="prose subtle">{e.fleet_impact}</div>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Section>
      <Section label="Vehicle classes">
        <table className="data-table">
          <thead><tr><th>Class</th><th>Payload</th><th>Derate@5km</th><th>Reliability prior (s/w paved · unpaved)</th><th>Cost</th></tr></thead>
          <tbody>
            {VEHICLES.map(v => (
              <tr key={v.id}>
                <td>
                  <div className="row-strong">{v.name}</div>
                  <div className="muted-mono">{v.id} · {v.surf}</div>
                </td>
                <td className="mono">{v.payload}</td>
                <td className="mono">{v.derate5k}</td>
                <td className="mono">{v.reliab}</td>
                <td className="mono">{v.cost}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="prose subtle"><span className="lbl">Reliability units: </span>deadlines per 1000 vehicle-km. Lower is better. The DBO axis (unpaved, winter) is the dominant deadline driver — see S3.</div>
      </Section>
    </div>
  );
}

// ---------------------------- Helpers ---------------------------------
function Section({ label, children }) {
  return <div className="section"><div className="section-label">{label}</div>{children}</div>;
}
function KV({ label, value }) {
  return (
    <div className="kv">
      <div className="kv-l">{label}</div>
      <div className="kv-v">{value}</div>
    </div>
  );
}

// =====================================================================
// Bottom — Timeline scrubber
// =====================================================================
function TimelineDock({ scenario, worldState, day, onDayChange }) {
  const pct = (day / worldState.duration_days) * 100;
  const anchors = useMemo(() => {
    const set = new Set();
    if (scenario.focal_post_projection) Object.keys(scenario.focal_post_projection.key_projection_days).forEach(k => { const d = parseDayKey(k); if (d != null) set.add(d); });
    if (scenario.focal_cluster_projection) Object.keys(scenario.focal_cluster_projection.key_projection_days).forEach(k => { const d = parseDayKey(k); if (d != null) set.add(d); });
    return [...set].sort((a, b) => a - b);
  }, [scenario.scenario_id]);
  return (
    <div className="dock">
      <div className="dock-l">
        <button className="step-btn" onClick={() => onDayChange(Math.max(0, day - 1))} aria-label="Step back">‹</button>
        <button className="step-btn" onClick={() => onDayChange(Math.min(worldState.duration_days, day + 1))} aria-label="Step forward">›</button>
        <div className="dock-day">Day <span className="dock-day-n">{String(day).padStart(2,"0")}</span> / {worldState.duration_days}</div>
      </div>
      <div className="dock-track-wrap">
        <div className="dock-track-rail">
          {anchors.map(d => (
            <div key={`a${d}`} className="anchor-tick" style={{ left: `${(d / worldState.duration_days) * 100}%` }} title={`Anchor day ${d}`} />
          ))}
          {scenario.disruption_events.map((e, i) => (
            <div key={`e${i}`} className={`event-tick event-tick--${TYPE_TONE[e.type] ?? "info"}`} style={{ left: `${(e.day / worldState.duration_days) * 100}%` }} title={`D${e.day}: ${e.description}`}>
              <div className="event-tick-pin" />
              <div className="event-tick-label">D{e.day}</div>
            </div>
          ))}
          <div className="dock-track-fill" style={{ width: `${pct}%` }} />
          <div className="dock-track-thumb" style={{ left: `${pct}%` }} />
          <input type="range" min="0" max={worldState.duration_days} step="1" value={day}
            onChange={e => onDayChange(parseInt(e.target.value, 10))} className="dock-range" />
        </div>
        <div className="dock-axis">
          <span>D0</span><span>D15</span><span>D30</span><span>D45</span><span>D60</span><span>D75</span><span>D90</span>
        </div>
      </div>
      <div className="dock-r">
        <button className="step-btn" onClick={() => {
          const next = anchors.find(d => d > day) ?? anchors[0]; if (next != null) onDayChange(next);
        }}>Next anchor</button>
        <button className="step-btn" onClick={() => {
          const next = scenario.disruption_events.find(e => e.day > day) ?? scenario.disruption_events[0];
          if (next) onDayChange(next.day);
        }}>Next event</button>
      </div>
    </div>
  );
}

// =====================================================================
// Today's events banner (over map)
// =====================================================================
function MapBanner({ events }) {
  if (!events.length) return null;
  return (
    <div className="map-banner">
      {events.map((e, i) => {
        const tone = TYPE_TONE[e.type] ?? "info";
        return (
          <div key={i} className={`banner-card banner-${tone}`}>
            <span className={`event-tag tag-${tone}`}>D{e.day} · {TYPE_LABELS[e.type] ?? e.type}</span>
            <span className="banner-text">{e.description}</span>
          </div>
        );
      })}
    </div>
  );
}

// =====================================================================
// Root
// =====================================================================
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "showProvenance": false,
  "denseRail": false
}/*EDITMODE-END*/;

function App() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [scenarioId, setScenarioId] = useState("SCEN-02-ZOJI_LA_CASCADE");
  const [day, setDay] = useState(12);
  const [selectedPostId, setSelectedPostId] = useState(null);
  const [tweaks, setTweak] = window.useTweaks(TWEAK_DEFAULTS);

  useEffect(() => {
    Promise.all([
      fetch("data/fsp/posts.json").then(r => r.json()),
      fetch("data/fsp/scenarios.json").then(r => r.json()),
    ]).then(([posts, scenarios]) => setData({ posts, scenarios }))
      .catch(e => setError(String(e)));
  }, []);

  const scenario = data ? data.scenarios.scenarios.find(s => s.scenario_id === scenarioId) : null;
  const worldState = useMemo(() => scenario ? computeWorldState(scenario, day) : null, [scenario, day]);
  const selectedPost = data && selectedPostId ? data.posts.posts.find(p => p.post_id === selectedPostId) : null;

  if (error) return <div style={{ padding: 24, color: "#dc2626" }}>Error: {error}</div>;
  if (!data || !worldState) {
    return (
      <div className="shell">
        <TopBar scenarios={[]} scenarioId="" onSelect={() => {}} worldState={null} />
        <div className="loading">Loading FSP data…</div>
      </div>
    );
  }

  return (
    <div className="shell">
      <TopBar scenarios={data.scenarios.scenarios} scenarioId={scenarioId}
        onSelect={(id) => { setScenarioId(id); setDay(id === "SCEN-02-ZOJI_LA_CASCADE" ? 12 : id === "SCEN-03-VEHICLE_DEADLINE_CASCADE" ? 10 : 18); setSelectedPostId(null); }}
        worldState={worldState} />
      <div className="body">
        <PostsRail data={data} worldState={worldState} selectedId={selectedPostId} onSelect={setSelectedPostId} />
        <main className="canvas">
          <MapBanner events={worldState.todays_disruptions} />
          <div className="map-frame">
            <MapView data={data} worldState={worldState}
              selectedPostId={selectedPostId} onSelectPost={setSelectedPostId}
              showProvenance={tweaks.showProvenance} />
          </div>
        </main>
        <AnalystPanel scenario={scenario} worldState={worldState} data={data} selectedPost={selectedPost} />
      </div>
      <TimelineDock scenario={scenario} worldState={worldState} day={day} onDayChange={setDay} />

      <window.TweaksPanel title="Tweaks">
        <window.TweakSection title="Demo state">
          <window.TweakSelect label="Scenario" value={scenarioId}
            options={data.scenarios.scenarios.map(s => ({ value: s.scenario_id, label: SHORT_TITLES[s.scenario_id] }))}
            onChange={(v) => setScenarioId(v)} />
          <window.TweakSlider label={`Day ${day} / ${worldState.duration_days}`}
            min={0} max={worldState.duration_days} step={1} value={day}
            onChange={(v) => setDay(v)} />
        </window.TweakSection>
        <window.TweakSection title="Display">
          <window.TweakToggle label="Show provenance grades on map" value={tweaks.showProvenance}
            onChange={(v) => setTweak("showProvenance", v)} />
          <window.TweakToggle label="Dense rail" value={tweaks.denseRail}
            onChange={(v) => setTweak("denseRail", v)} />
        </window.TweakSection>
      </window.TweaksPanel>
    </div>
  );
}

window.App = App;
