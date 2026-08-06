import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { delayColorExpression } from "../lib/delay.js";

const BASEMAP = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const BOSTON = { center: [-71.0789, 42.3465], zoom: 11.4 };

// Ease between the last two reported positions rather than snapping. Both ends
// are real points from the feed; only the transition is interpolated.
const TWEEN_MS = 900;

export default function MapView({
  vehicles,
  routeShape,
  selectedVehicleId,
  onSelectVehicle,
}) {
  const container = useRef(null);
  const map = useRef(null);
  const ready = useRef(false);
  const tracks = useRef(new Map()); // vehicle_id -> {from, to, start, props}
  const frame = useRef(null);

  useEffect(() => {
    if (map.current) return;
    map.current = new maplibregl.Map({
      container: container.current,
      style: BASEMAP,
      ...BOSTON,
      attributionControl: { compact: true },
    });
    const m = map.current;
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

    m.on("load", () => {
      m.addSource("route-shape", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "route-shape-line",
        type: "line",
        source: "route-shape",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#3987e5"],
          "line-width": 3,
          "line-opacity": 0.75,
        },
      });

      m.addSource("vehicles", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });

      m.addLayer({
        id: "vehicles-circle",
        type: "circle",
        source: "vehicles",
        paint: {
          "circle-color": delayColorExpression(),
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            9, 3.5,
            12, 5.5,
            15, 8,
          ],
          // dark ring separates vehicles where they cluster downtown; muted
          // ring and washed fill mark the ones that could not be placed
          "circle-stroke-width": 2,
          "circle-stroke-color": ["case", ["get", "has_delay"], "#12121a", "#6a6a68"],
          "circle-opacity": ["case", ["get", "has_delay"], 0.95, 0.4],
        },
      });

      m.addLayer({
        id: "vehicles-selected",
        type: "circle",
        source: "vehicles",
        filter: ["==", ["get", "vehicle_id"], ""],
        paint: {
          "circle-color": "rgba(0,0,0,0)",
          "circle-radius": [
            "interpolate", ["linear"], ["zoom"],
            9, 7, 12, 10, 15, 13,
          ],
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
        },
      });

      m.on("click", "vehicles-circle", (e) => {
        const f = e.features?.[0];
        if (f) onSelectVehicle?.(f.properties.vehicle_id);
      });
      m.on("mouseenter", "vehicles-circle", () => {
        m.getCanvas().style.cursor = "pointer";
      });
      m.on("mouseleave", "vehicles-circle", () => {
        m.getCanvas().style.cursor = "";
      });
      m.on("click", (e) => {
        const hits = m.queryRenderedFeatures(e.point, { layers: ["vehicles-circle"] });
        if (!hits.length) onSelectVehicle?.(null);
      });

      ready.current = true;
    });

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, [onSelectVehicle]);

  useEffect(() => {
    if (!map.current || !vehicles) return;

    const now = performance.now();
    const next = new Map();
    for (const f of vehicles.features) {
      const id = f.properties.vehicle_id;
      const to = f.geometry.coordinates;
      const existing = tracks.current.get(id);
      // start from where it's currently drawn, not its last reported point,
      // otherwise an update mid-animation snaps backwards
      const from = existing ? currentPoint(existing, now) : to;
      const moved = !existing || existing.to[0] !== to[0] || existing.to[1] !== to[1];
      next.set(id, {
        from,
        to,
        start: moved ? now : existing.start,
        props: f.properties,
      });
    }
    tracks.current = next;

    const render = () => {
      const t = performance.now();
      const features = [];
      let animating = false;
      for (const [id, track] of tracks.current) {
        if ((t - track.start) / TWEEN_MS < 1) animating = true;
        const d = track.props.computed_delay_s;
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: currentPoint(track, t) },
          properties: {
            ...track.props,
            vehicle_id: id,
            has_delay: d !== null && d !== undefined,
          },
        });
      }
      const src = map.current?.getSource("vehicles");
      if (src) src.setData({ type: "FeatureCollection", features });
      frame.current = animating ? requestAnimationFrame(render) : null;
    };

    if (ready.current) {
      if (frame.current) cancelAnimationFrame(frame.current);
      render();
    } else {
      map.current.once("load", render);
    }
  }, [vehicles]);

  useEffect(() => {
    if (!map.current || !ready.current) return;
    if (map.current.getLayer("vehicles-selected")) {
      map.current.setFilter("vehicles-selected", [
        "==",
        ["get", "vehicle_id"],
        selectedVehicleId ?? "",
      ]);
    }
  }, [selectedVehicleId, vehicles]);

  useEffect(() => {
    if (!map.current) return;
    const apply = () => {
      const src = map.current?.getSource("route-shape");
      if (!src) return;
      src.setData(routeShape ?? { type: "FeatureCollection", features: [] });
    };
    if (ready.current) apply();
    else map.current.once("load", apply);
  }, [routeShape]);

  return <div ref={container} className="map" />;
}

function currentPoint(track, now) {
  const progress = Math.min(1, Math.max(0, (now - track.start) / TWEEN_MS));
  const e = 1 - Math.pow(1 - progress, 3); // easeOutCubic
  return [
    track.from[0] + (track.to[0] - track.from[0]) * e,
    track.from[1] + (track.to[1] - track.from[1]) * e,
  ];
}
