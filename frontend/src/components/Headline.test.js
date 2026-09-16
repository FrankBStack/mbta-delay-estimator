import { describe, expect, it } from "vitest";
import { median } from "./Headline.jsx";

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
