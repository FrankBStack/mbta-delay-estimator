// Diverging scale: blue for early, gray in the middle, warm for late. All five
// steps clear 3:1 against the dark basemap.

export const DELAY_BUCKETS = [
  { key: "very_early", max: -180, color: "#86b6ef", label: "3+ min early" },
  { key: "early", max: -45, color: "#3987e5", label: "45s-3 min early" },
  { key: "on_time", max: 90, color: "#898781", label: "On time (−45s to +90s)" },
  { key: "late", max: 300, color: "#ec835a", label: "90s-5 min late" },
  { key: "very_late", max: Infinity, color: "#d03b3b", label: "5+ min late" },
];

export const UNKNOWN_COLOR = "#4a4a48";

export function delayColor(seconds) {
  if (seconds === null || seconds === undefined) return UNKNOWN_COLOR;
  return DELAY_BUCKETS.find((b) => seconds < b.max)?.color ?? "#d03b3b";
}

// Same scale as a MapLibre expression, built off the same array so the map and
// the legend can't drift apart.
//
// Uses has_delay rather than testing for null: step needs a number and throws
// at style-eval time if you hand it null, instead of falling through.
export function delayColorExpression(property = "computed_delay_s") {
  const step = ["step", ["coalesce", ["get", property], 0], DELAY_BUCKETS[0].color];
  for (let i = 0; i < DELAY_BUCKETS.length - 1; i++) {
    step.push(DELAY_BUCKETS[i].max, DELAY_BUCKETS[i + 1].color);
  }
  return ["case", ["get", "has_delay"], step, UNKNOWN_COLOR];
}

export function formatDelay(seconds, { sign = true } = {}) {
  if (seconds === null || seconds === undefined) return "—";
  const abs = Math.abs(seconds);
  const mins = Math.floor(abs / 60);
  const secs = abs % 60;
  const body = mins > 0 ? `${mins}m ${String(secs).padStart(2, "0")}s` : `${secs}s`;
  if (!sign) return body;
  if (seconds === 0) return "on time";
  return seconds > 0 ? `${body} late` : `${body} early`;
}

export function formatSigned(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  return `${s > 0 ? "+" : s < 0 ? "−" : ""}${Math.abs(s)}s`;
}

export function formatClock(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function secondsAgo(iso) {
  if (!iso) return null;
  return Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
}

export const METHOD_LABELS = {
  interpolated: "Interpolated between stops",
  stopped_at: "Stopped at a mid-route stop",
  layover: "On layover at origin",
  first_stop: "Approaching first stop",
};
