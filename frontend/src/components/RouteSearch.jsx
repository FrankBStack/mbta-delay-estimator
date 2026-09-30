import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api.js";
import { matchRoutes, matchVehicles, routeLabel, vehicleLabel } from "../lib/routes.js";

// more partial route matches than this and the answer is "type more"
const MAX_CHOICES = 8;

export default function RouteSearch({ routes, routeId, onSelect, onSelectVehicle }) {
  const current = routes.find((r) => r.route_id === routeId);
  const label = current ? routeLabel(current) : "";
  const [text, setText] = useState(label);
  // when the entry matches several things, or nothing
  const [choices, setChoices] = useState(null);
  const [note, setNote] = useState(null);
  const box = useRef(null);

  // a route picked from the chart or the URL shows up here too
  useEffect(() => setText(label), [label]);

  const reset = () => {
    setChoices(null);
    setNote(null);
  };

  // a click anywhere else puts the list away
  useEffect(() => {
    if (!choices) return undefined;
    const away = (e) => {
      if (!box.current?.contains(e.target)) setChoices(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [choices]);

  const pickRoute = (input, route) => {
    reset();
    onSelect(route.route_id);
    // closes the phone keyboard so the map can be seen
    input.blur();
  };
  const pickVehicle = (input, feature) => {
    reset();
    setText("");
    onSelectVehicle(feature);
    input.blur();
  };

  const search = async (input) => {
    const typed = text.trim();
    const { exact, partial } = matchRoutes(routes, typed);
    if (exact) return pickRoute(input, exact);
    let vehicles = [];
    try {
      vehicles = matchVehicles((await api.vehicles()).features, typed);
    } catch {
      // routes alone, then
    }
    const found = [
      ...partial.slice(0, MAX_CHOICES).map((r) => ({
        key: `r-${r.route_id}`,
        label: routeLabel(r),
        pick: () => pickRoute(input, r),
      })),
      ...vehicles.map((f) => ({
        key: `v-${f.properties.vehicle_id}`,
        label: vehicleLabel(f.properties),
        pick: () => pickVehicle(input, f),
      })),
    ];
    if (found.length === 1) found[0].pick();
    else if (found.length) setChoices(found);
    else if (partial.length > MAX_CHOICES) setNote("Type more of the name");
    else setNote(`No route or vehicle called “${typed}” right now`);
  };

  return (
    <div className="route-search" ref={box}>
      <input
        type="text"
        list="route-options"
        placeholder="Route or vehicle"
        aria-label="Find a route or vehicle"
        autoComplete="off"
        enterKeyHint="search"
        value={text}
        onChange={(e) => {
          const v = e.target.value;
          reset();
          setText(v);
          if (!v && routeId) onSelect(null);
          // only a whole suggestion; typing "3" on the way to "39" picks nothing
          const r = routes.find((x) => routeLabel(x) === v);
          if (r) pickRoute(e.target, r);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            if (text.trim()) search(e.target);
          } else if (e.key === "Escape") {
            reset();
            if (routeId) onSelect(null);
          }
        }}
      />
      {routeId && (
        <button className="route-clear" aria-label="Show every route" onClick={() => onSelect(null)}>
          ×
        </button>
      )}
      <datalist id="route-options">
        {routes.map((r) => (
          <option key={r.route_id} value={routeLabel(r)} />
        ))}
      </datalist>
      {choices && (
        <ul className="search-choices" aria-label="Matches">
          {choices.map((c) => (
            <li key={c.key}>
              <button type="button" onClick={c.pick}>
                {c.label}
              </button>
            </li>
          ))}
        </ul>
      )}
      {note && (
        <p className="search-note" role="status">
          {note}
        </p>
      )}
    </div>
  );
}
