import { useEffect, useMemo, useRef, useState } from "react";
import { formatDelay, formatSigned } from "../lib/delay.js";

// ours is the bar; the MBTA's is a tick on it, since the two mostly agree
// and a second bar per route doubled the ink to say so
const SERIES = {
  computed: { color: "#3987e5", label: "Computed from position" },
  feed: { color: "#e8e6df", label: "MBTA prediction" },
};

const MODE_NAMES = {
  0: "light rail",
  1: "subway",
  2: "commuter rail",
  3: "bus",
  4: "ferry",
};

const ROW_H = 26;
const BAR_H = 10;
const TICK_H = 18;
const VALUE_W = 50;
const MIN_LABEL_W = 76;
const MAX_LABEL_W = 132;
// the pill's bold 10.5px text averages about 6.3px a glyph
const PILL_CHAR_W = 6.3;
const PILL_PAD = 12;
// sidebar less its padding — used only until the first measurement lands
const FALLBACK_W = 318;

export default function DelayByRouteChart({
  routes,
  windowMinutes,
  loading,
  routeType = null,
  selectedRouteId = null,
  onSelectRoute,
}) {
  const [asTable, setAsTable] = useState(false);
  const [hover, setHover] = useState(null);
  const [measured, setMeasured] = useState(0);
  const bodyRef = useRef(null);

  const rows = useMemo(() => routes.slice(0, 14), [routes]);

  const domain = useMemo(() => {
    let lo = 0;
    let hi = 0;
    for (const r of rows) {
      for (const v of [r.mean_computed_s, r.mean_feed_s]) {
        if (v === null || v === undefined) continue;
        lo = Math.min(lo, v);
        hi = Math.max(hi, v);
      }
    }
    // keep zero in frame and leave room for the labels
    const pad = Math.max(60, (hi - lo) * 0.12);
    return { lo: lo - (lo < 0 ? pad : 0), hi: hi + pad };
  }, [rows]);

  const hasRows = rows.length > 0;

  useEffect(() => {
    const el = bodyRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(([entry]) =>
      setMeasured(Math.round(entry.contentRect.width))
    );
    ro.observe(el);
    return () => ro.disconnect();
  }, [asTable, hasRows]);

  if (loading && !rows.length) {
    return <p className="muted small">Collecting observations…</p>;
  }
  if (!rows.length) {
    return (
      <p className="muted small">
        Not enough placed observations yet. Give the poller a few cycles.
      </p>
    );
  }

  const width = Math.max(260, measured || FALLBACK_W);
  const labelW = Math.round(
    Math.min(MAX_LABEL_W, Math.max(MIN_LABEL_W, width * 0.32))
  );
  const plotW = Math.max(90, width - labelW - VALUE_W);
  const height = rows.length * ROW_H + 22;
  const maxChars = Math.max(4, Math.floor((labelW - 8 - PILL_PAD) / PILL_CHAR_W));

  const scale = (v) => ((v - domain.lo) / (domain.hi - domain.lo || 1)) * plotW;
  const zeroX = scale(0);
  const ticks = niceTicks(domain.lo, domain.hi);
  // choosing the route already shown puts every route back
  const choose = (id) => onSelectRoute?.(id === selectedRouteId ? null : id);

  return (
    <div className="chart">
      <div className="chart-head">
        <div>
          <h3>Mean delay by route</h3>
          <p className="muted small">
            Worst {rows.length} of {routes.length} {MODE_NAMES[routeType] ?? ""} routes · last{" "}
            {windowMinutes} min.
            Choose one to see it on the map.
          </p>
        </div>
        <button className="ghost-btn" onClick={() => setAsTable((v) => !v)}>
          {asTable ? "Chart" : "Table"}
        </button>
      </div>

      <div className="legend">
        <span className="legend-item">
          <span className="chip" style={{ background: SERIES.computed.color }} />
          {SERIES.computed.label}
        </span>
        <span className="legend-item">
          <span className="tick-chip" style={{ background: SERIES.feed.color }} />
          {SERIES.feed.label}
        </span>
      </div>

      {asTable ? (
        <table className="data-table">
          <thead>
            <tr>
              <th>Route</th>
              <th>Computed</th>
              <th>Feed</th>
              <th>Diff</th>
              <th>Obs</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.route_id} className={r.route_id === selectedRouteId ? "on" : ""}>
                <td>
                  <button
                    className="link-btn"
                    aria-pressed={r.route_id === selectedRouteId}
                    onClick={() => choose(r.route_id)}
                  >
                    {r.name}
                  </button>
                </td>
                <td className="num">{formatDelay(r.mean_computed_s)}</td>
                <td className="num">{formatDelay(r.mean_feed_s)}</td>
                <td className="num">{formatSigned(r.mean_divergence_s)}</td>
                <td className="num">{r.observations}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="chart-body" ref={bodyRef}>
          <svg
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            role="group"
            aria-label="Mean delay by route, computed from vehicle position compared with the MBTA's own prediction"
          >
            {ticks.map((t) => (
              <g key={t}>
                <line
                  x1={labelW + scale(t)}
                  x2={labelW + scale(t)}
                  y1={0}
                  y2={rows.length * ROW_H}
                  stroke={t === 0 ? "#4a4a48" : "#2c2c2a"}
                  strokeWidth={1}
                />
                <text
                  x={labelW + scale(t)}
                  y={rows.length * ROW_H + 14}
                  className="axis-label"
                  textAnchor="middle"
                >
                  {t === 0 ? "0" : `${Math.round(t / 60)}m`}
                </text>
              </g>
            ))}

            {rows.map((r, i) => {
              const y = i * ROW_H;
              const name = truncate(shortName(r.name), maxChars);
              const mode = MODE_NAMES[r.route_type];
              return (
                <g
                  key={r.route_id}
                  className="chart-row"
                  role="button"
                  tabIndex={0}
                  aria-pressed={r.route_id === selectedRouteId}
                  aria-label={`${r.name}${mode ? ` ${mode}` : ""}, ${formatDelay(
                    r.mean_computed_s
                  )}; MBTA ${formatDelay(r.mean_feed_s)}. Show on the map`}
                  onClick={() => choose(r.route_id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      choose(r.route_id);
                    }
                  }}
                  onMouseEnter={() => setHover(r.route_id)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(r.route_id)}
                  onBlur={() => setHover(null)}
                >
                  {/* whole row is the hit target, not just the bars */}
                  <title>{r.name}</title>
                  <rect
                    className="row-bg"
                    x={0}
                    y={y}
                    width={width}
                    height={ROW_H}
                    rx={4}
                    fill={
                      r.route_id === selectedRouteId
                        ? "rgba(57,135,229,0.16)"
                        : hover === r.route_id
                          ? "rgba(255,255,255,0.05)"
                          : "transparent"
                    }
                  />
                  {/* the MBTA's own route colors: yellow bus, purple commuter rail */}
                  <rect
                    x={2}
                    y={y + 5}
                    width={name.length * PILL_CHAR_W + PILL_PAD}
                    height={ROW_H - 10}
                    rx={4}
                    fill={r.color}
                  />
                  <text
                    x={2 + PILL_PAD / 2}
                    y={y + ROW_H / 2 + 3.5}
                    className="row-pill"
                    style={{ fill: textOn(r.color) }}
                  >
                    {name}
                  </text>

                  <path
                    d={barPath(
                      labelW + zeroX,
                      labelW + scale(r.mean_computed_s ?? 0),
                      y + (ROW_H - BAR_H) / 2,
                      BAR_H
                    )}
                    fill={SERIES.computed.color}
                  />
                  {r.mean_feed_s !== null && r.mean_feed_s !== undefined && (
                    <rect
                      x={labelW + scale(r.mean_feed_s) - 1}
                      y={y + (ROW_H - TICK_H) / 2}
                      width={2}
                      height={TICK_H}
                      rx={1}
                      fill={SERIES.feed.color}
                    />
                  )}

                  <text
                    x={labelW + plotW + 6}
                    y={y + ROW_H / 2 + 4}
                    className="row-value"
                  >
                    {formatDelay(r.mean_computed_s, { sign: false })}
                  </text>
                </g>
              );
            })}
          </svg>

          {hover && <HoverCard route={rows.find((r) => r.route_id === hover)} />}
        </div>
      )}
    </div>
  );
}

function HoverCard({ route }) {
  if (!route) return null;
  return (
    <div className="hovercard">
      <strong>{route.name}</strong>
      {MODE_NAMES[route.route_type] && (
        <span className="muted"> · {MODE_NAMES[route.route_type]}</span>
      )}
      <dl>
        <dt>
          <span className="chip" style={{ background: SERIES.computed.color }} />
          Computed
        </dt>
        <dd>{formatDelay(route.mean_computed_s)}</dd>
        <dt>
          <span className="tick-chip" style={{ background: SERIES.feed.color }} />
          MBTA
        </dt>
        <dd>{formatDelay(route.mean_feed_s)}</dd>
        <dt>Divergence</dt>
        <dd>{formatSigned(route.mean_divergence_s)}</dd>
        <dt>Median / p90</dt>
        <dd>
          {formatDelay(route.median_computed_s, { sign: false })} /{" "}
          {formatDelay(route.p90_computed_s, { sign: false })}
        </dd>
        <dt>Observations</dt>
        <dd>
          {route.observations} from {route.vehicles} vehicle
          {route.vehicles === 1 ? "" : "s"}
        </dd>
      </dl>
    </div>
  );
}

// Bar sits on the zero line with only the value end rounded.
function barPath(x0, x1, y, h, r = 4) {
  const w = Math.abs(x1 - x0);
  const radius = Math.min(r, w);
  if (w < 0.5) return `M${x0} ${y} h1 v${h} h-1 Z`;
  if (x1 >= x0) {
    return `M${x0} ${y} H${x1 - radius} a${radius} ${radius} 0 0 1 ${radius} ${radius} V${
      y + h - radius
    } a${radius} ${radius} 0 0 1 ${-radius} ${radius} H${x0} Z`;
  }
  return `M${x0} ${y} H${x1 + radius} a${radius} ${radius} 0 0 0 ${-radius} ${radius} V${
    y + h - radius
  } a${radius} ${radius} 0 0 0 ${radius} ${radius} H${x0} Z`;
}

export function niceTicks(lo, hi) {
  const span = hi - lo;
  const step = (span > 1200 ? 5 : span > 600 ? 2 : 1) * 60;
  const out = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  if (!out.includes(0) && lo <= 0 && hi >= 0) out.push(0);
  return out.sort((a, b) => a - b);
}

// whichever of black or white text reads better on a route's color
export function textOn(hex) {
  const n = parseInt(String(hex).replace("#", ""), 16);
  if (Number.isNaN(n)) return "#fff";
  const lin = (c) => {
    const v = c / 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  const l = 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
  // contrast against black beats contrast against white above this luminance
  return l > 0.179 ? "#111" : "#fff";
}

export function shortName(s) {
  return String(s ?? "").replace(/\s+(Line|Ferry)$/, "");
}

export function truncate(s, n) {
  const str = String(s ?? "");
  return str.length > n ? `${str.slice(0, n - 1)}…` : str;
}
