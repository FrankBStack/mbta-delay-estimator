import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import DelayByRouteChart from "./components/DelayByRouteChart.jsx";
import DivergencePanel from "./components/DivergencePanel.jsx";
import Headline from "./components/Headline.jsx";
import VehicleCard from "./components/VehicleCard.jsx";
import { api } from "./lib/api.js";
import { DELAY_BUCKETS, formatClock, secondsAgo } from "./lib/delay.js";
import {
  POLL_STEPS_MS,
  STALE_AFTER_S,
  describeStatus,
  keepLastGood,
  nextDelay,
} from "./lib/status.js";

const ANALYTICS_POLL_MS = 30000;
// One failed poll is noise; the banner waits for the next one to fail too.
const ERROR_AFTER_FAILURES = 2;
const DEV_HOST = /^(localhost|127\.0\.0\.1)$/;

const MODES = [
  { value: null, label: "All" },
  { value: 1, label: "Subway" },
  { value: 0, label: "Light rail" },
  { value: 3, label: "Bus" },
  { value: 2, label: "Commuter" },
];

const WINDOWS = [15, 60, 180];

// Ticks on its own so the age counts up between polls without re-rendering
// the map every second.
function FeedAge({ ts }) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!ts) return undefined;
    const timer = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [ts]);
  const age = secondsAgo(ts);
  return age === null ? null : ` · ${age}s old`;
}

export default function App() {
  const [vehicles, setVehicles] = useState(null);
  const [health, setHealth] = useState(null);
  const [delayRoutes, setDelayRoutes] = useState([]);
  const [divergence, setDivergence] = useState(null);
  const [routeShape, setRouteShape] = useState(null);
  const [hoverShape, setHoverShape] = useState(null);
  const [selectedVehicleId, setSelectedVehicleId] = useState(null);
  const [hoveredVehicleId, setHoveredVehicleId] = useState(null);
  // phones only: the sidebar is a bottom sheet
  const [sheetOpen, setSheetOpen] = useState(false);
  const [routeType, setRouteType] = useState(null);
  const [windowMinutes, setWindowMinutes] = useState(60);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Held in a ref so the poll effects don't restart on every filter change.
  const filters = useRef({ routeType, windowMinutes });
  filters.current = { routeType, windowMinutes };

  // The vehicle poll reads the latest health from here instead of waiting
  // on it: diagnostics must never hold up the map.
  const lastHealth = useRef(null);

  // live poll, backing off while it fails
  useEffect(() => {
    let alive = true;
    let timer;
    let delay = POLL_STEPS_MS[0];
    let failures = 0;
    const tick = async () => {
      let ok = false;
      try {
        const v = await api.vehicles({ route_type: filters.current.routeType });
        if (!alive) return;
        const age = secondsAgo(lastHealth.current?.poller?.feed_timestamp);
        const feedStale = age !== null && age > STALE_AFTER_S;
        setVehicles((prev) => keepLastGood(prev, v, feedStale));
        setError(null);
        failures = 0;
        ok = true;
      } catch (e) {
        failures += 1;
        if (alive && failures >= ERROR_AFTER_FAILURES) setError(e.message);
      } finally {
        if (alive) {
          setLoading(false);
          delay = nextDelay(delay, ok);
          timer = setTimeout(tick, delay);
        }
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [routeType]);

  // health poll: the feed time in the topbar and what the status banner reads.
  // A failure here just leaves the last answer in place; the vehicle poll owns
  // the error banner.
  useEffect(() => {
    let alive = true;
    let timer;
    let delay = POLL_STEPS_MS[0];
    const tick = async () => {
      let ok = false;
      try {
        const h = await api.health();
        if (!alive) return;
        lastHealth.current = h;
        setHealth(h);
        ok = true;
      } catch {
        ok = false;
      } finally {
        if (alive) {
          delay = nextDelay(delay, ok);
          timer = setTimeout(tick, delay);
        }
      }
    };
    tick();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, []);

  // analytics poll
  useEffect(() => {
    let alive = true;
    let timer;
    let failures = 0;
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
        failures = 0;
      } catch (e) {
        failures += 1;
        if (alive && failures >= ERROR_AFTER_FAILURES) setError(e.message);
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

  const hoveredRouteId = useMemo(
    () =>
      vehicles?.features.find((f) => f.properties.vehicle_id === hoveredVehicleId)
        ?.properties.route_id ?? null,
    [vehicles, hoveredVehicleId]
  );
  const selectedRouteId = selected?.properties?.route_id ?? null;

  // Draw the route line for the selected vehicle, and a fainter one for
  // whichever is under the cursor.
  useRouteShape(selectedRouteId, setRouteShape);
  useRouteShape(hoveredRouteId === selectedRouteId ? null : hoveredRouteId, setHoverShape);

  const handleSelect = useCallback((id) => {
    setSelectedVehicleId(id);
    if (id) setSheetOpen(true);
  }, []);
  const handleHover = useCallback((id) => setHoveredVehicleId(id), []);

  const feedAge = secondsAgo(health?.poller?.feed_timestamp);
  const status = describeStatus({ error, health, feedAgeS: feedAge });
  const stale = status.level !== "ok";
  const devHint =
    status.level === "down" && DEV_HOST.test(window.location.hostname)
      ? " Is uvicorn running on :8010?"
      : "";

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
              <FeedAge ts={health?.poller?.feed_timestamp} />
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

      {status.headline && (
        <div className="banner" data-level={status.level} role="status">
          <span>{status.headline}{devHint}</span>
          {status.detail && (
            <details>
              <summary>Details</summary>
              <code>{status.detail}</code>
            </details>
          )}
        </div>
      )}

      <main>
        <MapView
          vehicles={vehicles}
          stale={stale}
          routeShape={routeShape}
          hoverShape={hoverShape}
          selectedVehicleId={selectedVehicleId}
          onSelectVehicle={handleSelect}
          onHoverVehicle={handleHover}
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
          <span className="legend-note">
            Nose points the direction of travel. Trains are drawn larger.
          </span>
        </div>

        <aside className="sidebar" data-open={sheetOpen}>
          <button
            className="sheet-handle"
            aria-label={sheetOpen ? "Collapse panel" : "Expand panel"}
            aria-expanded={sheetOpen}
            onClick={() => setSheetOpen((o) => !o)}
          >
            <span />
          </button>

          <Headline
            vehicles={vehicles}
            divergence={divergence}
            windowMinutes={windowMinutes}
            routeType={routeType}
          />

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

function useRouteShape(routeId, setShape) {
  useEffect(() => {
    if (!routeId) {
      setShape(null);
      return;
    }
    let alive = true;
    api
      .routeShape(routeId)
      // shuttle routes have no fixed alignment to draw
      .then((s) => alive && setShape(s?.geometry ? s : null))
      .catch(() => alive && setShape(null));
    return () => {
      alive = false;
    };
  }, [routeId, setShape]);
}
