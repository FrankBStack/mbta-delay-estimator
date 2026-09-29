import { describe, expect, it } from "vitest";
import { median, noun, splitDelays, subject } from "./Headline.jsx";

const feature = (props) => ({ properties: props });

describe("noun", () => {
  it("names the mode the filter selected", () => {
    expect(noun(3)).toBe("bus");
    expect(noun(3, 212)).toBe("buses");
    expect(noun(1)).toBe("subway train");
    expect(noun(0, 2)).toBe("light rail trains");
    expect(noun(2)).toBe("commuter train");
  });

  it("says vehicle when no mode is selected", () => {
    expect(noun(null)).toBe("vehicle");
    expect(noun(undefined, 5)).toBe("vehicles");
  });

  it("falls back for a mode without a name", () => {
    expect(noun(5, 3)).toBe("vehicles");
  });
});

describe("subject", () => {
  it("puts the picked route's name before its mode", () => {
    expect(subject({ name: "39", route_type: 3 }, null)).toBe("39 bus");
    expect(subject({ name: "Red Line", route_type: 1 }, 3, 4)).toBe("Red Line subway trains");
  });

  it("is the mode's noun without a route", () => {
    expect(subject(null, 3, 2)).toBe("buses");
    expect(subject(null, null)).toBe("vehicle");
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

describe("splitDelays", () => {
  it("counts idle layovers separately instead of as on time", () => {
    const { delays, waiting } = splitDelays([
      feature({ method: "layover", computed_delay_s: 0 }),
      feature({ method: "layover", computed_delay_s: 0 }),
      feature({ method: "interpolated", computed_delay_s: 90 }),
      feature({ method: "stopped_at", computed_delay_s: -30 }),
    ]);
    expect(delays).toEqual([90, -30]);
    expect(waiting).toBe(2);
  });

  it("keeps a layover that is late leaving", () => {
    const { delays, waiting } = splitDelays([
      feature({ method: "layover", computed_delay_s: 200 }),
    ]);
    expect(delays).toEqual([200]);
    expect(waiting).toBe(0);
  });

  it("counts a vehicle still heading to its first stop ahead of time as waiting", () => {
    const { delays, waiting } = splitDelays([
      feature({ method: "first_stop", computed_delay_s: 0 }),
      feature({ method: "first_stop", computed_delay_s: 120 }),
    ]);
    expect(delays).toEqual([120]);
    expect(waiting).toBe(1);
  });

  it("leaves out low-confidence figures, as the analytics do", () => {
    const { delays, waiting } = splitDelays([
      feature({ method: "interpolated", computed_delay_s: 1296, confidence: "low" }),
      feature({ method: "layover", computed_delay_s: 0, confidence: "low" }),
      feature({ method: "interpolated", computed_delay_s: 40, confidence: "high" }),
    ]);
    expect(delays).toEqual([40]);
    expect(waiting).toBe(0);
  });

  it("counts vehicles with no figure as having no timetable", () => {
    const { delays, waiting, noTimetable } = splitDelays([
      feature({ method: null, computed_delay_s: null }),
      feature({ method: "interpolated" }),
      feature({ method: "interpolated", computed_delay_s: 1296, confidence: "low" }),
    ]);
    expect(delays).toEqual([]);
    expect(waiting).toBe(0);
    expect(noTimetable).toBe(2);
  });
});
