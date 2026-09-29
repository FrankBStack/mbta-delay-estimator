export const RETRY_DELAY_MS = 400;
export const TIMEOUT_MS = 10000;

// A request that dies before any response is almost always a kept-alive
// connection the network dropped while the tab sat idle. One retry opens a
// fresh connection; a real outage fails the retry too.
async function fetchOnceMore(url, signal) {
  try {
    return await fetch(url, { signal });
  } catch (first) {
    if (signal.aborted) throw first;
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    try {
      return await fetch(url, { signal });
    } catch {
      throw first;
    }
  }
}

// A connection that dies without closing leaves a request that never settles,
// and the poll waiting on it would stop for good. The deadline covers the body
// too.
async function get(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined)
  );
  const url = qs.toString() ? `${path}?${qs}` : path;
  const ctl = new AbortController();
  const timer = setTimeout(
    () => ctl.abort(new Error(`No response in ${TIMEOUT_MS / 1000}s on ${url}`)),
    TIMEOUT_MS
  );
  try {
    const resp = await fetchOnceMore(url, ctl.signal);
    if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} on ${url}`);
    return await resp.json();
  } finally {
    clearTimeout(timer);
  }
}

// Shapes are static for the life of the page, and hovering across the map
// asks for the same few dozen over and over.
const shapes = new Map();

function routeShape(routeId) {
  if (!shapes.has(routeId)) {
    const p = get(`/api/routes/${encodeURIComponent(routeId)}/shape`).catch((e) => {
      shapes.delete(routeId);
      throw e;
    });
    shapes.set(routeId, p);
  }
  return shapes.get(routeId);
}

export const api = {
  vehicles: (params) => get("/api/vehicles", params),
  routes: (params) => get("/api/routes", params),
  routeShape,
  delayByRoute: (params) => get("/api/analytics/delay-by-route", params),
  divergence: (params) => get("/api/analytics/divergence", params),
  timeline: (params) => get("/api/analytics/timeline", params),
  health: () => get("/api/analytics/health"),
};
