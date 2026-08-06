import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from .. import db

router = APIRouter(prefix="/api", tags=["routes"])

ROUTE_TYPE_NAMES = {
    0: "Light rail",
    1: "Subway",
    2: "Commuter rail",
    3: "Bus",
    4: "Ferry",
}


@router.get("/routes")
async def list_routes(active_only: bool = Query(False)):
    rows = await db.pool().fetch(
        """
        SELECT r.route_id, r.route_short_name, r.route_long_name, r.route_type,
               r.route_color, r.route_text_color, r.route_sort_order,
               count(DISTINCT v.vehicle_id) AS active_vehicles
        FROM route r
        LEFT JOIN vehicle_position v
               ON v.route_id = r.route_id AND v.ts > now() - interval '5 minutes'
        GROUP BY r.route_id, r.route_short_name, r.route_long_name, r.route_type,
                 r.route_color, r.route_text_color, r.route_sort_order
        HAVING NOT $1::boolean OR count(DISTINCT v.vehicle_id) > 0
        ORDER BY r.route_sort_order NULLS LAST, r.route_id
        """,
        active_only,
    )
    return [
        {
            "route_id": r["route_id"],
            "name": r["route_short_name"] or r["route_long_name"],
            "long_name": r["route_long_name"],
            "route_type": r["route_type"],
            "route_type_name": ROUTE_TYPE_NAMES.get(r["route_type"], "Other"),
            "color": f"#{r['route_color']}" if r["route_color"] else "#888888",
            "text_color": f"#{r['route_text_color']}" if r["route_text_color"] else "#ffffff",
            "active_vehicles": r["active_vehicles"],
        }
        for r in rows
    ]


@router.get("/routes/{route_id}/shape")
async def route_shape(route_id: str, simplify_m: Optional[float] = Query(5.0, ge=0, le=100)):
    """Route geometry as GeoJSON.

    A route has one shape per pattern and direction and most of them overlap,
    so collect and simplify -- the map only needs the line, not every survey
    point. LEFT JOIN because Shuttle-Generic is a real route with real vehicles
    and no fixed alignment; missing shape is not a missing route.
    """
    row = await db.pool().fetchrow(
        """
        SELECT r.route_id, r.route_short_name, r.route_long_name,
               r.route_color, r.route_type,
               ST_AsGeoJSON(
                   ST_Simplify(ST_Collect(DISTINCT sh.geom), $2::double precision / 111000.0)
               ) AS geojson
        FROM route r
        LEFT JOIN trip  t  ON t.route_id  = r.route_id
        LEFT JOIN shape sh ON sh.shape_id = t.shape_id
        WHERE r.route_id = $1
        GROUP BY r.route_id, r.route_short_name, r.route_long_name,
                 r.route_color, r.route_type
        """,
        route_id,
        simplify_m,
    )
    if row is None:
        raise HTTPException(404, f"unknown route {route_id}")

    return {
        "type": "Feature",
        "geometry": json.loads(row["geojson"]) if row["geojson"] else None,
        "properties": {
            "route_id": row["route_id"],
            "name": row["route_short_name"] or row["route_long_name"],
            "color": f"#{row['route_color']}" if row["route_color"] else "#888888",
            "route_type": row["route_type"],
            "has_geometry": row["geojson"] is not None,
        },
    }
