export const RETRY_DELAY_MS = 400;

// A request that dies before any response is almost always a kept-alive
// connection the network dropped while the tab sat idle. One retry opens a
// fresh connection; a real outage fails the retry too.
async function fetchOnceMore(url) {
  try {
    return await fetch(url);
  } catch (first) {
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    try {
      return await fetch(url);
    } catch {
      throw first;
    }
  }
}

async function get(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined)
  );
  const url = qs.toString() ? `${path}?${qs}` : path;
  const resp = await fetchOnceMore(url);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} on ${url}`);
  return resp.json();
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
