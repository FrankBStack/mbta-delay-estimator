import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView from "./components/MapView.jsx";
import DelayByRouteChart from "./components/DelayByRouteChart.jsx";
import DivergencePanel from "./components/DivergencePanel.jsx";
import Headline from "./components/Headline.jsx";
import RouteSearch from "./components/RouteSearch.jsx";
import VehicleCard from "./components/VehicleCard.jsx";
import { api } from "./lib/api.js";
import { DELAY_BUCKETS, formatClock, secondsAgo } from "./lib/delay.js";
import { MODES, WINDOWS, filterSearch, readFilters } from "./lib/filters.js";
import { startPolling } from "./lib/poll.js";
import {
  POLL_STEPS_MS,
  STALE_AFTER_S,
  describeStatus,
  keepLastGood,
  newestTs,
  nextDelay,
  nextVehicleDelay,
} from "./lib/status.js";

const ANALYTICS_POLL_MS = 30000;
// One failed poll is noise; the banner waits for the next one to fail too.
const ERROR_AFTER_FAILURES = 2;
const DEV_HOST = /^(localhost|127\.0\.0\.1)$/;

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
  // phones only: the sidebar is a bottom sheet. "half" leaves the top of the
  // map visible for the vehicle just tapped.
  const [sheet, setSheet] = useState("peek");
  const sidebar = useRef(null);
  const touch = useRef(null);
  const [routeType, setRouteType] = useState(
    () => readFilters(window.location.search).routeType
  );
  const [windowMinutes, setWindowMinutes] = useState(
    () => readFilters(window.location.search).windowMinutes
  );
  // one route picked out of the mode, by search or from the chart
  const [routeId, setRouteId] = useState(() => readFilters(window.location.search).routeId);
  const [routes, setRoutes] = useState([]);
  // a vehicle found by its number, selected once the map's list has it
  const [pendingVehicleId, setPendingVehicleId] = useState(null);
  const [centerOn, setCenterOn] = useState(null);
  const [error, setError] = useState(null);
  const [analyticsError, setAnalyticsError] = useState(null);
  const [loading, setLoading] = useState(true);

  // Held in a ref so the poll effects don't restart on every filter change.
  const filters = useRef({ routeType, windowMinutes, routeId });
  filters.current = { routeType, windowMinutes, routeId };

  // The vehicle poll reads the latest health from here instead of waiting
  // on it: diagnostics must never hold up the map.
  const lastHealth = useRef(null);

  useEffect(() => {
    const search = filterSearch({ routeType, windowMinutes, routeId });
    const { pathname, hash } = window.location;
    if (search !== window.location.search) {
      window.history.replaceState(null, "", `${pathname}${search}${hash}`);
    }
  }, [routeType, windowMinutes, routeId]);

  // names for the search and the headline; without them the search is empty
  useEffect(() => {
    api.routes().then(setRoutes, () => {});
  }, []);

  // live poll, paced to the feed's own updates, backing off while it fails
  useEffect(() => {
    let delay = POLL_STEPS_MS[0];
    let failures = 0;
    let newest = null;
    // holding the last good positions only makes sense within one filter;
    // the first answer for a new filter replaces the old set outright
    let first = true;
    return startPolling(async (alive) => {
      try {
        const { routeId: id, routeType: type } = filters.current;
        const v = await api.vehicles(id ? { route_id: id } : { route_type: type });
        if (!alive()) return;
        const age = secondsAgo(lastHealth.current?.poller?.feed_timestamp);
        const feedStale = age !== null && age > STALE_AFTER_S;
        // React may run the updater after first is cleared below
        const replace = first;
        setVehicles((prev) => (replace ? v : keepLastGood(prev, v, feedStale)));
        first = false;
        setError(null);
        failures = 0;
        const n = newestTs(v);
        delay = nextVehicleDelay(n, newest, Date.now());
        newest = n;
      } catch (e) {
        failures += 1;
        if (alive() && failures >= ERROR_AFTER_FAILURES) setError(e.message);
        delay = nextDelay(delay, false);
      }
      if (alive()) setLoading(false);
      return delay;
    });
  }, [routeType, routeId]);

  // health poll: the feed time in the topbar and what the status banner reads.
  // A failure here just leaves the last answer in place; the vehicle poll owns
  // the error banner.
  useEffect(() => {
    let delay = POLL_STEPS_MS[0];
    return startPolling(async (alive) => {
      let ok = false;
      try {
        const h = await api.health();
        if (!alive()) return;
        lastHealth.current = h;
        setHealth(h);
        ok = true;
      } catch {
        ok = false;
      }
      delay = nextDelay(delay, ok);
      return delay;
    });
  }, []);

  // analytics poll
  useEffect(() => {
    let failures = 0;
    return startPolling(async (alive) => {
      try {
        const [d, dv] = await Promise.all([
          api.delayByRoute({
            minutes: filters.current.windowMinutes,
            route_type: filters.current.routeType,
            min_observations: 3,
          }),
          api.divergence({
            minutes: filters.current.windowMinutes,
            route_type: filters.current.routeType,
          }),
        ]);
        if (!alive()) return;
        setDelayRoutes(d.routes);
        setDivergence(dv);
        setAnalyticsError(null);
        failures = 0;
      } catch (e) {
        failures += 1;
        if (alive() && failures >= ERROR_AFTER_FAILURES) setAnalyticsError(e.message);
      }
      return ANALYTICS_POLL_MS;
    });
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
  const drawnRouteId = routeId ?? selectedRouteId;
  const route = useMemo(
    () => routes.find((r) => r.route_id === routeId) ?? null,
    [routes, routeId]
  );

  // Draw the line for the picked route or the selected vehicle's, and a
  // fainter one for whichever is under the cursor.
  useRouteShape(drawnRouteId, setRouteShape);
  useRouteShape(hoveredRouteId === drawnRouteId ? null : hoveredRouteId, setHoverShape);
  // only once the picked route's own line has arrived, not the one before it
  const fitTo = routeId && routeShape?.properties?.route_id === routeId ? routeShape : null;

  const handleRoute = useCallback(
    (id) => {
      setRouteId(id);
      if (!id) return;
      // a route outside the chosen mode brings its mode along, or All where
      // the page has no button for it
      const r = routes.find((x) => x.route_id === id);
      if (r && routeType !== null && r.route_type !== routeType) {
        setRouteType(MODES.some((m) => m.value === r.route_type) ? r.route_type : null);
      }
      // phones: back to the map the route was picked for
      setSheet("peek");
    },
    [routes, routeType]
  );

  const handleSelect = useCallback((id) => {
    setSelectedVehicleId(id);
    if (id) {
      setSheet("half");
      sidebar.current?.scrollTo(0, 0);
    } else {
      setSheet((s) => (s === "half" ? "peek" : s));
    }
  }, []);

  // the selected vehicle can age out of the feed or fall outside a new
  // filter; drop it rather than hold an empty card open
  useEffect(() => {
    if (vehicles && selectedVehicleId && !selected) handleSelect(null);
  }, [vehicles, selectedVehicleId, selected, handleSelect]);

  // A vehicle typed into the search may be outside the current filter, so
  // widen to everything and select it when the next list arrives.
  const handleVehicleSearch = useCallback(
    (feature) => {
      const id = feature.properties.vehicle_id;
      if (!vehicles?.features.some((f) => f.properties.vehicle_id === id)) {
        setRouteId(null);
        setRouteType(null);
      }
      setPendingVehicleId(id);
    },
    [vehicles]
  );
  useEffect(() => {
    if (!pendingVehicleId) return;
    const f = vehicles?.features.find((v) => v.properties.vehicle_id === pendingVehicleId);
    if (!f) return;
    setPendingVehicleId(null);
    handleSelect(pendingVehicleId);
    setCenterOn(f.geometry.coordinates);
  }, [vehicles, pendingVehicleId, handleSelect]);

  // swipe up opens the sheet; swipe down from the top of its content closes it
  const onTouchStart = (e) => {
    touch.current = { y: e.touches[0].clientY, top: sidebar.current?.scrollTop ?? 0 };
  };
  const onTouchEnd = (e) => {
    const start = touch.current;
    touch.current = null;
    if (!start) return;
    const dy = e.changedTouches[0].clientY - start.y;
    if (dy < -40) setSheet("full");
    else if (dy > 40 && start.top === 0) setSheet("peek");
  };
  const handleHover = useCallback((id) => setHoveredVehicleId(id), []);

  const feedAge = secondsAgo(health?.poller?.feed_timestamp);
  const status = describeStatus({ error, analyticsError, health, feedAgeS: feedAge });
  const stale = status.level === "stale" || status.level === "down";
  // raw errors are for whoever is running it locally, not for visitors
  const dev = DEV_HOST.test(window.location.hostname);
  const devHint = status.level === "down" && dev ? " Is uvicorn running on :8010?" : "";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="dot" data-stale={stale} />
          <div>
            <h1>MBTA Delay Estimator</h1>
            <p className="muted small">
              {vehicles?.features.length ?? 0} vehicles
              {health?.poller?.feed_timestamp ? (
                <span className="feed-time">
                  {` · feed ${formatClock(health.poller.feed_timestamp)}`}
                </span>
              ) : (
                " · connecting…"
              )}
              <FeedAge ts={health?.poller?.feed_timestamp} />
            </p>
          </div>
        </div>

        <RouteSearch
          routes={routes}
          routeId={routeId}
          routeType={routeType}
          onSelect={handleRoute}
          onSelectVehicle={handleVehicleSearch}
        />

        <div className="filters">
          <div className="segmented" role="group" aria-label="Mode">
            {MODES.map((m) => (
              <button
                key={String(m.value)}
                className={routeType === m.value ? "on" : ""}
                onClick={() => {
                  setRouteType(m.value);
                  setRouteId(null);
                }}
              >
                {m.label}
              </button>
            ))}
          </div>
        </div>
      </header>

      {status.headline && (
        <div className="banner" data-level={status.level} role="status">
          <span>{status.headline}{devHint}</span>
          {dev && status.detail && (
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
          fitTo={fitTo}
          centerOn={centerOn}
          selectedVehicleId={selectedVehicleId}
          onSelectVehicle={handleSelect}
          onHoverVehicle={handleHover}
        />

        <div className="legend-overlay">
          <div className="legend-title">Delay vs schedule</div>
          {DELAY_BUCKETS.map((b) => (
            <span key={b.key} className="legend-item legend-step">
              <span className="chip" style={{ background: b.color }} />
              {b.label}
            </span>
          ))}
          {/* small screens: the same steps as one scale, so late fits too */}
          <span
            className="legend-scale"
            role="img"
            aria-label="Colors run from blue for early, through gray for on time, to red for late"
          >
            <span>Early</span>
            {DELAY_BUCKETS.map((b) => (
              <span key={b.key} className="chip" style={{ background: b.color }} />
            ))}
            <span>Late</span>
          </span>
          <span className="legend-item">
            <span className="chip chip-hollow" />
            No timetable
          </span>
          <span className="legend-note">
            Nose points the direction of travel. Trains are drawn larger.
          </span>
        </div>

        <aside
          ref={sidebar}
          className="sidebar"
          data-open={sheet}
          onClick={sheet === "peek" ? () => setSheet("full") : undefined}
          onTouchStart={onTouchStart}
          onTouchEnd={onTouchEnd}
        >
          <button
            className="sheet-handle"
            aria-label={sheet === "peek" ? "Expand panel" : "Collapse panel"}
            aria-expanded={sheet !== "peek"}
            onClick={(e) => {
              e.stopPropagation();
              setSheet((s) => (s === "peek" ? "full" : "peek"));
            }}
          >
            <span />
          </button>

          <Headline vehicles={vehicles} routeType={routeType} route={route} />

          {selected && (
            <VehicleCard vehicle={selected} onClose={() => handleSelect(null)} />
          )}

          <div className="panel-block">
            <div className="window-row">
              <span className="muted small">Statistics over the last</span>
              <div className="segmented" role="group" aria-label="Statistics window">
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
            <DelayByRouteChart
              routes={delayRoutes}
              windowMinutes={windowMinutes}
              loading={loading}
              routeType={routeType}
              selectedRouteId={routeId}
              onSelectRoute={handleRoute}
            />
          </div>

          <div className="panel-block">
            <DivergencePanel divergence={divergence} />
          </div>

          <p className="footnote">
            Delay is computed by projecting each vehicle onto its route shape in
            PostGIS and interpolating the scheduled timings at that point, not
            read from the feed. The MBTA publishes no delay field, so its column
            is derived from its predicted arrival times.
          </p>
          <p className="footnote">
            Data from the MBTA's GTFS and GTFS-realtime feeds, provided by
            MassDOT. Not affiliated with the MBTA or MassDOT.{" "}
            <a href="https://github.com/FrankBStack/mbta-delay-estimator">Source</a>.
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
