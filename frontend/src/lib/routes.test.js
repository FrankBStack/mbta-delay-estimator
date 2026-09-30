import { describe, expect, it } from "vitest";
import { bounds, matchRoutes, matchVehicles, routeLabel, vehicleLabel } from "./routes.js";

const ROUTES = [
  { route_id: "Red", name: "Red Line", long_name: "Red Line", active_vehicles: 18 },
  { route_id: "Shuttle-Red", name: "Red Line Shuttle", long_name: "Red Line Shuttle", active_vehicles: 0 },
  { route_id: "39", name: "39", long_name: "Forest Hills - Back Bay Station", active_vehicles: 5 },
  { route_id: "390", name: "390", long_name: "Ferry", active_vehicles: 0 },
  { route_id: "132", name: "132", long_name: "Redstone Shopping Center - Malden Center", active_vehicles: 3 },
];

describe("routeLabel", () => {
  it("adds the long name when it says something", () => {
    expect(routeLabel(ROUTES[2])).toBe("39 · Forest Hills - Back Bay Station");
  });

  it("leaves a name that is already the long name alone", () => {
    expect(routeLabel(ROUTES[0])).toBe("Red Line");
  });
});

describe("matchRoutes", () => {
  it("matches a picked suggestion exactly", () => {
    expect(matchRoutes(ROUTES, "39 · Forest Hills - Back Bay Station").exact.route_id).toBe("39");
  });

  it("matches a typed name, ignoring case and spaces", () => {
    expect(matchRoutes(ROUTES, " red line ").exact.route_id).toBe("Red");
    expect(matchRoutes(ROUTES, "39").exact.route_id).toBe("39");
  });

  it("takes the only route that starts with what was typed", () => {
    expect(matchRoutes(ROUTES, "red").exact.route_id).toBe("Red");
    expect(matchRoutes(ROUTES, "forest").exact.route_id).toBe("39");
  });

  it("prefers a route with vehicles out over an idle one", () => {
    expect(matchRoutes(ROUTES, "red l").exact.route_id).toBe("Red");
  });

  it("prefers the whole word to a word that only starts that way", () => {
    // 132 "Redstone…" is out too, but Red Line has the word itself
    expect(matchRoutes(ROUTES, "red").exact.route_id).toBe("Red");
    const shuttleToo = ROUTES.map((r) => (r.route_id === "Shuttle-Red" ? { ...r, active_vehicles: 2 } : r));
    expect(matchRoutes(shuttleToo, "red").partial.map((r) => r.route_id)).toEqual(["Red", "Shuttle-Red"]);
  });

  it("offers the candidates when several start that way", () => {
    const idle = ROUTES.map((r) => ({ ...r, active_vehicles: 0 }));
    const m = matchRoutes(idle, "3");
    expect(m.exact).toBe(null);
    expect(m.partial.map((r) => r.route_id)).toEqual(["39", "390"]);
  });

  it("finds nothing for nothing", () => {
    expect(matchRoutes(ROUTES, "")).toEqual({ exact: null, partial: [] });
    expect(matchRoutes(ROUTES, "zzz")).toEqual({ exact: null, partial: [] });
  });
});

const vehicle = (label, extra = {}) => ({ properties: { label, vehicle_id: `y${label}`, ...extra } });

describe("matchVehicles", () => {
  const FLEET = [
    vehicle("1864", { route_type: 2 }),
    vehicle("1864", { route_type: 3 }),
    vehicle("0723"),
    vehicle("3691-3833"),
    vehicle("LF 0952"),
    vehicle(null),
  ];

  it("finds every vehicle carrying the number", () => {
    expect(matchVehicles(FLEET, "1864").map((f) => f.properties.route_type)).toEqual([2, 3]);
  });

  it("ignores a leading zero on either side", () => {
    expect(matchVehicles(FLEET, "723")).toHaveLength(1);
    expect(matchVehicles(FLEET, "0723")).toHaveLength(1);
    expect(matchVehicles(FLEET, "952")[0].properties.label).toBe("LF 0952");
  });

  it("finds a Green Line pair by either car", () => {
    expect(matchVehicles(FLEET, "3691")).toHaveLength(1);
    expect(matchVehicles(FLEET, "3833")).toHaveLength(1);
  });

  it("does not match a prefix or nothing", () => {
    expect(matchVehicles(FLEET, "18")).toHaveLength(0);
    expect(matchVehicles(FLEET, "")).toHaveLength(0);
  });
});

describe("vehicleLabel", () => {
  it("names the kind, number, route and destination", () => {
    expect(
      vehicleLabel({ route_type: 2, label: "1864", route_name: "Providence/Stoughton Line", headsign: "South Station" })
    ).toBe("Train 1864 · Providence/Stoughton Line to South Station");
    expect(vehicleLabel({ route_type: 3, label: "1864", route_name: "9", headsign: null })).toBe("Bus 1864 · 9");
  });
});

describe("bounds", () => {
  it("spans every line of a multi-line shape", () => {
    expect(
      bounds({
        type: "MultiLineString",
        coordinates: [
          [[-71.1, 42.3], [-71.0, 42.35]],
          [[-71.2, 42.4], [-71.05, 42.32]],
        ],
      })
    ).toEqual([[-71.2, 42.3], [-71.0, 42.4]]);
  });

  it("reads inside a geometry collection", () => {
    expect(
      bounds({
        type: "GeometryCollection",
        geometries: [{ type: "Point", coordinates: [-71, 42] }],
      })
    ).toEqual([[-71, 42], [-71, 42]]);
  });

  it("is null without a geometry", () => {
    expect(bounds(null)).toBe(null);
    expect(bounds({ type: "MultiLineString", coordinates: [] })).toBe(null);
  });
});
