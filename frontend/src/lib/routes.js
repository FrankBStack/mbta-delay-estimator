// What the route search offers and matches: "39 · Forest Hills - Back Bay
// Station", or just "Red Line" where the long name adds nothing.
export function routeLabel(r) {
  return r.long_name && r.long_name !== r.name ? `${r.name} · ${r.long_name}` : r.name;
}

// Routes for what was typed. A picked suggestion or a typed name matches
// exactly; otherwise the routes whose name starts that way, for a chooser,
// unless that leaves just one. "red" means the Red Line: a route with that
// whole word beats one that merely begins with the letters (Redstone), and
// a route with vehicles out beats the shuttle that replaces it some weekends.
export function matchRoutes(routes, text) {
  const t = text.trim().toLowerCase();
  if (!t) return { exact: null, partial: [] };
  const exact =
    routes.find((r) => routeLabel(r).toLowerCase() === t) ??
    routes.find((r) => r.name.toLowerCase() === t) ??
    null;
  if (exact) return { exact, partial: [] };
  const narrow = (list, keep) => {
    const kept = list.filter(keep);
    return kept.length ? kept : list;
  };
  let partial = routes.filter(
    (r) => r.name.toLowerCase().startsWith(t) || r.long_name?.toLowerCase().startsWith(t)
  );
  partial = narrow(partial, (r) =>
    `${r.name} ${r.long_name ?? ""}`.toLowerCase().split(/[^a-z0-9]+/).includes(t)
  );
  partial = narrow(partial, (r) => r.active_vehicles > 0);
  return partial.length === 1 ? { exact: partial[0], partial: [] } : { exact: null, partial };
}

// Vehicles by the number on them. Labels come as "1864", "0723", the pair
// "3691-3833" or "LF 0952", and nobody types the leading zero.
const keyOf = (s) => String(s).toLowerCase().replace(/^0+(?=\d)/, "");

export function matchVehicles(features, text) {
  const t = keyOf(text.trim());
  if (!t) return [];
  return features.filter((f) =>
    String(f.properties.label ?? "")
      .split(/[\s-]+/)
      .some((part) => part && keyOf(part) === t)
  );
}

const KIND = { 0: "Train", 1: "Train", 2: "Train", 3: "Bus", 4: "Boat" };

// "Train 1864 · Providence/Stoughton Line to South Station"
export function vehicleLabel(p) {
  const kind = KIND[p.route_type] ?? "Vehicle";
  const route = p.route_name ?? "no route";
  return `${kind} ${p.label ?? p.vehicle_id} · ${route}${p.headsign ? ` to ${p.headsign}` : ""}`;
}

// [[west, south], [east, north]] of any GeoJSON geometry, or null if empty
export function bounds(geometry) {
  let w = Infinity;
  let s = Infinity;
  let e = -Infinity;
  let n = -Infinity;
  const walk = (c) => {
    if (typeof c[0] === "number") {
      w = Math.min(w, c[0]);
      e = Math.max(e, c[0]);
      s = Math.min(s, c[1]);
      n = Math.max(n, c[1]);
      return;
    }
    for (const x of c) walk(x);
  };
  if (geometry?.type === "GeometryCollection") {
    for (const g of geometry.geometries) if (g.coordinates) walk(g.coordinates);
  } else if (geometry?.coordinates) {
    walk(geometry.coordinates);
  }
  return w === Infinity ? null : [[w, s], [e, n]];
}
