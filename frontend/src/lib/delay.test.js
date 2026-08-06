import { describe, expect, it } from "vitest";
import {
  DELAY_BUCKETS,
  METHOD_LABELS,
  UNKNOWN_COLOR,
  delayColor,
  delayColorExpression,
  formatDelay,
  formatSigned,
  secondsAgo,
} from "./delay.js";

// Walk the MapLibre `step` expression the way the renderer does, so the test
// exercises the encoding rather than re-deriving the bucket from the array.
function evalStep(step, value) {
  let color = step[2];
  for (let i = 3; i < step.length; i += 2) {
    if (value >= step[i]) color = step[i + 1];
  }
  return color;
}

describe("delayColorExpression", () => {
  const expr = delayColorExpression();
  const step = expr[2];

  it("gates on has_delay and falls back to the unknown colour", () => {
    expect(expr[0]).toBe("case");
    expect(expr[1]).toEqual(["get", "has_delay"]);
    expect(expr[3]).toBe(UNKNOWN_COLOR);
  });

  it("never emits Infinity, which MapLibre cannot parse", () => {
    for (const token of step) {
      if (typeof token === "number") expect(Number.isFinite(token)).toBe(true);
    }
  });

  it("emits one stop per bucket boundary", () => {
    // fallback colour + a (threshold, colour) pair for every bucket but the last
    expect(step.length).toBe(3 + (DELAY_BUCKETS.length - 1) * 2);
    expect(step[2]).toBe(DELAY_BUCKETS[0].color);
  });

  it("reads the property it was asked for", () => {
    expect(delayColorExpression("other_field")[2][1]).toEqual([
      "coalesce",
      ["get", "other_field"],
      0,
    ]);
  });
});

// The comment in delay.js claims the map and the legend "can't drift apart".
// Nothing enforced that before this test.
describe("map expression agrees with delayColor", () => {
  const step = delayColorExpression()[2];
  const probes = [-6000, -181, -180, -179, -46, -45, -44, 0, 89, 90, 91, 299, 300, 301, 9000];

  for (const seconds of probes) {
    it(`classifies ${seconds}s the same way`, () => {
      expect(evalStep(step, seconds)).toBe(delayColor(seconds));
    });
  }
});

describe("delayColor", () => {
  it("returns the unknown colour when there is no value", () => {
    expect(delayColor(null)).toBe(UNKNOWN_COLOR);
    expect(delayColor(undefined)).toBe(UNKNOWN_COLOR);
  });

  it("treats a bucket's max as exclusive", () => {
    // -180 is the very_early/early boundary: `seconds < b.max`
    expect(delayColor(-181)).toBe(DELAY_BUCKETS[0].color);
    expect(delayColor(-180)).toBe(DELAY_BUCKETS[1].color);
  });

  it("puts zero in the on-time bucket", () => {
    expect(delayColor(0)).toBe(DELAY_BUCKETS[2].color);
  });

  it("has no gap above the last threshold", () => {
    expect(delayColor(9_999)).toBe(DELAY_BUCKETS[4].color);
  });
});

describe("formatDelay", () => {
  it("dashes a missing value rather than printing 0", () => {
    expect(formatDelay(null)).toBe("—");
    expect(formatDelay(undefined)).toBe("—");
  });

  it("says on time only for exactly zero", () => {
    expect(formatDelay(0)).toBe("on time");
    expect(formatDelay(1)).toBe("1s late");
  });

  it("zero-pads seconds once minutes appear", () => {
    expect(formatDelay(65)).toBe("1m 05s late");
    expect(formatDelay(59)).toBe("59s late");
  });

  it("carries direction in the suffix, not a sign", () => {
    expect(formatDelay(-65)).toBe("1m 05s early");
    expect(formatDelay(-65, { sign: false })).toBe("1m 05s");
    expect(formatDelay(0, { sign: false })).toBe("0s");
  });
});

describe("formatSigned", () => {
  it("dashes a missing value", () => {
    expect(formatSigned(null)).toBe("—");
  });

  it("uses a typographic minus, not a hyphen", () => {
    expect(formatSigned(-5)).toBe("−5s");
    expect(formatSigned(-5)).not.toBe("-5s");
  });

  it("signs positives and leaves zero bare", () => {
    expect(formatSigned(5)).toBe("+5s");
    expect(formatSigned(0)).toBe("0s");
  });

  it("rounds rather than truncating", () => {
    expect(formatSigned(5.6)).toBe("+6s");
  });
});

describe("secondsAgo", () => {
  it("returns null without a timestamp", () => {
    expect(secondsAgo(null)).toBe(null);
  });

  it("clamps a future timestamp to zero instead of going negative", () => {
    expect(secondsAgo(new Date(Date.now() + 60_000).toISOString())).toBe(0);
  });

  it("measures elapsed seconds", () => {
    expect(secondsAgo(new Date(Date.now() - 30_000).toISOString())).toBeCloseTo(30, 0);
  });
});

// These keys come from the `method` column in backend/app/services/delay.py.
// A method added there without a label here renders as "Not placeable".
describe("METHOD_LABELS", () => {
  it("covers every method the estimator emits", () => {
    expect(Object.keys(METHOD_LABELS).sort()).toEqual(
      ["first_stop", "interpolated", "layover", "stopped_at"].sort()
    );
  });
});
