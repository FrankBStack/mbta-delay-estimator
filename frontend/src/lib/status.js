// What the page should say about the health of its data, and how hard to poll.

export const POLL_STEPS_MS = [5000, 15000, 30000];
export const STALE_AFTER_S = 90;
export const LOW_DISK_FRACTION = 0.1;

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

// level: ok | stale | down. `headline` is written for a visitor; `detail` is
// the raw message for whoever is debugging.
export function describeStatus({ error, analyticsError, health, feedAgeS }) {
  if (error) {
    return {
      level: "down",
      headline:
        "Live data is unavailable right now. The map shows the last positions received.",
      detail: error,
    };
  }

  const notes = [];
  const details = [];
  const poller = health?.poller;
  const disk = health?.disk;

  if (feedAgeS !== null && feedAgeS !== undefined && feedAgeS > STALE_AFTER_S) {
    notes.push(`Positions last updated ${formatAge(feedAgeS)} ago.`);
  }
  if (poller?.last_error) {
    notes.push("The server reported a problem storing data.");
    details.push(poller.last_error);
  }
  // the map is still live; only the route figures are behind
  if (analyticsError) {
    notes.push("Route statistics are not refreshing.");
    details.push(analyticsError);
  }
  if (disk?.total_bytes && disk.free_bytes / disk.total_bytes < LOW_DISK_FRACTION) {
    notes.push("The server is low on disk space.");
    details.push(
      `${Math.round(disk.free_bytes / 1e9)} GB free of ${Math.round(disk.total_bytes / 1e9)} GB`
    );
  }

  if (!notes.length) return { level: "ok", headline: null, detail: null };
  return { level: "stale", headline: notes.join(" "), detail: details.join(" · ") || null };
}
