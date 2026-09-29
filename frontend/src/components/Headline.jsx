import { delayColor, formatDelay } from "../lib/delay.js";

// keyed by GTFS route_type; null is the "All" filter
const NOUNS = {
  null: ["vehicle", "vehicles"],
  0: ["light rail train", "light rail trains"],
  1: ["subway train", "subway trains"],
  2: ["commuter train", "commuter trains"],
  3: ["bus", "buses"],
  // a route is named "Charlestown Ferry" already
  4: ["boat", "boats"],
};

export function noun(routeType, count = 1) {
  const pair = NOUNS[routeType] ?? NOUNS[null];
  return count === 1 ? pair[0] : pair[1];
}

// "39 bus", "Red Line subway trains", or the mode's noun when no route is picked
export function subject(route, routeType, count = 1) {
  return route ? `${route.name} ${noun(route.route_type, count)}` : noun(routeType, count);
}

export function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

// A vehicle waiting at, or still heading to, its origin ahead of departure
// reads as exactly zero, which says nothing about how late the fleet is, so
// it's counted separately. Mirrors CONFIDENCE_FILTER in the analytics router.
export function isWaiting(p) {
  return (p.method === "layover" || p.method === "first_stop") && p.computed_delay_s === 0;
}

export function splitDelays(features) {
  const delays = [];
  let waiting = 0;
  // the hollow markers on the map
  let noTimetable = 0;
  for (const f of features) {
    const p = f.properties;
    if (p.computed_delay_s === null || p.computed_delay_s === undefined) {
      noTimetable += 1;
      continue;
    }
    // the analytics leave these out too: off the shape, or implausibly late
    if (p.confidence === "low") continue;
    if (isWaiting(p)) waiting += 1;
    else delays.push(p.computed_delay_s);
  }
  return { delays, waiting, noTimetable };
}

export default function Headline({ vehicles, routeType, route = null }) {
  const { delays, waiting, noTimetable } = splitDelays(vehicles?.features ?? []);
  const type = route ? route.route_type : routeType;

  if (!delays.length) {
    const none = vehicles && !vehicles.features.length;
    return (
      <div className="hero">
        <p className="hero-kicker">Right now</p>
        <div className="hero-value muted">—</div>
        <p className="muted small">
          {none
            ? `No ${subject(route, routeType, 2)} in service.`
            : `Waiting for ${subject(route, routeType, 2)} to be placed against the timetable.`}
          {noTimetable > 0 &&
            ` ${noTimetable} in service ${noTimetable === 1 ? "has" : "have"} no timetable.`}
        </p>
      </div>
    );
  }

  const typical = Math.round(median(delays));
  // >= to match the color scale, which turns red at five minutes
  const late = delays.filter((d) => d >= 300).length;

  return (
    <div className="hero">
      <p className="hero-kicker">
        Right now the typical {route ? subject(route) : `MBTA ${noun(routeType)}`} is
      </p>
      <div className="hero-value" style={{ color: delayColor(typical) }}>
        {formatDelay(typical)}
      </div>
      <p className="muted small">
        Median of {delays.length} {noun(type, delays.length)} in service
      </p>
      {/* keyed to the marker colors on the map */}
      <ul className="hero-counts">
        {late > 0 && (
          <li>
            <span className="chip" style={{ background: delayColor(300) }} />
            {late} more than 5 min late
          </li>
        )}
        {waiting > 0 && (
          <li>
            <span className="chip" style={{ background: delayColor(0) }} />
            {waiting} waiting at origin
          </li>
        )}
        {noTimetable > 0 && (
          <li>
            <span className="chip chip-hollow" />
            {noTimetable} with no timetable
          </li>
        )}
      </ul>
    </div>
  );
}
