"""Why a vehicle on the map carries no delay figure."""

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app import db
from app.routers import vehicles
from app.services import delay


async def position(conn, vehicle, *, trip, route, seq, status="IN_TRANSIT_TO"):
    now = datetime.now(UTC)
    await conn.execute(
        """
        INSERT INTO vehicle_position
            (vehicle_id, trip_id, route_id, direction_id, start_date, ts,
             geom, geom_p, current_status, current_stop_sequence)
        SELECT $1, $2, $3, 0, $4, $5, g, ST_Transform(g, 26986), $6, $7
        FROM (SELECT ST_SetSRID(ST_MakePoint(-71.09, 42.35), 4326) AS g) p
        """,
        vehicle, trip, route, now.astimezone(ZoneInfo("America/New_York")).date(), now, status, seq,
    )


async def test_no_delay_reason_names_the_cause(conn, monkeypatch):
    # _vehicles only calls .fetch on the pool, which a connection also has
    monkeypatch.setattr(db, "_pool", conn)
    await position(conn, "shuttle", trip="BL-1", route="Shuttle-Generic", seq=None)
    await position(conn, "added", trip="ADDED-1", route="R1", seq=5)
    await position(conn, "variant", trip="T1-OL1", route="R1", seq=2)
    await position(conn, "noseq", trip="T1", route="R1", seq=None)
    await position(conn, "placed", trip="T1", route="R1", seq=2, status="STOPPED_AT")
    ids = [r["id"] for r in await conn.fetch("SELECT id FROM vehicle_position")]
    await delay.compute(conn, ids)

    out = await vehicles._vehicles(300, None, None)
    reasons = {
        f["properties"]["vehicle_id"]: f["properties"]["no_delay_reason"] for f in out["features"]
    }
    assert reasons == {
        "shuttle": "shuttle",
        "added": "added_trip",
        "variant": "unknown_trip",
        "noseq": "no_stop_sequence",
        "placed": None,
    }
