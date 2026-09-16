import { describe, expect, it } from "vitest";
import { DELAY_BUCKETS } from "./delay.js";
import { SHAPES, markerImageExpression, markerName, markerNames } from "./markers.js";

// Just enough of the MapLibre expression language to resolve an icon name.
function evaluate(expr, props) {
  if (!Array.isArray(expr)) return expr;
  const [op, ...args] = expr;
  switch (op) {
    case "get":
      return props[args[0]];
    case "coalesce":
      for (const a of args) {
        const v = evaluate(a, props);
        if (v !== null && v !== undefined) return v;
      }
      return null;
    case "case":
      return evaluate(evaluate(args[0], props) ? args[1] : args[2], props);
    case "concat":
      return args.map((a) => evaluate(a, props)).join("");
    case "step": {
      const v = evaluate(args[0], props);
      let out = args[1];
      for (let i = 2; i < args.length; i += 2) if (v >= args[i]) out = args[i + 1];
      return out;
    }
    default:
      throw new Error(`unhandled ${op}`);
  }
}

// one representative delay per bucket, plus "no delay"
const samples = [
  ...DELAY_BUCKETS.map((b, i) => ({
    key: b.key,
    props: { has_delay: true, computed_delay_s: i === 0 ? b.max - 1 : DELAY_BUCKETS[i - 1].max },
  })),
  { key: "unknown", props: { has_delay: false, computed_delay_s: null } },
];

describe("marker images", () => {
  it("the layer only ever asks for names that get registered", () => {
    const registered = new Set(markerNames());
    for (const shape of SHAPES) {
      for (const { key, props } of samples) {
        const name = evaluate(markerImageExpression(), {
          ...props,
          has_bearing: shape === "arrow",
        });
        expect(name).toBe(markerName(shape, key));
        expect(registered.has(name)).toBe(true);
      }
    }
  });

  it("registers one image per shape and bucket", () => {
    expect(markerNames().length).toBe(SHAPES.length * (DELAY_BUCKETS.length + 1));
  });
});
