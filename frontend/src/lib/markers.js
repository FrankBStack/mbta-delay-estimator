import { DELAY_BUCKETS, UNKNOWN_COLOR, delayBucketExpression } from "./delay.js";

// One raster image per (shape, delay bucket). The layer picks one by name
// with a data-driven icon-image expression, and MapLibre rotates it by the
// feed's bearing. Symbol icons can't be recolored per feature unless they
// are SDFs, so the colors are baked in here instead.

const SIZE = 32;
const RADIUS = 9;
const TIP = 14; // distance from center to the nose; > RADIUS makes the point
const RING = "#12121a";
const RING_UNKNOWN = "#6a6a68";

export const SHAPES = ["arrow", "dot"];

const FILLS = [
  ...DELAY_BUCKETS.map((b) => [b.key, b.color, RING]),
  ["unknown", UNKNOWN_COLOR, RING_UNKNOWN],
];

export function markerName(shape, bucket) {
  return `veh-${shape}-${bucket}`;
}

export function markerNames() {
  return SHAPES.flatMap((shape) => FILLS.map(([key]) => markerName(shape, key)));
}

export function markerImageExpression() {
  return [
    "concat",
    "veh-",
    ["case", ["get", "has_bearing"], "arrow", "dot"],
    "-",
    delayBucketExpression(),
  ];
}

function draw(shape, color, ring, scale) {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = SIZE * scale;
  const ctx = canvas.getContext("2d");
  ctx.scale(scale, scale);
  const c = SIZE / 2;
  ctx.beginPath();
  if (shape === "arrow") {
    // circle body with a nose pointing north; the tangent points sit at
    // ±t from straight up
    const t = Math.acos(RADIUS / TIP);
    ctx.arc(c, c, RADIUS, -Math.PI / 2 + t, (3 * Math.PI) / 2 - t);
    ctx.lineTo(c, c - TIP);
    ctx.closePath();
  } else {
    ctx.arc(c, c, RADIUS, 0, 2 * Math.PI);
  }
  ctx.fillStyle = color;
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = ring;
  ctx.stroke();
  return ctx.getImageData(0, 0, canvas.width, canvas.height);
}

export function addMarkerImages(map) {
  const scale = Math.min(window.devicePixelRatio || 1, 3);
  for (const shape of SHAPES) {
    for (const [key, color, ring] of FILLS) {
      map.addImage(markerName(shape, key), draw(shape, color, ring, scale), {
        pixelRatio: scale,
      });
    }
  }
}
