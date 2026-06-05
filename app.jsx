// Project Bastion — root app shell + router.

const { useState: useStateApp } = React;

function App() {
  const [route, setRoute] = useStateApp("overview");
  const [lineage, setLineage] = useStateApp({ open: false, kind: null, payload: null });
  const [dayOffset, setDayOffset] = useStateApp(0);

  // expose route setter for in-page links
  window.__setRoute = setRoute;

  const openLineage  = (kind, payload) => setLineage({ open: true, kind, payload });
  const closeLineage = () => setLineage({ open: false, kind: null, payload: null });

  const day = window.B.computeDay(dayOffset);
  // Expose for screens that read it directly
  window.__dayOffset = dayOffset;
  window.__day = day;

  const advance = () => setDayOffset((d) => Math.min(30, d + 1));
  const retreat = () => setDayOffset((d) => Math.max(-30, d - 1));
  const reset   = () => setDayOffset(0);

  const counts = {
    alerts:    day.alert_totals.total,
    plans:     window.B.plans.length,
    risk:      day.alert_totals.stockout_risk.total,
    vehicles:  window.B.vehicle_summary.total,
    snapshots: window.B.snapshots.length,
  };

  let screen = null;
  if (route === "overview")  screen = <OverviewScreen  openLineage={openLineage} day={day} />;
  if (route === "alerts")    screen = <AlertsScreen    openLineage={openLineage} day={day} />;
  if (route === "plans")     screen = <PlansScreen     openLineage={openLineage} day={day} />;
  if (route === "risk")      screen = <RiskScreen      openLineage={openLineage} day={day} />;
  if (route === "map")       screen = <MapScreen       openLineage={openLineage} day={day} />;
  if (route === "vehicles")  screen = <VehiclesScreen />;
  if (route === "models")    screen = <ModelsScreen />;
  if (route === "snapshots") screen = <SnapshotsScreen />;
  if (route === "sources")   screen = <SourcesScreen />;

  return (
    <div className="app">
      <Header
        snapshot={window.B.snapshot}
        alertTotal={counts.alerts}
        onSnapshotClick={() => setRoute("snapshots")}
        onReplan={() => setRoute("plans")}
        dayOffset={dayOffset}
        day={day}
        onAdvance={advance}
        onRetreat={retreat}
        onReset={reset}
      />
      <LeftRail route={route} onRoute={setRoute} counts={counts} />
      <main className="main">
        <ReplayBanner dayOffset={dayOffset} day={day} onReset={reset} />
        {screen}
        <LineageDrawer open={lineage.open} kind={lineage.kind} payload={lineage.payload} onClose={closeLineage} />
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
