import { describe, expect, it } from "vitest";
import { niceTicks, shortName, textOn, truncate } from "./DelayByRouteChart.jsx";

describe("shortName", () => {
  it("drops the redundant suffix that pushed names past the gutter", () => {
    expect(shortName("Framingham/Worcester Line")).toBe("Framingham/Worcester");
    expect(shortName("Hingham Ferry")).toBe("Hingham");
  });

  it("leaves bus routes alone", () => {
    expect(shortName("1")).toBe("1");
    expect(shortName("SL4")).toBe("SL4");
  });

  it("only strips a trailing suffix", () => {
    expect(shortName("Blue Line Shuttle")).toBe("Blue Line Shuttle");
    expect(shortName("Green Line B")).toBe("Green Line B");
  });

  it("survives a missing name", () => {
    expect(shortName(null)).toBe("");
    expect(shortName(undefined)).toBe("");
  });

  it("keeps distinct routes distinct", () => {
    expect(shortName("Winthrop Ferry")).not.toBe(shortName("Winthrop/Quincy Ferry"));
  });
});

describe("truncate", () => {
  it("leaves anything that fits", () => {
    expect(truncate("Red", 10)).toBe("Red");
    expect(truncate("exactly10!", 10)).toBe("exactly10!");
  });

  it("never exceeds the budget, ellipsis included", () => {
    const out = truncate("Providence/Stoughton", 15);
    expect(out).toBe("Providence/Sto…");
    expect(out.length).toBe(15);
  });

  it("coerces non-strings", () => {
    expect(truncate(null, 5)).toBe("");
    expect(truncate(12345678, 5)).toBe("1234…");
  });
});

describe("niceTicks", () => {
  it("includes zero whenever the domain spans it", () => {
    expect(niceTicks(-120, 300)).toContain(0);
  });

  it("returns ascending values", () => {
    const ticks = niceTicks(-400, 900);
    expect([...ticks].sort((a, b) => a - b)).toEqual(ticks);
  });

  it("widens the step on a wide domain to avoid crowding", () => {
    const narrow = niceTicks(0, 300);
    const wide = niceTicks(0, 3000);
    const stepOf = (t) => t[1] - t[0];
    expect(stepOf(wide)).toBeGreaterThan(stepOf(narrow));
  });

  it("stays inside the domain", () => {
    for (const t of niceTicks(-200, 700)) {
      expect(t).toBeGreaterThanOrEqual(-200);
      expect(t).toBeLessThanOrEqual(700);
    }
  });
});

describe("textOn", () => {
  it("puts dark text on the light route colours", () => {
    expect(textOn("#FFC72C")).toBe("#111"); // bus yellow
    expect(textOn("#7C878E")).toBe("#111"); // Silver Line
    expect(textOn("#ED8B00")).toBe("#111"); // Orange Line
  });

  it("puts white text on the dark ones", () => {
    expect(textOn("#003DA5")).toBe("#fff"); // Blue Line
    expect(textOn("#80276C")).toBe("#fff"); // commuter rail
    expect(textOn("#DA291C")).toBe("#fff"); // Red Line
  });

  it("falls back to white for a colour it can't read", () => {
    expect(textOn(undefined)).toBe("#fff");
  });
});
