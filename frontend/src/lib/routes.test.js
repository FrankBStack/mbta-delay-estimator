import { describe, expect, it } from "vitest";
import { bounds, findRoute, routeLabel } from "./routes.js";

const ROUTES = [
  { route_id: "Red", name: "Red Line", long_name: "Red Line" },
  { route_id: "39", name: "39", long_name: "Forest Hills - Back Bay Station" },
  { route_id: "390", name: "390", long_name: "Ferry" },
];

describe("routeLabel", () => {
  it("adds the long name when it says something", () => {
    expect(routeLabel(ROUTES[1])).toBe("39 · Forest Hills - Back Bay Station");
  });

  it("leaves a name that is already the long name alone", () => {
    expect(routeLabel(ROUTES[0])).toBe("Red Line");
  });
});

describe("findRoute", () => {
  it("matches a picked suggestion", () => {
    expect(findRoute(ROUTES, "39 · Forest Hills - Back Bay Station").route_id).toBe("39");
  });

  it("matches a typed name exactly, ignoring case and spaces", () => {
    expect(findRoute(ROUTES, " red line ").route_id).toBe("Red");
    expect(findRoute(ROUTES, "39").route_id).toBe("39");
  });

  it("does not guess from a prefix", () => {
    expect(findRoute(ROUTES, "3")).toBe(null);
    expect(findRoute(ROUTES, "")).toBe(null);
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
