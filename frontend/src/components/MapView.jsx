import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import { formatDelay } from "../lib/delay.js";
import { addMarkerImages, markerImageExpression } from "../lib/markers.js";

const BASEMAP = "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";
const BOSTON = { center: [-71.0789, 42.3465], zoom: 11.4 };

// Ease between the last two reported positions rather than snapping. Both ends
// are real points from the feed; only the transition is interpolated.
const TWEEN_MS = 900;

export default function MapView({
  vehicles,
  routeShape,
  hoverShape,
  selectedVehicleId,
  onSelectVehicle,
  onHoverVehicle,
  stale = false,
}) {
  const container = useRef(null);
  const map = useRef(null);
  const ready = useRef(false);
  const popup = useRef(null);
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
      addMarkerImages(m);

      // hovered route sits under the selected one
      m.addSource("route-hover", {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      m.addLayer({
        id: "route-hover-line",
        type: "line",
        source: "route-hover",
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          "line-color": ["coalesce", ["get", "color"], "#3987e5"],
          "line-width": 2,
          "line-opacity": 0.45,
        },
      });

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
        id: "vehicles-icon",
        type: "symbol",
        source: "vehicles",
        layout: {
          "icon-image": markerImageExpression(),
          "icon-rotate": ["get", "bearing"],
          "icon-rotation-alignment": "map",
          // every vehicle renders, even where they pile up downtown
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          // the image body is 9px at size 1; trains a third larger. Zoom has
          // to be the outer expression, so the mode factor sits in each stop.
          "icon-size": [
            "interpolate", ["linear"], ["zoom"],
            9, ["case", ["get", "is_rail"], 0.54, 0.4],
            12, ["case", ["get", "is_rail"], 0.84, 0.62],
            15, ["case", ["get", "is_rail"], 1.2, 0.9],
          ],
          "symbol-sort-key": ["case", ["get", "is_rail"], 2, 1],
        },
        paint: {
          "icon-opacity": ["case", ["get", "has_delay"], 0.95, 0.45],
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

      popup.current = new maplibregl.Popup({
        closeButton: false,
        closeOnClick: false,
        offset: 12,
        maxWidth: "240px",
        className: "vehicle-popup",
      });

      m.on("click", "vehicles-icon", (e) => {
        const f = e.features?.[0];
        if (f) onSelectVehicle?.(f.properties.vehicle_id);
      });
      m.on("mouseenter", "vehicles-icon", () => {
        m.getCanvas().style.cursor = "pointer";
      });
      m.on("mousemove", "vehicles-icon", (e) => {
        const f = e.features?.[0];
        if (!f) return;
        popup.current
          .setLngLat(f.geometry.coordinates)
          .setDOMContent(tooltip(f.properties))
          .addTo(m);
        onHoverVehicle?.(f.properties.vehicle_id);
      });
      m.on("mouseleave", "vehicles-icon", () => {
        m.getCanvas().style.cursor = "";
        popup.current.remove();
        onHoverVehicle?.(null);
      });
      m.on("click", (e) => {
        const hits = m.queryRenderedFeatures(e.point, { layers: ["vehicles-icon"] });
        if (!hits.length) onSelectVehicle?.(null);
      });

      ready.current = true;
    });

    return () => {
      if (frame.current) cancelAnimationFrame(frame.current);
      popup.current?.remove();
      m.remove();
      map.current = null;
      ready.current = false;
    };
  }, [onSelectVehicle, onHoverVehicle]);

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
        const { computed_delay_s: d, bearing, route_type } = track.props;
        features.push({
          type: "Feature",
          geometry: { type: "Point", coordinates: currentPoint(track, t) },
          properties: {
            ...track.props,
            vehicle_id: id,
            has_delay: d !== null && d !== undefined,
            has_bearing: bearing !== null && bearing !== undefined,
            bearing: bearing ?? 0,
            is_rail: route_type === 0 || route_type === 1 || route_type === 2,
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

  useSourceData(map, ready, "route-shape", routeShape);
  useSourceData(map, ready, "route-hover", hoverShape);

  return <div ref={container} className="map" data-stale={stale} />;
}

const EMPTY = { type: "FeatureCollection", features: [] };

function useSourceData(map, ready, sourceId, data) {
  useEffect(() => {
    if (!map.current) return;
    const apply = () => {
      map.current?.getSource(sourceId)?.setData(data ?? EMPTY);
    };
    if (ready.current) apply();
    else map.current.once("load", apply);
  }, [map, ready, sourceId, data]);
}

// DOM, not an HTML string: route names and headsigns come from the feed
function tooltip(p) {
  const el = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${p.route_name ?? "—"} · ${p.label ?? p.vehicle_id}`;
  const headsign = document.createElement("div");
  headsign.className = "muted";
  headsign.textContent = p.headsign ?? "Unknown destination";
  const delay = document.createElement("div");
  delay.textContent =
    p.computed_delay_s === null || p.computed_delay_s === undefined
      ? "Not placeable"
      : formatDelay(p.computed_delay_s);
  el.append(title, headsign, delay);
  return el;
}

function currentPoint(track, now) {
  const progress = Math.min(1, Math.max(0, (now - track.start) / TWEEN_MS));
  const e = 1 - Math.pow(1 - progress, 3); // easeOutCubic
  return [
    track.from[0] + (track.to[0] - track.from[0]) * e,
    track.from[1] + (track.to[1] - track.from[1]) * e,
  ];
}
