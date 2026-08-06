import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import DelayByRouteChart from "./components/DelayByRouteChart.jsx";
import DivergencePanel from "./components/DivergencePanel.jsx";
import VehicleCard from "./components/VehicleCard.jsx";
import { api } from "./lib/api.js";
import { DELAY_BUCKETS, formatClock, secondsAgo } from "./lib/delay.js";

const VEHICLE_POLL_MS = 5000;
const ANALYTICS_POLL_MS = 30000;

const MODES = [
  { value: null, label: "All" },
  { value: 1, label: "Subway" },
  { value: 0, label: "Light rail" },
  { value: 3, label: "Bus" },
  { value: 2, label: "Commuter" },
];

const WINDOWS = [15, 60, 180];

export default function App() {
  const [vehicles, setVehicles] = useState(null);
  const [health, setHealth] = useState(null);
  const [delayRoutes, setDelayRoutes] = useState([]);
  const [divergence, setDivergence] = useState(null);
  const [routeShape, setRouteShape] = useState(null);
  const [selectedVehicleId, setSelectedVehicleId] = useState(null);
  const [routeType, setRouteType] = useState(null);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Held in a ref so the poll effects don't restart on every filter change.
  const filters = useRef({ routeType, windowMinutes });
  filters.current = { routeType, windowMinutes };

  // live poll
  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      try {
        const [v, h] = await Promise.all([
          api.vehicles({ route_type: filters.current.routeType }),
          api.health(),
        ]);
        if (!alive) return;
        setVehicles(v);
        setHealth(h);
        setError(null);
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) {
          setLoading(false);
          timer = setTimeout(tick, VEHICLE_POLL_MS);
        }
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [routeType]);

  // analytics poll
  useEffect(() => {
    let alive = true;
    let timer;
    const tick = async () => {
      try {
        const [d, dv] = await Promise.all([
          api.delayByRoute({
            minutes: filters.current.windowMinutes,
            route_type: filters.current.routeType,
            min_observations: 3,
          }),
          api.divergence({ minutes: filters.current.windowMinutes }),
        ]);
        if (!alive) return;
        setDelayRoutes(d.routes);
        setDivergence(dv);
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) timer = setTimeout(tick, ANALYTICS_POLL_MS);
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [routeType, windowMinutes]);

  const selected = useMemo(
    () =>
      vehicles?.features.find(
        (f) => f.properties.vehicle_id === selectedVehicleId
      ) ?? null,
    [vehicles, selectedVehicleId]
  );

  // Draw the route line for whichever vehicle is selected.
  useEffect(() => {
    const routeId = selected?.properties?.route_id;
    if (!routeId) {
      setRouteShape(null);
      return;
    }
    let alive = true;
    api
      .routeShape(routeId)
      // shuttle routes have no fixed alignment to draw
      .then((s) => alive && setRouteShape(s?.geometry ? s : null))
      .catch(() => alive && setRouteShape(null));
    return () => {
      alive = false;
    };
  }, [selected?.properties?.route_id]);

  const handleSelect = useCallback((id) => setSelectedVehicleId(id), []);

  const feedAge = secondsAgo(health?.poller?.feed_timestamp);
  const stale = feedAge !== null && feedAge > 90;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="dot" data-stale={stale} />
          <div>
            <h1>MBTA Live Tracker</h1>
            <p className="muted small">
              {vehicles?.features.length ?? 0} vehicles ·{" "}
              {health?.poller?.feed_timestamp
                ? `feed ${formatClock(health.poller.feed_timestamp)}`
                : "connecting…"}
              {feedAge !== null && ` · ${feedAge}s old`}
            </p>
          </div>
        </div>

        <div className="filters">
          <div className="segmented" role="group" aria-label="Mode">
            {MODES.map((m) => (
              <button
                key={String(m.value)}
                className={routeType === m.value ? "on" : ""}
                onClick={() => setRouteType(m.value)}
              >
                {m.label}
              </button>
            ))}
          </div>
          <div className="segmented" role="group" aria-label="Analytics window">
            {WINDOWS.map((w) => (
              <button
                key={w}
                className={windowMinutes === w ? "on" : ""}
                onClick={() => setWindowMinutes(w)}
              >
                {w}m
              </button>
            ))}
          </div>
        </div>
      </header>

      {error && (
        <div className="banner">
          Backend unreachable — {error}. Is uvicorn running on :8010?
        </div>
      )}

      <main>
        <MapView
          vehicles={vehicles}
          routeShape={routeShape}
          selectedVehicleId={selectedVehicleId}
          onSelectVehicle={handleSelect}
        />

        <div className="legend-overlay">
          <div className="legend-title">Delay vs schedule</div>
          {DELAY_BUCKETS.map((b) => (
            <span key={b.key} className="legend-item">
              <span className="chip" style={{ background: b.color }} />
              {b.label}
            </span>
          ))}
          <span className="legend-item">
            <span className="chip chip-hollow" />
            Not placeable
          </span>
        </div>

        <aside className="sidebar">
          {selected && (
            <VehicleCard
              vehicle={selected}
              onClose={() => setSelectedVehicleId(null)}
            />
          )}

          <div className="panel-block">
            <DivergencePanel divergence={divergence} />
          </div>

          <div className="panel-block">
            <DelayByRouteChart
              routes={delayRoutes}
              windowMinutes={windowMinutes}
              loading={loading}
            />
          </div>

          <p className="footnote">
            Delay is computed by projecting each vehicle onto its route shape in
            PostGIS and interpolating the scheduled timings at that point, not
            read from the feed. The MBTA publishes no delay field, so its column
            is derived from its predicted arrival times.
          </p>
        </aside>
      </main>
    </div>
  );
}
