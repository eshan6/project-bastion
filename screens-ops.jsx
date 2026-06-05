// Bastion — operational screens.

const { useState: useStateOps, useMemo: useMemoOps } = React;

// ════════════════════════════════════════════════════════════════════ OVERVIEW
function OverviewScreen({ openLineage }) {
  const B = window.B;
  const totals = B.alert_totals;
  const opt = B.models.find((m) => m.kind === "optimizer").metrics;
  const risk = B.models.find((m) => m.kind === "risk_evaluator").metrics;

  return (
    <Page
      eyebrow={`Snapshot ${B.snapshot.as_of_date} · canonical · stage3-v1.0 · stage4-v1.0`}
      title="Operational overview"
      sub="Forecasts, risks, and four plan alternatives for the 14-day window ending 2024-12-29. All numbers are computed against the frozen Stage 2 world (seed=42). Re-running training produces byte-identical outputs."
      actions={
        <>
          <button className="btn" type="button"><Icon d={Icons.external} size={12}/>Export snapshot</button>
          <button className="btn primary" type="button"><Icon d={Icons.zap} size={12}/>Replan now</button>
        </>
      }
    >
      {/* The load-bearing finding */}
      <Callout
        tone="crit"
        title={`${opt.coverage_best_road_pct.toFixed(1)}% achievable road coverage — ${opt.posts_road_isolated} of ${opt.posts_at_risk} at-risk posts are road-isolated at the planning horizon.`}
        actions={
          <>
            <button className="btn sm" type="button">View isolated posts</button>
            <button className="btn sm" type="button">Inspect Stage 4 diagnostics</button>
          </>
        }
      >
        The optimizer refuses to promise undeliverable convoys. Zoji La path-open ≈ <b>0.29</b>, Chang La ≈ <b>0.21</b>; posts behind a 3-pass chain compound to <b>0.037</b>. The uncovered 68% is not a stock problem (depots are full) or a truck problem (capacity is slack) — it is a <b>reachability</b> problem. The lever is convoys-before-closure, not more inventory.
      </Callout>

      <div className="kpi-banner">
        <Stat
          label="Open alerts"
          value={totals.total}
          sub={`${totals.stockout_risk.total} stockout · ${totals.disruption.total} disruption · ${totals.vehicle_deadline.total} vehicle`}
          tone="critical"
          icon={Icons.alert}
        />
        <Stat
          label="Tier-1 alerts fired"
          value={128}
          sub="All on RAT-005 (Fresh Meat) — single SKU, late-winter thin attainment."
          icon={Icons.risk}
        />
        <Stat
          label="Posts at risk"
          value={`${opt.posts_at_risk}`}
          unit={`/ ${B.snapshot.row_counts.posts}`}
          sub={`${opt.posts_road_isolated} road-isolated · ${opt.posts_at_risk - opt.posts_road_isolated} reachable`}
          icon={Icons.map}
        />
        <Stat
          label="Stage 4 solve"
          value={`${opt.solve_time_s.toFixed(1)}s`}
          sub={`${opt.plan_count} plans · last tick 9m ago`}
          icon={Icons.plans}
        />
      </div>

      <div className="split-2 mt-3">
        {/* Left: alerts breakdown */}
        <Card
          title="Alerts by type"
          actions={<button className="btn ghost sm" type="button" onClick={() => window.__setRoute("alerts")}>View all <Icon d={Icons.chevronR} size={11}/></button>}
          padded={false}
        >
          <div style={{ padding: "12px 16px" }}>
            <AlertBreakdownRow label="Stockout risk"      total={totals.stockout_risk}    color="var(--crit)"/>
            <AlertBreakdownRow label="Route disruption"   total={totals.disruption}       color="var(--warn)"/>
            <AlertBreakdownRow label="Vehicle deadline"   total={totals.vehicle_deadline} color="var(--info)"/>
          </div>
        </Card>

        {/* Right: coverage gauge */}
        <Card title="Best achievable road coverage" sub="Plan: balanced · Horizon: 14d · Reserve: 7d">
          <Gauge value={31.7} label="of priority-kg of P90 demand can be covered by road" tone="crit" />
          <div className="coverage-stripe">
            <i style={{ width: "31.7%", background: "var(--ok)" }} />
            <i style={{ width: "68.3%", background: "var(--crit)" }} />
          </div>
          <div className="mt-2" style={{ display: "flex", justifyContent: "space-between", fontSize: 11.5, color: "var(--ink-muted)" }}>
            <span><b style={{ color: "var(--ok)" }}>31.4 t</b> delivered</span>
            <span><b style={{ color: "var(--crit)" }}>67.8 t</b> surfaced shortfall</span>
          </div>
        </Card>
      </div>

      <div className="split-2 mt-3">
        {/* Top recent alerts */}
        <Card
          title="Top critical alerts"
          count={9}
          actions={<button className="btn ghost sm" type="button" onClick={() => window.__setRoute("alerts")}>All alerts <Icon d={Icons.chevronR} size={11}/></button>}
          padded={false}
        >
          {B.alerts.filter((a) => a.severity === "critical").slice(0, 5).map((a) => (
            <CompactAlertRow key={a.alert_id} alert={a} onClick={() => openLineage("alert", a)} />
          ))}
        </Card>

        <div className="stack">
          <Card title="Plans for this snapshot" actions={
            <button className="btn ghost sm" type="button" onClick={() => window.__setRoute("plans")}>Compare <Icon d={Icons.chevronR} size={11}/></button>
          } padded={false}>
            <table className="tbl">
              <thead>
                <tr>
                  <th>Objective</th>
                  <th className="num">Cost</th>
                  <th className="num">Time</th>
                  <th className="num">P(disrupt)</th>
                  <th className="num">Vehicles</th>
                </tr>
              </thead>
              <tbody>
                {B.plans.map((p) => (
                  <tr key={p.plan_id} onClick={() => window.__setRoute("plans")}>
                    <td><Tag tone="accent">{p.objective}</Tag></td>
                    <td className="num">{fmtCur(p.total_cost)}</td>
                    <td className="num">{fmtHours(p.total_time_hours)}</td>
                    <td className="num">{fmtPct(p.aggregate_risk)}</td>
                    <td className="num">{p.vehicles_tasked}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card title="Model versions on this snapshot">
            {B.models.map((m, i) => (
              <div key={i} style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", padding: "5px 0", borderTop: i ? "1px solid var(--line)" : "none" }}>
                <div>
                  <div style={{ fontSize: 12.5, fontWeight: 500 }}>{m.kind}</div>
                  <div style={{ fontSize: 11, color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{m.name} · git {m.git_sha}</div>
                </div>
                <Tag>{m.slices} {m.slices === 1 ? "model" : "slices"}</Tag>
              </div>
            ))}
          </Card>
        </div>
      </div>
    </Page>
  );
}

function AlertBreakdownRow({ label, total, color }) {
  const max = 128;
  const w = (n) => `${Math.min(100, (n / max) * 100)}%`;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "150px 1fr 60px 60px 60px", gap: 12, alignItems: "center", padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
      <div style={{ fontSize: 13 }}>{label}</div>
      <div style={{ position: "relative", height: 8, background: "var(--surface-alt)", borderRadius: 999, overflow: "hidden", display: "flex" }}>
        <i style={{ display: "block", height: "100%", width: w(total.critical), background: "var(--crit)" }} />
        <i style={{ display: "block", height: "100%", width: w(total.warning),  background: "var(--warn)" }} />
        <i style={{ display: "block", height: "100%", width: w(total.info),     background: "var(--info)" }} />
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--crit)", textAlign: "right" }}>{total.critical}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--warn)", textAlign: "right" }}>{total.warning}</div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600, textAlign: "right" }}>{total.total}</div>
    </div>
  );
}

function CompactAlertRow({ alert, onClick }) {
  const sevChar = alert.severity === "critical" ? "!" : alert.severity === "warning" ? "▲" : "i";
  return (
    <div className="alert-row" onClick={onClick} style={{ gridTemplateColumns: "32px 130px 1fr 110px" }}>
      <div className={`alert-sev ${alert.severity}`}>{sevChar}</div>
      <div><span className={`alert-type-tag ${alert.alert_type}`}>{alert.alert_type}</span></div>
      <div className="alert-msg" style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{alert.message}</div>
      <div className="alert-meta">{alert.created_at.slice(11, 16)}</div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════ ALERTS
function AlertsScreen({ openLineage }) {
  const B = window.B;
  const [typeFilter, setTypeFilter] = useStateOps("all");
  const [sevFilter, setSevFilter]   = useStateOps("all");
  const [q, setQ] = useStateOps("");

  const filtered = B.alerts.filter((a) =>
    (typeFilter === "all" || a.alert_type === typeFilter) &&
    (sevFilter === "all" || a.severity === sevFilter) &&
    (q === "" || a.message.toLowerCase().includes(q.toLowerCase()))
  );

  const totals = B.alert_totals;

  return (
    <Page
      eyebrow={`bastion.alert · snapshot ${B.snapshot.as_of_date}`}
      title="Alerts"
      sub="3 alert types from 3 Stage 3 predictions. Stockout-risk severity is set from worst-case predicted status + tier. Disruption fires when P(closed) > 0.60 in the 7d window. Vehicle deadline fires when P(deadline) > 5% over 7d."
      actions={
        <>
          <button className="btn" type="button"><Icon d={Icons.external} size={12}/>Export CSV</button>
          <button className="btn" type="button">Acknowledge all</button>
        </>
      }
    >
      <Card padded={false}>
        <div className="filterbar">
          <div className="filter-group">
            <span>Type</span>
            <Segmented value={typeFilter} onChange={setTypeFilter} options={[
              { value: "all",              label: "All", count: totals.total },
              { value: "stockout_risk",    label: "Stockout",  count: totals.stockout_risk.total },
              { value: "disruption",       label: "Disruption",count: totals.disruption.total },
              { value: "vehicle_deadline", label: "Vehicle",   count: totals.vehicle_deadline.total },
            ]} />
          </div>
          <div className="filter-group">
            <span>Severity</span>
            <Segmented value={sevFilter} onChange={setSevFilter} options={[
              { value: "all", label: "All" },
              { value: "critical", label: "Critical" },
              { value: "warning",  label: "Warning" },
              { value: "info",     label: "Info" },
            ]} />
          </div>
          <div className="spacer" />
          <Search value={q} onChange={setQ} placeholder="Search message, post, vehicle…" />
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "32px 140px 1fr 130px 110px 70px", gap: 12, padding: "8px 16px", background: "var(--surface)", borderBottom: "1px solid var(--line)", fontSize: 10.5, fontWeight: 600, color: "var(--ink-faint)", letterSpacing: "0.05em", textTransform: "uppercase" }}>
          <div></div>
          <div>Type</div>
          <div>Message</div>
          <div>Trigger</div>
          <div>Created</div>
          <div></div>
        </div>

        {filtered.length === 0 ? (
          <div className="empty">
            <div className="empty-icon">∅</div>
            No alerts match these filters.
          </div>
        ) : (
          filtered.map((a) => (
            <AlertRow key={a.alert_id} alert={a} onClick={() => openLineage("alert", a)} />
          ))
        )}
      </Card>

      <div className="mt-3" style={{ fontSize: 11, color: "var(--ink-faint)" }}>
        Showing <b style={{ color: "var(--ink)" }}>{filtered.length}</b> of <b style={{ color: "var(--ink)" }}>{totals.total}</b> alerts. The remaining 119 stockout-risk alerts are warning-severity RAT-005 rationing predictions across the same forward + mid posts; they're grouped here for brevity.
      </div>
    </Page>
  );
}

function AlertRow({ alert, onClick }) {
  const sevChar = alert.severity === "critical" ? "!" : alert.severity === "warning" ? "▲" : "i";
  return (
    <div className="alert-row" onClick={onClick}>
      <div className={`alert-sev ${alert.severity}`}>{sevChar}</div>
      <div><span className={`alert-type-tag ${alert.alert_type}`}>{alert.alert_type}</span></div>
      <div className="alert-msg">{alert.message}</div>
      <div className="alert-meta">
        {alert.trigger_metric} = <b style={{ color: "var(--ink)" }}>{
          typeof alert.trigger_value === "number" && alert.trigger_value < 1 && alert.trigger_value > 0
            ? alert.trigger_metric.includes("days") ? alert.trigger_value.toFixed(2) : (alert.trigger_value * 100).toFixed(1) + "%"
            : alert.trigger_value
        }</b>
      </div>
      <div className="alert-meta">{alert.created_at.slice(5, 16)}</div>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <Icon d={Icons.chevronR} size={12} />
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════ PLANS
function PlansScreen({ openLineage, day }) {
  const B = window.B;
  const [selectedPlan, setSelectedPlan] = useStateOps("PL-COST-2024-12-15");
  const plan = B.plans.find((p) => p.plan_id === selectedPlan);
  const legs = B.plan_legs[selectedPlan] || B.plan_legs["PL-COST-2024-12-15"];

  return (
    <Page
      eyebrow={`bastion.resupply_plan · snapshot ${B.snapshot.as_of_date} · horizon 14d`}
      title="Resupply plans"
      sub="OR-Tools CBC MIP with lexicographic coverage objective. Plans on worst-case (P90) demand; dispatches anticipatorily. Same coverage, different routing + vehicle picks. Warm-started from min_cost; total solve time 1.4s."
      actions={
        <>
          <button className="btn" type="button"><Icon d={Icons.external} size={12}/>Export PDF</button>
          <button className="btn primary" type="button"><Icon d={Icons.zap} size={12}/>Re-run</button>
        </>
      }
    >
      <Callout
        tone="crit"
        title="All four plans cover the same 31.4 t — the rest is physically unreachable by road at horizon 14d."
      >
        Coverage is lexicographically dominant in the objective, so every plan covers everything it physically can. Plans differentiate only on the secondary penalty: <b>min_cost</b> spreads onto cheap light trucks, <b>min_time</b> consolidates onto faster trucks, <b>min_risk</b> picks the fleet's most-reliable BharatBenz-HD's. <b>{plan.shortfall_t.toFixed(1)} t</b> remains as surfaced shortfall — Stage 4 flags it explicitly rather than failing silently.
      </Callout>

      <div className="plans-grid mt-3">
        {B.plans.map((p) => (
          <PlanCard
            key={p.plan_id}
            plan={p}
            selected={p.plan_id === selectedPlan}
            onSelect={() => setSelectedPlan(p.plan_id)}
            superlatives={superlative(p, B.plans)}
          />
        ))}
      </div>

      <div className="mt-3">
        <Card
          title={`Legs of ${plan.objective}`}
          count={legs.length}
          sub={`Total cost ${fmtCur(plan.total_cost)} · Total time ${fmtHours(plan.total_time_hours)} · Aggregate P(>=1 leg fails) ${(plan.aggregate_risk * 100).toFixed(1)}% · ${plan.expected_disrupted_legs.toFixed(1)} expected disrupted legs`}
          actions={<Tag tone="accent">{plan.plan_id}</Tag>}
          padded={false}
        >
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th style={{ width: 36 }}>#</th>
                  <th>Vehicle</th>
                  <th>Class</th>
                  <th>Route</th>
                  <th>SKU</th>
                  <th className="num">Qty</th>
                  <th>Depart</th>
                  <th className="num">Cost</th>
                  <th className="num">P(open)</th>
                  <th className="num">Leg risk</th>
                </tr>
              </thead>
              <tbody>
                {legs.map((l) => {
                  const fromName = (B.depots.find(d => d.depot_id === l.from) || B.posts.find(p => p.post_id === l.from))?.name || l.from;
                  const toName   = (B.depots.find(d => d.depot_id === l.to)   || B.posts.find(p => p.post_id === l.to))?.name   || l.to;
                  return (
                    <tr key={l.seq}>
                      <td className="mono muted">{l.seq}</td>
                      <td className="mono">{l.vehicle_id}</td>
                      <td><Tag>{l.vehicle_class}</Tag></td>
                      <td>
                        <span style={{ fontFamily: "var(--font-mono)", color: "var(--ink-muted)", fontSize: 11.5 }}>{l.route_id}</span>
                        <div style={{ fontSize: 11.5, color: "var(--ink-muted)", marginTop: 1 }}>{fromName} → {toName}</div>
                      </td>
                      <td className="mono">{l.sku_id}</td>
                      <td className="num">{l.qty.toLocaleString()}</td>
                      <td className="mono">{l.depart_date}</td>
                      <td className="num">{fmtCur(l.expected_cost)}</td>
                      <td className="num"><span style={{ color: l.path_open >= 0.7 ? "var(--ok)" : l.path_open >= 0.4 ? "var(--warn)" : "var(--crit)" }}>{fmtPctI(l.path_open)}</span></td>
                      <td className="num"><span style={{ color: l.expected_risk <= 0.2 ? "var(--ok)" : l.expected_risk <= 0.6 ? "var(--warn)" : "var(--crit)" }}>{fmtPct(l.expected_risk)}</span></td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan="5">Plan totals</td>
                  <td className="num">{legs.reduce((s, l) => s + l.qty, 0).toLocaleString()}</td>
                  <td></td>
                  <td className="num">{fmtCur(legs.reduce((s, l) => s + l.expected_cost, 0))}</td>
                  <td colSpan="2"></td>
                </tr>
              </tfoot>
            </table>
          </div>
        </Card>
      </div>

      <div className="mt-3">
        <Card title="Surfaced shortfall · road-isolated posts" count={15} sub="Posts whose path availability fell below PATH_FEASIBILITY_MIN=0.05 at the planning horizon. The optimizer cannot drive there; deficit becomes shortfall (air-resupply flagged where available).">
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Post</th>
                  <th>Axis</th>
                  <th>Path</th>
                  <th className="num">P(path open)</th>
                  <th className="num">Deficit (t)</th>
                  <th>Air-resupply?</th>
                </tr>
              </thead>
              <tbody>
                {[
                  ["POST-001","DBO Base","DBO","Khardung La → Saser La",0.038,8.2,true],
                  ["POST-003","Saser Brangsa","DBO","Khardung La → Saser La",0.038,3.4,true],
                  ["POST-004","Burtse","DBO","Khardung La → Saser La",0.038,2.6,false],
                  ["POST-006","PP-14 Galwan","DBO","Khardung La → Chang La",0.137,5.8,false],
                  ["POST-013","Rezang La OP","Chushul","Chang La",0.210,2.1,false],
                  ["POST-015","Marsimik La OP","Pangong","Chang La → Marsimik La",0.032,0.9,false],
                  ["POST-028","Tiger Hill OP","western","Zoji La",0.290,2.0,false],
                  ["POST-029","Tololing OP","western","Zoji La",0.290,1.9,false],
                  ["POST-032","Indira Col OP","Siachen","—",0.000,1.4,true],
                  ["POST-033","Bana Post","Siachen","—",0.000,1.1,true],
                  ["POST-034","Sonam Post","Siachen","—",0.000,1.0,true],
                  ["POST-035","Kumar Post","Siachen","—",0.000,1.1,true],
                ].map((r) => (
                  <tr key={r[0]}>
                    <td className="mono">{r[0]}</td>
                    <td className="muted">{r[2]}</td>
                    <td className="muted">{r[3]}</td>
                    <td className="num"><span style={{ color: r[4] < 0.05 ? "var(--crit)" : "var(--warn)" }}>{(r[4] * 100).toFixed(1)}%</span></td>
                    <td className="num">{r[5].toFixed(1)}</td>
                    <td>{r[6] ? <Tag tone="ok">supported</Tag> : <Tag tone="crit">no</Tag>}</td>
                  </tr>
                ))}
                <tr><td colSpan="6" className="muted" style={{ textAlign: "center", padding: 10 }}>+ 3 more rationing-only posts inside reach</td></tr>
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </Page>
  );
}

function superlative(plan, all) {
  const tags = [];
  if (plan.total_cost === Math.min(...all.map(p => p.total_cost))) tags.push({ tone: "ok", label: "Lowest cost" });
  if (plan.total_time_hours === Math.min(...all.map(p => p.total_time_hours))) tags.push({ tone: "ok", label: "Fastest" });
  if (plan.aggregate_risk === Math.min(...all.map(p => p.aggregate_risk))) tags.push({ tone: "ok", label: "Lowest risk" });
  return tags;
}

function PlanCard({ plan, selected, onSelect, superlatives }) {
  return (
    <div className={`plan-card ${selected ? "selected" : ""}`} onClick={onSelect}>
      <div className="plan-card-head">
        <div className="plan-card-obj">{plan.objective}</div>
        <div className="plan-card-name">
          <span>
            {plan.objective === "min_cost" && "Lowest cost"}
            {plan.objective === "min_time" && "Fastest delivery"}
            {plan.objective === "min_risk" && "Lowest risk"}
            {plan.objective === "balanced" && "Balanced"}
          </span>
          {superlatives[0] && <Tag tone={superlatives[0].tone}>{superlatives[0].label}</Tag>}
        </div>
      </div>
      <div className="plan-card-body">
        <div className="plan-row"><span className="lbl">Total cost</span><span className="val">{fmtCur(plan.total_cost)}</span></div>
        <div className="plan-row"><span className="lbl">Total time</span><span className="val">{fmtHours(plan.total_time_hours)}</span></div>
        <div className="plan-row"><span className="lbl">Aggregate risk</span><span className="val">{(plan.aggregate_risk * 100).toFixed(1)}%</span></div>
        <div className="plan-row"><span className="lbl">Expected disrupted legs</span><span className="val">{plan.expected_disrupted_legs.toFixed(1)}</span></div>
        <hr className="divider" style={{ margin: "4px 0" }} />
        <div className="plan-row"><span className="lbl">Coverage</span><span className="val">{plan.coverage_pct.toFixed(1)}%</span></div>
        <div className="plan-row"><span className="lbl">Vehicles tasked</span><span className="val">{plan.vehicles_tasked}</span></div>
        <div className="plan-row"><span className="lbl">Legs</span><span className="val">{plan.legs_planned}</span></div>
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 10.5, color: "var(--ink-faint)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 4 }}>Vehicle mix</div>
          <div style={{ display: "flex", gap: 4, fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--ink-muted)", flexWrap: "wrap" }}>
            {Object.entries(plan.vehicle_mix).filter(([, n]) => n > 0).map(([k, v]) => (
              <Tag key={k}>{k.replace("Stallion-", "S-").replace("BharatBenz-HD", "BB-HD")} ×{v}</Tag>
            ))}
          </div>
        </div>
      </div>
      <div className="plan-card-foot">
        <button className="btn sm" type="button" onClick={(e) => e.stopPropagation()}>Inspect</button>
        <button className={`btn sm ${selected ? "primary" : ""}`} type="button">{selected ? "Selected ✓" : "Select"}</button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════ RISK INSPECTOR
function RiskScreen({ openLineage, day }) {
  const B = window.B;
  const [head, setHead] = useStateOps("all");
  const [tier, setTier] = useStateOps("all");
  const [firedOnly, setFiredOnly] = useStateOps(true);
  const [q, setQ] = useStateOps("");
  const [selected, setSelected] = useStateOps(null);

  const filtered = B.stockout_risk.filter((r) =>
    (head === "all" || r.head === head) &&
    (tier === "all" || r.tier === parseInt(tier, 10)) &&
    (!firedOnly || r.tier_alert_fired) &&
    (q === "" || (r.post_id + r.sku).toLowerCase().includes(q.toLowerCase()))
  );

  return (
    <Page
      eyebrow={`bastion.stockout_risk · snapshot ${B.snapshot.as_of_date} · horizon 14d`}
      title="Risk inspector"
      sub="Composed risk objects per (post, SKU, horizon). 4,200 rows total; showing 14-day horizon. Stage 3 risk_scorer composes demand-forecast P50/P90 + current stock + isolation probability (∏ P(pass closed)) into the projected_status used by Stage 4."
      actions={
        <button className="btn" type="button"><Icon d={Icons.external} size={12}/>Export Parquet</button>
      }
    >
      <Card padded={false}>
        <div className="filterbar">
          <div className="filter-group">
            <span>Head</span>
            <Segmented value={head} onChange={setHead} options={[
              { value: "all", label: "All" },
              ...B.heads.map((h) => ({ value: h, label: h })),
            ]} />
          </div>
          <div className="filter-group">
            <span>Tier</span>
            <Segmented value={tier} onChange={setTier} options={[
              { value: "all", label: "All" },
              { value: "1", label: "1" },
              { value: "2", label: "2" },
              { value: "3", label: "3" },
            ]} />
          </div>
          <div className="filter-group">
            <span>Alert</span>
            <Segmented value={firedOnly ? "fired" : "all"} onChange={(v) => setFiredOnly(v === "fired")} options={[
              { value: "fired", label: "Fired (128)" },
              { value: "all",   label: "All (4,200)" },
            ]} />
          </div>
          <div className="spacer" />
          <Search value={q} onChange={setQ} placeholder="Search post_id or sku…" />
        </div>

        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>Post</th>
                <th>SKU</th>
                <th>Head</th>
                <th className="num">Tier</th>
                <th>Status</th>
                <th>Worst-case</th>
                <th className="num">Current stock</th>
                <th className="num">DoC now</th>
                <th className="num">P50 DoC</th>
                <th className="num">P90 DoC</th>
                <th className="num">Isolation</th>
                <th>Alert</th>
              </tr>
            </thead>
            <tbody>
              {filtered.slice(0, 50).map((r) => {
                const post = B.posts.find((p) => p.post_id === r.post_id);
                const sku  = B.skus.find((s) => s.sku_id === r.sku);
                return (
                  <tr key={r.risk_id} className={selected === r.risk_id ? "selected" : ""}
                      onClick={() => { setSelected(r.risk_id); openLineage("alert", { alert_type: "stockout_risk", source_risk_id: r.risk_id, severity: r.predicted_status_worstcase === "stockout" ? "critical" : "warning", message: `${r.post_id} / ${r.head} (${r.sku}): risk row`, alert_id: `R-LINEAGE-${r.risk_id}`, trigger_metric: "projected_days_of_cover_p50", trigger_value: r.projected_days_of_cover_p50, created_at: "2026-05-29 11:14:02" }); }}>
                    <td>
                      <div className="mono">{r.post_id}</div>
                      <div style={{ fontSize: 11, color: "var(--ink-muted)" }}>{post?.name} · {post?.band}</div>
                    </td>
                    <td className="mono">{r.sku}<div style={{ fontSize: 11, color: "var(--ink-muted)", fontFamily: "var(--font-sans)" }}>{sku?.name}</div></td>
                    <td className="muted">{r.head}</td>
                    <td className="num">{r.tier}</td>
                    <td><StatusPill status={r.predicted_status} /></td>
                    <td><StatusPill status={r.predicted_status_worstcase} /></td>
                    <td className="num">{r.current_stock.toLocaleString()}</td>
                    <td className="num">{r.current_days_of_cover.toFixed(1)}</td>
                    <td className="num"><span style={{ color: r.projected_days_of_cover_p50 < 7 ? "var(--crit)" : "var(--ink)" }}>{r.projected_days_of_cover_p50.toFixed(1)}</span></td>
                    <td className="num"><span style={{ color: r.projected_days_of_cover_p90 < 7 ? "var(--crit)" : "var(--ink)" }}>{r.projected_days_of_cover_p90.toFixed(1)}</span></td>
                    <td className="num">{(r.isolation_probability * 100).toFixed(1)}%</td>
                    <td>{r.tier_alert_fired ? <Tag tone="crit">Fired</Tag> : <Tag>—</Tag>}</td>
                  </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr><td colSpan="12" style={{ textAlign: "center", padding: 10 }}>
                Showing {Math.min(50, filtered.length)} of {filtered.length} rows · {firedOnly ? "filter: tier_alert_fired = TRUE" : "filter: all"}
              </td></tr>
            </tfoot>
          </table>
        </div>
      </Card>
    </Page>
  );
}

window.OverviewScreen = OverviewScreen;
window.AlertsScreen   = AlertsScreen;
window.PlansScreen    = PlansScreen;
window.RiskScreen     = RiskScreen;
