// The mode, window and route live in the URL so a reload or a shared link
// keeps them.

export const MODES = [
  { value: null, label: "All", slug: null },
  { value: 1, label: "Subway", slug: "subway" },
  { value: 0, label: "Light rail", slug: "light-rail" },
  { value: 3, label: "Bus", slug: "bus" },
  { value: 2, label: "Commuter", slug: "commuter" },
];

export const WINDOWS = [15, 60, 180];
const DEFAULT_WINDOW = 60;

export function readFilters(search) {
  const q = new URLSearchParams(search);
  const mode = MODES.find((m) => m.slug && m.slug === q.get("mode"));
  const w = Number(q.get("window"));
  return {
    routeType: mode ? mode.value : null,
    windowMinutes: WINDOWS.includes(w) ? w : DEFAULT_WINDOW,
    routeId: q.get("route")?.slice(0, 64) || null,
  };
}

// defaults are left out, so the plain address stays plain
export function filterSearch({ routeType, windowMinutes, routeId }) {
  const q = new URLSearchParams();
  const mode = MODES.find((m) => m.value === routeType);
  if (mode?.slug) q.set("mode", mode.slug);
  if (windowMinutes !== DEFAULT_WINDOW) q.set("window", String(windowMinutes));
  if (routeId) q.set("route", routeId);
  const s = q.toString();
  return s ? `?${s}` : "";
}
