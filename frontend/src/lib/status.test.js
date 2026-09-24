import { describe, expect, it } from "vitest";
import { describeStatus, formatAge, keepLastGood, nextDelay } from "./status.js";

const fc = (n) => ({ type: "FeatureCollection", features: Array(n).fill({}) });

describe("nextDelay", () => {
  it("steps 5s, 15s, 30s on failure and stays there", () => {
    expect(nextDelay(5000, false)).toBe(15000);
    expect(nextDelay(15000, false)).toBe(30000);
    expect(nextDelay(30000, false)).toBe(30000);
  });

  it("snaps back on success", () => {
    expect(nextDelay(30000, true)).toBe(5000);
  });
});

describe("formatAge", () => {
  it("picks a unit a person would", () => {
    expect(formatAge(45)).toBe("45s");
    expect(formatAge(200)).toBe("3 min");
    expect(formatAge(7200)).toBe("2 h");
    expect(formatAge(null)).toBe(null);
  });
});

describe("keepLastGood", () => {
  it("holds the previous positions when the feed is stale and the poll is empty", () => {
    const prev = fc(3);
    expect(keepLastGood(prev, fc(0), true)).toBe(prev);
  });

  it("accepts an empty poll when the feed is fresh", () => {
    const next = fc(0);
    expect(keepLastGood(fc(3), next, false)).toBe(next);
  });

  it("accepts new positions whenever they arrive", () => {
    const next = fc(2);
    expect(keepLastGood(fc(3), next, true)).toBe(next);
  });
});

describe("describeStatus", () => {
  it("is quiet when everything is fine", () => {
    expect(describeStatus({ error: null, health: {}, feedAgeS: 12 })).toEqual({
      level: "ok",
      headline: null,
      detail: null,
    });
  });

  it("reports a failing API for a visitor and keeps the raw error as detail", () => {
    const s = describeStatus({ error: "Failed to fetch", health: null, feedAgeS: null });
    expect(s.level).toBe("down");
    expect(s.headline).not.toMatch(/uvicorn|8010|fetch/);
    expect(s.detail).toBe("Failed to fetch");
  });

  it("calls an old feed stale, not down", () => {
    const s = describeStatus({ error: null, health: {}, feedAgeS: 240 });
    expect(s.level).toBe("stale");
    expect(s.headline).toBe("Positions last updated 4 min ago.");
  });

  it("keeps a failing analytics poll off the outage banner", () => {
    const s = describeStatus({
      error: null,
      analyticsError: "500 Internal Server Error on /api/analytics/divergence",
      health: {},
      feedAgeS: 10,
    });
    expect(s.level).toBe("stale");
    expect(s.headline).toBe("Route statistics are not refreshing.");
    expect(s.detail).toContain("500");
  });

  it("surfaces a poller error and low disk in plain words", () => {
    const s = describeStatus({
      error: null,
      feedAgeS: 400,
      health: {
        poller: { last_error: "DiskFull: could not extend file" },
        disk: { free_bytes: 1e9, total_bytes: 30e9 },
      },
    });
    expect(s.level).toBe("stale");
    expect(s.headline).toContain("problem storing data");
    expect(s.headline).toContain("low on disk space");
    expect(s.detail).toContain("DiskFull");
    expect(s.detail).toContain("1 GB free of 30 GB");
  });
});
