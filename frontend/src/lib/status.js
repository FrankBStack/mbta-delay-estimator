// What the page should say about the health of its data, and how hard to poll.

export const POLL_STEPS_MS = [15000, 30000, 60000];
export const STALE_AFTER_S = 90;

// The poller writes every 15s and the API caches for 5s, so asking more often
// only downloads the same positions again. Aim just after the next update is
// due; if the answer hasn't moved yet, look again shortly.
export const FEED_INTERVAL_MS = 15000;
const FEED_SETTLE_MS = 4000;
const RECHECK_MS = 5000;
const MIN_POLL_MS = 3000;

export function newestTs(vehicles) {
  let newest = null;
  for (const f of vehicles?.features ?? []) {
    const t = Date.parse(f.properties.ts);
    if (!Number.isNaN(t) && (newest === null || t > newest)) newest = t;
  }
  return newest;
}

export function nextVehicleDelay(newestMs, prevNewestMs, nowMs) {
  if (newestMs === null) return POLL_STEPS_MS[0];
  if (newestMs === prevNewestMs) return RECHECK_MS;
  const due = newestMs + FEED_INTERVAL_MS + FEED_SETTLE_MS - nowMs;
  // clamped so a visitor's wrong clock can't stall or hammer the poll
  return Math.min(Math.max(due, MIN_POLL_MS), FEED_INTERVAL_MS + FEED_SETTLE_MS);
}

// Back off while requests fail so a struggling server isn't hammered by every
// open tab; snap back to the fast cadence on the first success.
export function nextDelay(prevMs, ok) {
  if (ok) return POLL_STEPS_MS[0];
  const i = POLL_STEPS_MS.indexOf(prevMs);
  return POLL_STEPS_MS[Math.min(i + 1, POLL_STEPS_MS.length - 1)];
}

export function formatAge(seconds) {
  if (seconds === null || seconds === undefined) return null;
  if (seconds < 90) return `${seconds}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${Math.round(seconds / 3600)} h`;
}

// A poll that comes back empty while the feed is stale means the stored
// positions have aged out, not that the fleet vanished. Keep what we had.
export function keepLastGood(prev, next, stale) {
  if (!next) return prev;
  if (stale && next.features.length === 0 && prev?.features.length) return prev;
  return next;
}

// level: ok | note | stale | down. Only stale and down mean the map itself is
// behind; a note is something beside it. `headline` is written for a visitor;
// `detail` is the raw message for whoever is debugging. Operator concerns
// (scoring, disk) stay in /api/analytics/health and off the page.
export function describeStatus({ error, analyticsError, health, feedAgeS }) {
  if (error) {
    return {
      level: "down",
      headline:
        "Live data is unavailable right now. The map shows the last positions received.",
      detail: error,
    };
  }

  const poller = health?.poller;
  if (feedAgeS !== null && feedAgeS !== undefined && feedAgeS > STALE_AFTER_S) {
    return {
      level: "stale",
      headline: `Positions last updated ${formatAge(feedAgeS)} ago.`,
      detail: poller?.last_error ?? null,
    };
  }

  const notes = [];
  const details = [];
  if (poller?.trip_updates_error) {
    notes.push("MBTA predictions are unavailable; delays are still computed from positions.");
    details.push(poller.trip_updates_error);
  }
  if (analyticsError) {
    notes.push("Route statistics are not refreshing.");
    details.push(analyticsError);
  }

  if (!notes.length) return { level: "ok", headline: null, detail: null };
  return { level: "note", headline: notes.join(" "), detail: details.join(" · ") };
}
