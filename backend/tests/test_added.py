"""Added trips borrow the timetable of the scheduled trip they most nearly run
as, the way every Green Line train has to."""

from datetime import UTC, datetime

from google.transit import gtfs_realtime_pb2 as gtfs_rt

from app import db
from app.routers import vehicles
from app.services import realtime, scoring
from tests.test_delay import SERVICE_DATE, at, observe


def prediction(trip_id, seq, stop_id, arrival):
    msg = gtfs_rt.FeedMessage()
    msg.header.gtfs_realtime_version = "2.0"
    msg.header.timestamp = int(arrival.timestamp()) - 60
    e = msg.entity.add()
    e.id = "u"
    e.trip_update.trip.trip_id = trip_id
    e.trip_update.trip.start_date = SERVICE_DATE.strftime("%Y%m%d")
    stu = e.trip_update.stop_time_update.add()
    stu.stop_sequence = seq
    stu.stop_id = stop_id
    stu.arrival.time = int(arrival.timestamp())
    return msg


async def test_an_added_trip_is_matched_to_the_nearest_slot_and_scored(conn, monkeypatch):
    # stopped at ST2 at 05:07 with the feed's own numbering: two minutes behind
    # the 05:05 slot that T1 and T2 both have there
    row = await observe(conn, at(18420), -71.09, seq=20, status="STOPPED_AT",
                        trip="ADDED-1", stop="ST2")
    match = await conn.fetchrow("SELECT * FROM added_trip_match")
    assert match["trip_id"] == "ADDED-1"
    assert match["scheduled_trip_id"] in ("T1", "T2")
    assert (match["matched_stop_id"], match["offset_s"]) == ("ST2", 120)
    assert row["trip_id"] == "ADDED-1"
    assert (row["method"], row["computed_delay_s"]) == ("stopped_at", 120)

    # the feed's figure for the same stop reads the matched timetable too
    await realtime.ingest_trip_updates(conn, prediction("ADDED-1", 20, "ST2", at(18420)))
    assert await conn.fetchval("SELECT delay_s FROM trip_update") == 120

    # then on the way to ST3, halfway along the leg at 05:09: interpolated
    # against the same slot, and paired with the feed
    row = await observe(conn, at(18540), -71.085, seq=30, status="IN_TRANSIT_TO",
                        trip="ADDED-1", stop="ST3")
    assert (row["method"], row["computed_delay_s"]) == ("interpolated", 60)
    assert await conn.fetchval("SELECT count(*) FROM added_trip_match") == 1


async def test_no_slot_within_an_hour_means_no_match(conn):
    # 07:05 at ST2; the nearest timetable there is 05:05
    row = await observe(conn, at(25500), -71.09, seq=20, status="STOPPED_AT",
                        trip="ADDED-2", stop="ST2")
    assert row is None
    assert await conn.fetchval("SELECT count(*) FROM added_trip_match") == 0


async def test_the_map_says_which_figures_are_against_a_matched_slot(conn, monkeypatch):
    # the endpoint only reads the last few minutes, so this one runs on the clock
    now = datetime.now(UTC)
    await conn.execute(
        """
        INSERT INTO vehicle_position
            (vehicle_id, trip_id, route_id, direction_id, start_date, ts, geom, geom_p,
             current_status, current_stop_sequence, stop_id)
        SELECT v.id, v.trip, 'R1', 0, $1, $2, g, ST_Transform(g, 26986), 'STOPPED_AT', 20, 'ST2'
        FROM (VALUES ('matched', 'ADDED-4'), ('unmatched', 'ADDED-5')) v(id, trip),
             (SELECT ST_SetSRID(ST_MakePoint(-71.09, 42.35), 4326) AS g) p
        """,
        SERVICE_DATE, now,
    )
    await conn.execute(
        "INSERT INTO added_trip_match VALUES ('ADDED-4', $1, 'T1', $2, 'ST2', 0)",
        SERVICE_DATE, now,
    )
    await conn.execute(
        """
        INSERT INTO delay_observation
            (vehicle_id, trip_id, route_id, direction_id, ts, frac, snap_error_m,
             scheduled_time, computed_delay_s, method, confidence)
        VALUES ('matched', 'ADDED-4', 'R1', 0, $1, 0.5, 0, $1, 90, 'stopped_at', 'high')
        """,
        now,
    )
    monkeypatch.setattr(db, "_pool", conn)
    by_id = {
        f["properties"]["vehicle_id"]: f["properties"]
        for f in (await vehicles._vehicles(None, None))["features"]
    }
    m, u = by_id["matched"], by_id["unmatched"]
    assert (m["computed_delay_s"], m["slot_matched"], m["no_delay_reason"]) == (90, True, None)
    assert (u["computed_delay_s"], u["slot_matched"], u["no_delay_reason"]) == (
        None, False, "added_trip"
    )


async def test_an_arrival_on_an_added_trip_is_scored(conn):
    await observe(conn, at(18150), -71.095, seq=20, status="IN_TRANSIT_TO",
                  trip="ADDED-3", stop="ST2")
    await observe(conn, at(18360), -71.09, seq=20, status="STOPPED_AT",
                  trip="ADDED-3", stop="ST2")
    assert await scoring.score(conn, at(18000), at(19000)) == 1
    row = await conn.fetchrow("SELECT trip_id, stop_sequence, scheduled_time FROM arrival_score")
    assert (row["trip_id"], row["stop_sequence"]) == ("ADDED-3", 20)
    assert row["scheduled_time"] == at(18300)
