import { describe, expect, it } from "vitest";
import { MODES, WINDOWS, filterSearch, readFilters } from "./filters.js";

describe("readFilters", () => {
  it("defaults to every mode over the last hour", () => {
    expect(readFilters("")).toEqual({ routeType: null, windowMinutes: 60, routeId: null });
  });

  it("reads a mode, window and route", () => {
    expect(readFilters("?mode=light-rail&window=15&route=Green-B")).toEqual({
      routeType: 0,
      windowMinutes: 15,
      routeId: "Green-B",
    });
  });

  it("ignores values the page doesn't offer", () => {
    expect(readFilters("?mode=ferry&window=7&route=")).toEqual({
      routeType: null,
      windowMinutes: 60,
      routeId: null,
    });
  });
});

describe("filterSearch", () => {
  it("leaves the defaults out", () => {
    expect(filterSearch({ routeType: null, windowMinutes: 60, routeId: null })).toBe("");
  });

  it("round-trips every mode and window, with and without a route", () => {
    for (const m of MODES) {
      for (const w of WINDOWS) {
        for (const routeId of [null, "39", "CR-Franklin", "Green-B"]) {
          const f = { routeType: m.value, windowMinutes: w, routeId };
          expect(readFilters(filterSearch(f))).toEqual(f);
        }
      }
    }
  });
});
