// What the route search offers and matches: "39 · Forest Hills - Back Bay
// Station", or just "Red Line" where the long name adds nothing.
export function routeLabel(r) {
  return r.long_name && r.long_name !== r.name ? `${r.name} · ${r.long_name}` : r.name;
}

// A picked suggestion matches its label exactly; a typed "39" or "red line"
// matches the name.
export function findRoute(routes, text) {
  const t = text.trim().toLowerCase();
  if (!t) return null;
  return (
    routes.find((r) => routeLabel(r).toLowerCase() === t) ??
    routes.find((r) => r.name.toLowerCase() === t) ??
    null
  );
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
