import {
  delayColor,
  formatClock,
  formatDelay,
  formatSigned,
  METHOD_LABELS,
  secondsAgo,
} from "../lib/delay.js";

function direction(seconds, suffix) {
  if (seconds === null || seconds === undefined) return `No ${suffix} value`;
  if (seconds === 0) return `On time (${suffix})`;
  return `${seconds > 0 ? "Late" : "Early"} (${suffix})`;
}

export default function VehicleCard({ vehicle, onClose }) {
  if (!vehicle) return null;
  const p = vehicle.properties;
  const age = secondsAgo(p.ts);

  return (
    <div className="panel-block vehicle-card">
      <div className="chart-head">
        <div>
          <h3>
            <span
              className="chip"
              style={{ background: delayColor(p.computed_delay_s) }}
            />
            Route {p.route_name ?? "—"} · {p.label ?? p.vehicle_id}
          </h3>
          <p className="muted small">
            {p.headsign ?? "Unknown destination"}
          </p>
        </div>
        <button className="ghost-btn" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="tiles two">
        <div className="tile">
          <div
            className="tile-value"
            style={{ color: delayColor(p.computed_delay_s) }}
          >
            {formatDelay(p.computed_delay_s, { sign: false })}
          </div>
          <div className="tile-label">{direction(p.computed_delay_s, "computed")}</div>
        </div>
        <div className="tile">
          <div className="tile-value">
            {formatDelay(p.feed_delay_s, { sign: false })}
          </div>
          {/* the figures drop the sign, so the label has to carry it */}
          <div className="tile-label">{direction(p.feed_delay_s, "predicted")}</div>
        </div>
      </div>

      <dl className="kv">
        <dt>Difference</dt>
        <dd>{formatSigned(p.divergence_s)}</dd>
        <dt>Placed by</dt>
        <dd>{METHOD_LABELS[p.method] ?? "Not placeable"}</dd>
        <dt>Confidence</dt>
        <dd className={`conf conf-${p.confidence ?? "none"}`}>
          {p.confidence ?? "—"}
        </dd>
        <dt>Status</dt>
        <dd>{(p.status ?? "—").replace(/_/g, " ").toLowerCase()}</dd>
        <dt>Next stop</dt>
        <dd>{p.next_stop ?? "—"}</dd>
        <dt>Reported</dt>
        <dd>
          {formatClock(p.ts)}
          {age !== null && <span className="muted"> · {age}s ago</span>}
        </dd>
      </dl>
    </div>
  );
}
