// Bastion — system / model / lineage screens.

const { useState: useStateSys, useMemo: useMemoSys } = React;

// ════════════════════════════════════════════════════════════════════ MAP
function MapScreen({ openLineage, day }) {
  const B = window.B;
  const [selectedPostId, setSelectedPostId] = useStateSys(null);

  // Derive worst-case status per post from stockout_risk
  const postStatus = useMemoSys(() => {
    const m = {};
    B.stockout_risk.forEach((r) => {
      if (r.tier_alert_fired) {
        const cur = m[r.post_id];
        const worse = (a, b) => {
          const rank = { ok: 0, rationing: 1, stockout: 2 };
          return rank[a] >= rank[b] ? a : b;
        };
        m[r.post_id] = cur ? worse(cur, r.predicted_status_worstcase) : r.predicted_status_worstcase;
      }
    });
    return m;
  }, []);

  // Isolated posts (the 15 from the canonical snapshot)
  const isolatedSet = new Set([
    "POST-001","POST-003","POST-004","POST-006","POST-013","POST-015","POST-028","POST-029",
    "POST-032","POST-033","POST-034","POST-035","POST-005","POST-008","POST-027",
  ]);

  const selectedPost = selectedPostId ? B.posts.find((p) => p.post_id === selectedPostId) : null;
  const selectedRisks = selectedPost
    ? B.stockout_risk.filter((r) => r.post_id === selectedPost.post_id && r.tier_alert_fired)
    : [];

  return (
    <Page
      eyebrow="Eastern Ladakh AOI"
      title="Posts & routes"
      sub="35 posts · 4 depots · 5 modeled passes. Marker fill = worst-case status from stockout_risk; dashed ring = road-isolated at horizon 14d (path availability < 0.05)."
      actions={
        <>
          <button className="btn" type="button">Filter by axis</button>
          <button className="btn" type="button">Toggle pass status</button>
        </>
      }
    >
      <div className="split-2" style={{ gridTemplateColumns: "1fr 320px", gap: 14 }}>
        <window.PostsMap
          posts={B.posts}
          depots={B.depots}
          passes={B.passes}
          routes={B.routes}
          hydro={B.hydro}
          lac={B.lac}
          postStatus={postStatus}
          selectedPostId={selectedPostId}
          onSelectPost={(id) => setSelectedPostId(id === selectedPostId ? null : id)}
          onSelectPass={(pa) => openLineage("alert", {
            alert_type: "disruption",
            pass_name: pa.pass_name,
            severity: pa.p_closed > 0.85 ? "critical" : pa.p_closed > 0.60 ? "warning" : "info",
            message: `${pa.pass_name}: P(closed) ${(pa.p_closed * 100).toFixed(0)}% by 2024-12-22 (h=7d) — posts beyond this pass risk isolation`,
            alert_id: `MAP-${pa.pass_name.replace(/\s+/g, "_")}`,
            trigger_metric: "p_closed",
            trigger_value: pa.p_closed,
            created_at: "2026-05-29 11:14:02",
          })}
          isolatedSet={isolatedSet}
        />

        <div className="stack" style={{ minWidth: 0 }}>
          {selectedPost ? (
            <PostDetailCard post={selectedPost} risks={selectedRisks} status={postStatus[selectedPost.post_id]} isolated={isolatedSet.has(selectedPost.post_id)} openLineage={openLineage} />
          ) : (
            <Card title="Selection" sub="Click any post or pass on the map to inspect.">
              <div className="empty" style={{ padding: 24 }}>
                <div className="empty-icon">⌖</div>
                Nothing selected.
              </div>
            </Card>
          )}

          <Card title="Modeled passes" count={B.passes.length} padded={false}>
            <table className="tbl">
              <thead><tr><th>Pass</th><th>Elev</th><th className="num">P(open)</th><th className="num">P(closed)</th></tr></thead>
              <tbody>
                {B.passes.map((p) => {
                  const tone = p.p_closed > 0.85 ? "crit" : p.p_closed > 0.60 ? "warn" : "ok";
                  return (
                    <tr key={p.pass_name}>
                      <td>{p.pass_name}</td>
                      <td className="mono muted">{p.elev_m}m</td>
                      <td className="num"><span style={{ color: p.p_open >= 0.6 ? "var(--ok)" : "var(--ink)" }}>{(p.p_open * 100).toFixed(0)}%</span></td>
                      <td className="num"><span style={{ color: tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : "var(--ok)" }}>{(p.p_closed * 100).toFixed(0)}%</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </Page>
  );
}

function PostDetailCard({ post, risks, status, isolated, openLineage }) {
  return (
    <div className="card">
      <div className="card-head">
        <div>
          <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--ink-faint)" }}>
            {post.post_id} · {post.band}
          </div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--ink)", marginTop: 2 }}>{post.name}</div>
          <div style={{ fontSize: 11.5, color: "var(--ink-muted)", marginTop: 1 }}>{post.axis} axis · {post.elev_m.toLocaleString()}m · {post.troops} troops</div>
        </div>
        <Grade grade={post.provenance} />
      </div>
      <div className="card-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span className="muted">Status (worst-case)</span>
          <StatusPill status={status || "ok"} />
        </div>
        <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span className="muted">Road reachability</span>
          {isolated ? <Tag tone="crit">Isolated</Tag> : <Tag tone="ok">Reachable</Tag>}
        </div>
        <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span className="muted">Depot</span>
          <span className="mono">{post.depot}</span>
        </div>
        <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span className="muted">Served by</span>
          <span style={{ fontSize: 11.5, color: "var(--ink)", textAlign: "right" }}>{(post.served_by || []).join(" → ") || "—"}</span>
        </div>
        <div className="row" style={{ display: "flex", justifyContent: "space-between", fontSize: 12 }}>
          <span className="muted">Air resupply</span>
          {post.has_air ? <Tag tone="ok">supported</Tag> : <Tag>no</Tag>}
        </div>

        {risks.length > 0 && (
          <>
            <hr className="divider" />
            <div style={{ fontSize: 10.5, fontWeight: 600, letterSpacing: "0.06em", textTransform: "uppercase", color: "var(--ink-faint)" }}>
              Fired risks at this post ({risks.length})
            </div>
            {risks.slice(0, 4).map((r) => (
              <button key={r.risk_id} className="rail-item" style={{ padding: "6px 8px", borderLeft: "none", background: "var(--surface)", borderRadius: 5, fontSize: 12, color: "var(--ink)" }}
                onClick={() => openLineage("alert", { alert_type: "stockout_risk", source_risk_id: r.risk_id, severity: r.predicted_status_worstcase === "stockout" ? "critical" : "warning", message: `${r.post_id} / ${r.head} (${r.sku}): risk row`, alert_id: `R-MAP-${r.risk_id}`, trigger_metric: "projected_days_of_cover_p50", trigger_value: r.projected_days_of_cover_p50, created_at: "2026-05-29 11:14:02" })}
                type="button"
              >
                <span style={{ fontFamily: "var(--font-mono)", color: "var(--ink-muted)", fontSize: 11 }}>{r.sku}</span>
                <span style={{ flex: 1, marginLeft: 6 }}>{r.head}</span>
                <span className="mono" style={{ fontSize: 11, color: "var(--crit)" }}>{r.projected_days_of_cover_p50.toFixed(1)}d</span>
              </button>
            ))}
          </>
        )}
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════ VEHICLES
function VehiclesScreen() {
  const B = window.B;
  const [cls, setCls] = useStateSys("all");
  const [depot, setDepot] = useStateSys("all");
  const [hotOnly, setHotOnly] = useStateSys(false);

  const sample = B.vehicles
    .filter((v) => (cls === "all" || v.class_id === cls))
    .filter((v) => (depot === "all" || v.home_depot_id === depot))
    .filter((v) => (!hotOnly || v.p_deadline > 0.05))
    .sort((a, b) => b.p_deadline - a.p_deadline);

  return (
    <Page
      eyebrow={`bastion.vehicle_reliability · snapshot ${B.snapshot.as_of_date} · horizon 7d`}
      title="Vehicles"
      sub="249 vehicles across 4 depots and 4 classes. Reliability is a rule-based analytic Weibull scorer (no training); the slot is hot-swappable when real altitude/breakdown data lands. Backtest Brier skill ≈ 0 — documented weak-signal per masterplan."
    >
      <Callout
        tone="info"
        title="Vehicle scorer Brier skill = −0.4%"
      >
        Rolling backtest of 104 weekly snapshots × 249 vehicles = 25,896 observations, 247 actual failures (0.95%). The rule predicts 1.16% — accurate on the unconditional rate, but no information beyond it. This is the honest signal for synthetic data where Stage 2's Weibull is too clean for ML to add anything. <b>Recommendation:</b> keep the rule for v1.0; replace with a survival forest only when real fleet data arrives.
      </Callout>

      <div className="stat-grid mt-3">
        <Stat label="Fleet" value={B.vehicle_summary.total} sub="across 4 classes" icon={Icons.vehicles} />
        <Stat label="Mean P(deadline) 7d" value={fmtPct(B.vehicle_summary.mean_p_deadline)} sub="vs observed 0.95%" />
        <Stat label="Hot vehicles" value={B.vehicle_summary.alert_count} sub="P(deadline) > 5%" tone={B.vehicle_summary.alert_count > 0 ? "critical" : null} />
        <Stat label="Tasked this plan" value={B.plans[0].vehicles_tasked} sub={`of ${B.vehicle_summary.total} available`} />
      </div>

      <div className="split-2 mt-3" style={{ gridTemplateColumns: "1fr 280px" }}>
        <Card padded={false}>
          <div className="filterbar">
            <div className="filter-group">
              <span>Class</span>
              <Segmented value={cls} onChange={setCls} options={[
                { value: "all", label: "All" },
                { value: "Tata-LPTA", label: "LPTA" },
                { value: "Stallion-4x4", label: "S-4x4" },
                { value: "Stallion-6x6", label: "S-6x6" },
                { value: "BharatBenz-HD", label: "BB-HD" },
              ]} />
            </div>
            <div className="filter-group">
              <span>Depot</span>
              <Segmented value={depot} onChange={setDepot} options={[
                { value: "all", label: "All" },
                { value: "DEP-LEH",      label: "Leh" },
                { value: "DEP-KARU",     label: "Karu" },
                { value: "DEP-PARTAPUR", label: "Partapur" },
                { value: "DEP-KARGIL",   label: "Kargil" },
              ]} />
            </div>
            <div className="filter-group">
              <span>Filter</span>
              <Segmented value={hotOnly ? "hot" : "all"} onChange={(v) => setHotOnly(v === "hot")} options={[
                { value: "hot", label: "Hot (>5%)" },
                { value: "all", label: "All" },
              ]} />
            </div>
          </div>
          <div className="tbl-wrap">
            <table className="tbl">
              <thead>
                <tr>
                  <th>Vehicle</th>
                  <th>Class</th>
                  <th>Depot</th>
                  <th className="num">Payload (t)</th>
                  <th className="num">Eff. age</th>
                  <th className="num">Events</th>
                  <th className="num">P(deadline) 7d</th>
                  <th className="num">Reliability</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {sample.map((v) => {
                  const tone = v.p_deadline > 0.15 ? "crit" : v.p_deadline > 0.05 ? "warn" : "ok";
                  return (
                    <tr key={v.vehicle_id}>
                      <td className="mono">{v.vehicle_id}</td>
                      <td><Tag>{v.class_id}</Tag></td>
                      <td className="mono muted">{v.home_depot_id.replace("DEP-", "")}</td>
                      <td className="num">{v.payload_tons.toFixed(1)}</td>
                      <td className="num">{v.effective_age_days.toLocaleString()}d</td>
                      <td className="num">{v.events_to_date}</td>
                      <td className="num">
                        <span style={{ color: tone === "crit" ? "var(--crit)" : tone === "warn" ? "var(--warn)" : "var(--ink)" }}>
                          {(v.p_deadline * 100).toFixed(2)}%
                        </span>
                      </td>
                      <td className="num">
                        <Bar value={v.reliability_score * 100} max={100} tone={tone === "ok" ? "ok" : tone}/>
                        <span>{(v.reliability_score * 100).toFixed(1)}%</span>
                      </td>
                      <td><Tag tone={v.status === "available" ? "ok" : "warn"}>{v.status}</Tag></td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot><tr><td colSpan="9" style={{ textAlign: "center" }}>Showing {sample.length} of {B.vehicle_summary.total} vehicles · sorted by P(deadline) desc</td></tr></tfoot>
            </table>
          </div>
        </Card>

        <div className="stack">
          <Card title="By class" padded={false}>
            <table className="tbl">
              <tbody>
                {Object.entries(B.vehicle_summary.by_class).map(([k, n]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td className="num mono">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Card title="By depot" padded={false}>
            <table className="tbl">
              <tbody>
                {Object.entries(B.vehicle_summary.by_depot).map(([k, n]) => (
                  <tr key={k}>
                    <td>{k.replace("DEP-", "")}</td>
                    <td className="num mono">{n}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      </div>
    </Page>
  );
}

// ════════════════════════════════════════════════════════════════════ MODELS
function ModelsScreen() {
  const B = window.B;
  const [selected, setSelected] = useStateSys(B.models[0].kind);
  const m = B.models.find((x) => x.kind === selected);

  return (
    <Page
      eyebrow="bastion_provenance.model_version"
      title="Models & evaluation"
      sub="5 model artifacts in stage3-v1.0 + stage4-v1.0. Metrics computed on the held-out 2024-07 to 2024-12 test window. Honest reporting per masterplan §10 — both MAPE and MAE/median framings for demand; Brier (not AUC) headline for route; documented weak-signal disclosure for vehicle."
    >
      <div className="split-2" style={{ gridTemplateColumns: "260px 1fr", gap: 14 }}>
        <Card title="Model registry" padded={false}>
          {B.models.map((m, i) => (
            <button key={m.kind} className={`rail-item ${selected === m.kind ? "active" : ""}`} style={{ borderLeft: selected === m.kind ? "" : "none" }} onClick={() => setSelected(m.kind)} type="button">
              <div style={{ width: 24, height: 24, display: "flex", alignItems: "center", justifyContent: "center", background: "var(--surface)", borderRadius: 4, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--ink-muted)" }}>0{i+1}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: "inherit" }}>{m.kind}</div>
                <div style={{ fontSize: 10.5, color: "var(--ink-faint)", fontFamily: "var(--font-mono)" }}>{m.name}</div>
              </div>
              <span className="badge">{m.slices}</span>
            </button>
          ))}
        </Card>

        <ModelDetailCard model={m} />
      </div>
    </Page>
  );
}

function ModelDetailCard({ model: m }) {
  const metrics = renderMetrics(m);
  return (
    <Card
      title={m.kind}
      sub={`${m.name} · ${m.algorithm}`}
      actions={<><Tag>git {m.git_sha}</Tag><Tag>{m.artifacts} artifact{m.artifacts > 1 ? "s" : ""}</Tag></>}
    >
      <div className="stat-grid">
        <Stat label="Algorithm" value={m.algorithm.split(/[(;,]/)[0].trim()} />
        <Stat label="Trained at" value={m.trained_at.slice(0, 10)} sub={m.trained_at.slice(11, 19) + " UTC"} />
        <Stat label="Slices" value={m.slices} sub={`${m.artifacts} persisted artifacts`} />
        <Stat label="Snapshot" value="seed=42" sub="frozen Stage 2 world" />
      </div>

      <hr className="divider" />

      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--ink-faint)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>Held-out metrics</div>
      <div>
        {metrics.map((row, i) => <MetricRow key={i} {...row} />)}
      </div>

      {m.metrics.notes && (
        <div className="note-box" style={{ marginTop: 14, background: "var(--surface)", border: "1px solid var(--line)", borderRadius: 6, padding: "10px 12px", fontSize: 12, color: "var(--ink-muted)", lineHeight: 1.55 }}>
          <b style={{ color: "var(--ink)" }}>Honest note.</b> {m.metrics.notes}
        </div>
      )}
    </Card>
  );
}

function renderMetrics(m) {
  const km = m.metrics;
  if (m.kind === "demand_forecast") return [
    { name: "Weighted MAPE (P50)", sub: "vs masterplan target <20%",       val: fmtPct(km.weighted_mape_p50), tgt: "<20%",   v: km.weighted_mape_p50, max: 0.5, tone: "warn" },
    { name: "Coverage P10",        sub: "post-calibration (target 10%)",   val: fmtPct(km.coverage_p10),     tgt: "10%",    v: km.coverage_p10, max: 0.2, tone: "ok" },
    { name: "Coverage P90",        sub: "post-calibration (target 10%)",   val: fmtPct(km.coverage_p90),     tgt: "10%",    v: km.coverage_p90, max: 0.2, tone: "ok" },
    { name: "MAE / median range",  sub: "across forward SKUs",             val: `${km.mae_over_median_range[0].toFixed(2)}–${km.mae_over_median_range[1].toFixed(2)}`, tgt: "—", v: 0.20, max: 0.5, tone: "ok" },
  ];
  if (m.kind === "route_availability") return [
    { name: "Mean AUC range",      sub: "across 5 passes × 4 horizons",     val: km.auc_range.map(x => x.toFixed(2)).join("–"), tgt: "—",       v: 0.73, max: 1.0, tone: "warn" },
    { name: "Mean Brier range",    sub: "lower is better",                  val: km.brier_range.map(x => x.toFixed(2)).join("–"), tgt: "—",     v: 0.10, max: 0.25, tone: "ok" },
    { name: "Brier baseline",      sub: "vs trivial p(1-p)",                val: km.brier_baseline_range.map(x => x.toFixed(2)).join("–"), tgt: "—", v: 0.075, max: 0.25, tone: "info" },
  ];
  if (m.kind === "vehicle_reliability") return [
    { name: "Predicted failure rate", sub: "(unconditional)",                val: fmtPct(km.predicted_rate),  tgt: "0.95%", v: km.predicted_rate, max: 0.05, tone: "ok" },
    { name: "Observed failure rate",  sub: "(rolling backtest)",             val: fmtPct(km.observed_rate),   tgt: "—",     v: km.observed_rate,  max: 0.05, tone: "ok" },
    { name: "Brier skill",            sub: "vs constant-rate baseline",      val: fmtPct(km.brier_skill),     tgt: ">0%",   v: 0.05, max: 0.20, tone: "crit" },
    { name: "Backtest sample",        sub: "weekly snapshots × fleet",       val: km.backtest_n.toLocaleString(), tgt: "—", v: 0.75, max: 1.0, tone: "ok" },
  ];
  if (m.kind === "risk_evaluator") return [
    { name: "Stockout precision",  sub: "@14d horizon, 1,050 pairs",         val: fmtPct(km.stockout_precision_14d), tgt: "—", v: km.stockout_precision_14d, max: 1.0, tone: "ok" },
    { name: "At-risk recall",      sub: "@14d horizon",                       val: fmtPct(km.at_risk_recall_14d),     tgt: "—", v: km.at_risk_recall_14d,     max: 1.0, tone: "ok" },
    { name: "True positives",      sub: "(predicted_stockout ∩ actual)",      val: String(km.confusion_14d.tp),       tgt: "—", v: 0.95, max: 1.0, tone: "ok" },
    { name: "False negatives",     sub: "(rationing missed as ok)",           val: String(km.confusion_14d.fn),       tgt: "0", v: 0.10, max: 1.0, tone: "warn" },
    { name: "False positives",     sub: "(predicted_stockout ∩ actual=ok)",   val: String(km.confusion_14d.fp),       tgt: "0", v: 0.0,  max: 1.0, tone: "ok" },
  ];
  if (m.kind === "optimizer") return [
    { name: "Solve time (4 plans)",sub: "warm-start enabled",                val: `${km.solve_time_s.toFixed(1)}s`,  tgt: "<5s", v: km.solve_time_s, max: 5, tone: "ok" },
    { name: "Plans emitted",       sub: "lexicographic objectives",          val: String(km.plan_count),             tgt: "4",   v: km.plan_count / 4, max: 1, tone: "ok" },
    { name: "Best road coverage",  sub: "of priority-kg of P90 demand",      val: `${km.coverage_best_road_pct.toFixed(1)}%`, tgt: "—", v: km.coverage_best_road_pct / 100, max: 1, tone: "crit" },
    { name: "Road-isolated posts", sub: "at horizon 14d",                    val: `${km.posts_road_isolated} / ${km.posts_at_risk}`, tgt: "—", v: km.posts_road_isolated / km.posts_at_risk, max: 1, tone: "crit" },
  ];
  return [];
}

function MetricRow({ name, sub, val, tgt, v, max, tone }) {
  const pct = Math.max(2, Math.min(100, (v / max) * 100));
  return (
    <div className="metric-row">
      <div className="m-name">{name}<small>{sub}</small></div>
      <div className="m-val">{val}</div>
      <div className="metric-bar">
        <i className={tone || ""} style={{ width: `${pct}%` }} />
      </div>
      <div className="m-target">{tgt}</div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════════ SNAPSHOTS
function SnapshotsScreen() {
  const B = window.B;
  return (
    <Page
      eyebrow="bastion_provenance.data_snapshot"
      title="Data snapshots"
      sub="Every prediction row joins back to one of these. Re-running stage2_world/generate.py with the same seed produces byte-identical output — the lineage chain terminates here."
      actions={<button className="btn primary" type="button"><Icon d={Icons.zap} size={12}/>Generate new snapshot</button>}
    >
      <Card padded={false}>
        <div className="tbl-wrap">
          <table className="tbl">
            <thead>
              <tr>
                <th>As of</th>
                <th>Label</th>
                <th className="num">Seed</th>
                <th className="num">Alerts</th>
                <th className="num">Plans</th>
                <th className="num">Best road coverage</th>
                <th>Status</th>
                <th>Created</th>
              </tr>
            </thead>
            <tbody>
              {B.snapshots.map((s) => (
                <tr key={s.as_of_date}>
                  <td className="mono"><b>{s.as_of_date}</b></td>
                  <td><Tag>{s.label}</Tag></td>
                  <td className="num mono">{s.seed}</td>
                  <td className="num">{s.alerts}</td>
                  <td className="num">{s.plans}</td>
                  <td className="num">
                    <Bar value={s.coverage_pct} max={100} tone={s.coverage_pct > 80 ? "ok" : s.coverage_pct > 50 ? "warn" : "crit"} />
                    {s.coverage_pct.toFixed(1)}%
                  </td>
                  <td>{s.status === "current" ? <Tag tone="accent">current</Tag> : <Tag>archived</Tag>}</td>
                  <td className="mono muted">{s.created_at.slice(0, 16).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-3">
        <Card title="Generator config" sub="parameters in stage2_world/config.py">
          <div className="stat-grid">
            <Stat label="AOI" value="Eastern Ladakh" sub="32.5–35.5°N, 76–79.5°E" />
            <Stat label="Time range" value="3 years" sub="2022-01-01 → 2024-12-31" />
            <Stat label="Posts" value={B.snapshot.row_counts.posts} sub="across 4 depots" />
            <Stat label="SKUs" value={B.snapshot.row_counts.skus} sub="6 stock heads" />
            <Stat label="Consumption" value={`${(B.snapshot.row_counts.consumption_event / 1e6).toFixed(2)}M`} unit="rows" sub="daily per (post, SKU)" />
            <Stat label="Weather obs" value={`${(B.snapshot.row_counts.weather_observation / 1e3).toFixed(1)}K`} unit="rows" sub="anchored to IMD climatology" />
            <Stat label="Stock ledger" value={`${(B.snapshot.row_counts.stock_level / 1e6).toFixed(2)}M`} unit="rows" sub="full daily stock dynamics" />
            <Stat label="Vehicles" value={B.snapshot.row_counts.vehicles} sub="4 classes; per-vehicle Weibull priors" />
          </div>
        </Card>
      </div>

      <div className="mt-3">
        <Card title="Provenance sources" sub="Every anchored value cites a public source; the rest is flagged SYNTHETIC-INFERRED in config.py." padded={false}>
          <table className="tbl">
            <thead><tr><th>source_id</th><th>Name</th><th>Realism tier</th></tr></thead>
            <tbody>
              {B.sources.map((s) => (
                <tr key={s.source_id}>
                  <td className="mono">{s.source_id}</td>
                  <td>{s.name}</td>
                  <td><Tag tone={s.tier.startsWith("tier_1") ? "ok" : s.tier.startsWith("tier_2") ? "accent" : ""}>{s.tier.replace(/_/g, " ")}</Tag></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
    </Page>
  );
}

// ════════════════════════════════════════════════════════════════════ SOURCES (simple stub)
function SourcesScreen() {
  const B = window.B;
  return (
    <Page
      eyebrow="bastion_provenance.sources"
      title="Sources"
      sub="Public-data anchors backing the Stage 2 generator. Each Source attaches via RawArtifact → Claim → EvidenceLink to the domain objects it parameterises."
    >
      <Card padded={false}>
        <table className="tbl">
          <thead><tr><th>source_id</th><th>Name</th><th>Category</th><th>Tier</th><th>Status</th></tr></thead>
          <tbody>
            {B.sources.map((s) => (
              <tr key={s.source_id}>
                <td className="mono">{s.source_id}</td>
                <td>{s.name}</td>
                <td className="muted">—</td>
                <td><Tag tone={s.tier.startsWith("tier_1") ? "ok" : "accent"}>{s.tier.replace(/_/g, " ")}</Tag></td>
                <td><Tag tone="ok">enabled</Tag></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="mt-3" style={{ fontSize: 11.5, color: "var(--ink-faint)", lineHeight: 1.6 }}>
        <b style={{ color: "var(--ink-muted)" }}>Note:</b> the v2-era scraper/extractor pipeline (under <code>bastion/</code>) is legacy. v3 does not depend on it. Real sources land via direct ingestion into <code>bastion_provenance.raw_artifacts</code> when a customer's data substrate replaces the synthetic world.
      </div>
    </Page>
  );
}

window.MapScreen       = MapScreen;
window.VehiclesScreen  = VehiclesScreen;
window.ModelsScreen    = ModelsScreen;
window.SnapshotsScreen = SnapshotsScreen;
window.SourcesScreen   = SourcesScreen;
