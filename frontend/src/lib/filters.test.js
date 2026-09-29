import { describe, expect, it } from "vitest";
import { MODES, WINDOWS, filterSearch, readFilters } from "./filters.js";

describe("readFilters", () => {
  it("defaults to every mode over the last hour", () => {
    expect(readFilters("")).toEqual({ routeType: null, windowMinutes: 60 });
  });

  it("reads a mode and window", () => {
    expect(readFilters("?mode=light-rail&window=15")).toEqual({
      routeType: 0,
      windowMinutes: 15,
    });
  });

  it("ignores values the page doesn't offer", () => {
    expect(readFilters("?mode=ferry&window=7")).toEqual({ routeType: null, windowMinutes: 60 });
  });
});

describe("filterSearch", () => {
  it("leaves the defaults out", () => {
    expect(filterSearch({ routeType: null, windowMinutes: 60 })).toBe("");
  });

  it("round-trips every mode and window", () => {
    for (const m of MODES) {
      for (const w of WINDOWS) {
        const f = { routeType: m.value, windowMinutes: w };
        expect(readFilters(filterSearch(f))).toEqual(f);
      }
    }
  });
});
