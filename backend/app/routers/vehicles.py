from typing import Optional

from fastapi import APIRouter, Query

from .. import cache, db

router = APIRouter(prefix="/api", tags=["vehicles"])


@router.get("/vehicles")
async def vehicles(
    max_age_s: int = Query(300, ge=30, le=3600),
    route_id: Optional[str] = None,
    route_type: Optional[int] = Query(None, ge=0, le=7),
):
    """Latest position per vehicle, as GeoJSON.

    The delay join is LEFT: a vehicle on a trip we can't place still belongs on
    the map, just without a number attached.
    """
    return await cache.get_or_set(
        ("vehicles", max_age_s, route_id, route_type),
        lambda: _vehicles(max_age_s, route_id, route_type),
    )


async def _vehicles(max_age_s, route_id, route_type):
    rows = await db.pool().fetch(
        """
        WITH latest AS (
            SELECT DISTINCT ON (vp.vehicle_id)
                   vp.vehicle_id, vp.label, vp.trip_id, vp.route_id, vp.direction_id,
                   vp.ts, vp.bearing, vp.speed, vp.current_status,
                   vp.current_stop_sequence, vp.stop_id,
                   ST_X(vp.geom) AS lon, ST_Y(vp.geom) AS lat
            FROM vehicle_position vp
            WHERE vp.ts > now() - ($1 || ' seconds')::interval
            ORDER BY vp.vehicle_id, vp.ts DESC
        )
        SELECT l.*,
               r.route_short_name, r.route_long_name, r.route_type,
               r.route_color, r.route_text_color,
               t.trip_headsign,
               s.stop_name,
               d.computed_delay_s, d.feed_delay_s, d.divergence_s,
               d.method, d.confidence
        FROM latest l
        LEFT JOIN route r ON r.route_id = l.route_id
        LEFT JOIN trip  t ON t.trip_id  = l.trip_id
        LEFT JOIN stop  s ON s.stop_id  = l.stop_id
        LEFT JOIN delay_observation d
               ON d.vehicle_id = l.vehicle_id AND d.ts = l.ts
        WHERE ($2::text IS NULL OR l.route_id = $2::text)
          AND ($3::int  IS NULL OR r.route_type = $3::int)
        """,
        str(max_age_s),
        route_id,
        route_type,
    )

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
            "properties": {
                "vehicle_id": r["vehicle_id"],
                "label": r["label"],
                "route_id": r["route_id"],
                "route_name": r["route_short_name"] or r["route_long_name"],
                "route_type": r["route_type"],
                "route_color": f"#{r['route_color']}" if r["route_color"] else None,
                "headsign": r["trip_headsign"],
                "direction_id": r["direction_id"],
                "bearing": r["bearing"],
                "speed": r["speed"],
                "status": r["current_status"],
                "next_stop": r["stop_name"],
                "ts": r["ts"].isoformat(),
                "computed_delay_s": r["computed_delay_s"],
                "feed_delay_s": r["feed_delay_s"],
                "divergence_s": r["divergence_s"],
                "method": r["method"],
                "confidence": r["confidence"],
            },
        }
        for r in rows
    ]
    return {"type": "FeatureCollection", "features": features}


@router.get("/vehicles/{vehicle_id}/history")
async def history(vehicle_id: str, minutes: int = Query(60, ge=5, le=720)):
    """Breadcrumb trail with the delay computed at each point."""
    rows = await db.pool().fetch(
        """
        SELECT vp.ts, ST_X(vp.geom) AS lon, ST_Y(vp.geom) AS lat,
               d.computed_delay_s, d.feed_delay_s, d.divergence_s,
               d.method, d.confidence, d.frac
        FROM vehicle_position vp
        LEFT JOIN delay_observation d
               ON d.vehicle_id = vp.vehicle_id AND d.ts = vp.ts
        WHERE vp.vehicle_id = $1
          AND vp.ts > now() - ($2 || ' minutes')::interval
        ORDER BY vp.ts
        """,
        vehicle_id,
        str(minutes),
    )
    return {
        "vehicle_id": vehicle_id,
        "points": [
            {
                "ts": r["ts"].isoformat(),
                "lon": r["lon"],
                "lat": r["lat"],
                "frac": r["frac"],
                "computed_delay_s": r["computed_delay_s"],
                "feed_delay_s": r["feed_delay_s"],
                "divergence_s": r["divergence_s"],
                "method": r["method"],
                "confidence": r["confidence"],
            }
            for r in rows
        ],
    }
