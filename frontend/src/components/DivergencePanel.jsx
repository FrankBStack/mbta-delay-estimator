import { formatSigned, METHOD_LABELS } from "../lib/delay.js";

export default function DivergencePanel({ divergence }) {
  if (!divergence || !divergence.compared) {
    return (
      <p className="muted small">
        Waiting for enough paired observations to compare against the feed.
      </p>
    );
  }

  const {
    correlation,
    mean_divergence_s,
    pct_within_60s,
    compared,
    by_method,
  } = divergence;

  return (
    <div className="panel-block">
      <div className="chart-head">
        <div>
          <h3>Our number vs the MBTA's</h3>
          <p className="muted small">
            {compared.toLocaleString()} observations where both exist
          </p>
        </div>
      </div>

      <div className="tiles">
        <Tile
          value={correlation !== null ? correlation.toFixed(3) : "—"}
          label="Correlation"
          hint="1.0 = perfect agreement on which vehicles are late"
        />
        <Tile
          value={formatSigned(mean_divergence_s)}
          label="Mean difference"
          hint="Positive = we read later than the feed does"
        />
        <Tile
          value={pct_within_60s !== null ? `${pct_within_60s}%` : "—"}
          label="Within 60s"
          hint="Share of observations agreeing to within a minute"
        />
      </div>

      {by_method?.length > 0 && (
        <table className="data-table tight">
          <thead>
            <tr>
              <th>How the vehicle was placed</th>
              <th>Obs</th>
              <th>Mean |diff|</th>
            </tr>
          </thead>
          <tbody>
            {by_method.map((m) => (
              <tr key={m.method}>
                <td>{METHOD_LABELS[m.method] ?? m.method}</td>
                <td className="num">{m.observations.toLocaleString()}</td>
                <td className="num">
                  {m.mean_abs_divergence_s !== null
                    ? `${m.mean_abs_divergence_s}s`
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function Tile({ value, label, hint }) {
  return (
    <div className="tile" title={hint}>
      <div className="tile-value">{value}</div>
      <div className="tile-label">{label}</div>
    </div>
  );
}
