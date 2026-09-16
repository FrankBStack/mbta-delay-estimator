import { describe, expect, it } from "vitest";
import { median, noun } from "./Headline.jsx";

describe("noun", () => {
  it("names the mode the filter selected", () => {
    expect(noun(3)).toBe("bus");
    expect(noun(3, 212)).toBe("buses");
    expect(noun(1)).toBe("subway train");
    expect(noun(0, 2)).toBe("Green Line trains");
    expect(noun(2)).toBe("commuter train");
  });

  it("says vehicle when no mode is selected", () => {
    expect(noun(null)).toBe("vehicle");
    expect(noun(undefined, 5)).toBe("vehicles");
  });

  it("falls back for a mode without a name", () => {
    expect(noun(4, 3)).toBe("vehicles");
  });
});

describe("median", () => {
  it("is null for no values", () => {
    expect(median([])).toBe(null);
  });

  it("takes the middle of an odd count", () => {
    expect(median([5, -3, 100])).toBe(5);
  });

  it("averages the two middle values of an even count", () => {
    expect(median([1, 2, 3, 10])).toBe(2.5);
  });

  it("does not sort the caller's array", () => {
    const input = [3, 1, 2];
    median(input);
    expect(input).toEqual([3, 1, 2]);
  });
});
