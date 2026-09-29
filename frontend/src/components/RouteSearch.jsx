import { useEffect, useState } from "react";
import { findRoute, routeLabel } from "../lib/routes.js";

export default function RouteSearch({ routes, routeId, onSelect }) {
  const current = routes.find((r) => r.route_id === routeId);
  const label = current ? routeLabel(current) : "";
  const [text, setText] = useState(label);

  // a route picked from the chart or the URL shows up here too
  useEffect(() => setText(label), [label]);

  const pick = (input, route) => {
    onSelect(route.route_id);
    // closes the phone keyboard so the map can be seen
    input.blur();
  };

  return (
    <div className="route-search">
      <input
        type="text"
        list="route-options"
        placeholder="Find a route"
        aria-label="Find a route"
        autoComplete="off"
        enterKeyHint="search"
        value={text}
        onChange={(e) => {
          const v = e.target.value;
          setText(v);
          if (!v && routeId) onSelect(null);
          // only a whole suggestion; typing "3" on the way to "39" picks nothing
          const r = routes.find((x) => routeLabel(x) === v);
          if (r) pick(e.target, r);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            const r = findRoute(routes, text);
            if (r) pick(e.target, r);
          } else if (e.key === "Escape" && routeId) {
            onSelect(null);
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
    </div>
  );
}
