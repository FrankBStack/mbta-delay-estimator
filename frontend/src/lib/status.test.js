import { describe, expect, it } from "vitest";
import {
  FEED_INTERVAL_MS,
  describeStatus,
  formatAge,
  keepLastGood,
  newestTs,
  nextDelay,
  nextVehicleDelay,
} from "./status.js";

const fc = (n) => ({ type: "FeatureCollection", features: Array(n).fill({}) });

describe("nextDelay", () => {
  it("steps 15s, 30s, 60s on failure and stays there", () => {
    expect(nextDelay(15000, false)).toBe(30000);
    expect(nextDelay(30000, false)).toBe(60000);
    expect(nextDelay(60000, false)).toBe(60000);
  });

  it("snaps back on success", () => {
    expect(nextDelay(60000, true)).toBe(15000);
  });
});

describe("nextVehicleDelay", () => {
  const t0 = Date.parse("2026-09-30T02:00:00Z");

  it("aims just after the feed's next update", () => {
    // newest report at t0, asked 3s later: due at t0 + 15s + settle
    expect(nextVehicleDelay(t0, null, t0 + 3000)).toBe(FEED_INTERVAL_MS + 4000 - 3000);
  });

  it("looks again shortly when the positions haven't moved", () => {
    expect(nextVehicleDelay(t0, t0, t0 + 20000)).toBe(5000);
  });

  it("stays between 3s and 19s whatever the clock says", () => {
    expect(nextVehicleDelay(t0, null, t0 + 60000)).toBe(3000);
    expect(nextVehicleDelay(t0, null, t0 - 60000)).toBe(19000);
  });

  it("falls back to the plain cadence with no positions", () => {
    expect(nextVehicleDelay(null, null, t0)).toBe(15000);
  });
});

describe("newestTs", () => {
  it("is the latest report in the collection", () => {
    const v = {
      features: [
        { properties: { ts: "2026-09-30T02:00:00+00:00" } },
        { properties: { ts: "2026-09-30T02:00:12+00:00" } },
        { properties: { ts: "not a time" } },
      ],
    };
    expect(newestTs(v)).toBe(Date.parse("2026-09-30T02:00:12Z"));
    expect(newestTs({ features: [] })).toBe(null);
    expect(newestTs(null)).toBe(null);
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

  it("keeps a failing analytics poll off the map", () => {
    const s = describeStatus({
      error: null,
      analyticsError: "500 Internal Server Error on /api/analytics/divergence",
      health: {},
      feedAgeS: 10,
    });
    expect(s.level).toBe("note");
    expect(s.headline).toBe("Route statistics are not refreshing.");
    expect(s.detail).toContain("500");
  });

  it("says the comparison is paused when only the predictions feed is down", () => {
    const s = describeStatus({
      error: null,
      feedAgeS: 10,
      health: { poller: { trip_updates_error: "ConnectError: no route to host" } },
    });
    expect(s.level).toBe("note");
    expect(s.headline).toMatch(/predictions are unavailable/);
    expect(s.detail).toContain("ConnectError");
  });

  it("attaches the poller's error to a stale feed", () => {
    const s = describeStatus({
      error: null,
      feedAgeS: 400,
      health: { poller: { last_error: "DiskFull: could not extend file" } },
    });
    expect(s.level).toBe("stale");
    expect(s.detail).toContain("DiskFull");
  });

  it("leaves scoring and disk to the operator", () => {
    const s = describeStatus({
      error: null,
      feedAgeS: 10,
      health: {
        poller: { last_score_error: "QueryCanceledError: statement timeout" },
        disk: { free_bytes: 1e9, total_bytes: 30e9 },
      },
    });
    expect(s.level).toBe("ok");
    expect(s.headline).toBe(null);
  });
});
