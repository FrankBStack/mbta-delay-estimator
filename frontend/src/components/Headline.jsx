import { delayColor, formatDelay } from "../lib/delay.js";

export function median(values) {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const mid = s.length >> 1;
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
}

export default function Headline({ vehicles, divergence, windowMinutes }) {
  const delays = (vehicles?.features ?? [])
    .map((f) => f.properties.computed_delay_s)
    .filter((d) => d !== null && d !== undefined);

  if (!delays.length) {
    return (
      <div className="hero">
        <p className="hero-kicker">Right now</p>
        <div className="hero-value muted">—</div>
        <p className="muted small">
          Waiting for vehicles to be placed against the timetable.
        </p>
      </div>
    );
  }

  const typical = Math.round(median(delays));
  const late = delays.filter((d) => d > 300).length;
  const corr = divergence?.correlation;

  return (
    <div className="hero">
      <p className="hero-kicker">Right now the typical MBTA vehicle is</p>
      <div className="hero-value" style={{ color: delayColor(typical) }}>
        {formatDelay(typical)}
      </div>
      <p className="muted small">
        Median of {delays.length} vehicles placed against the timetable
        {late > 0 && ` · ${late} more than 5 min late`}
      </p>
      {corr !== null && corr !== undefined && (
        <p className="muted small">
          Agrees with the MBTA's own predictions at r = {corr.toFixed(3)} over
          the last {windowMinutes} min
        </p>
      )}
    </div>
  );
}
