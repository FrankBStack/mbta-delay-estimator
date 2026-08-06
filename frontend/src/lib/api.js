async function get(path, params = {}) {
  const qs = new URLSearchParams(
    Object.entries(params).filter(([, v]) => v !== null && v !== undefined)
  );
  const url = qs.toString() ? `${path}?${qs}` : path;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`${resp.status} ${resp.statusText} on ${url}`);
  return resp.json();
}

export const api = {
  vehicles: (params) => get("/api/vehicles", params),
  routes: (params) => get("/api/routes", params),
  routeShape: (routeId) => get(`/api/routes/${encodeURIComponent(routeId)}/shape`),
  delayByRoute: (params) => get("/api/analytics/delay-by-route", params),
  divergence: (params) => get("/api/analytics/divergence", params),
  timeline: (params) => get("/api/analytics/timeline", params),
  health: () => get("/api/analytics/health"),
};
