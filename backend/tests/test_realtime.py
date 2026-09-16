"""Ingest filtering and pruning, against the same synthetic route."""

from datetime import timedelta

from google.transit import gtfs_realtime_pb2 as gtfs_rt

from app.services import realtime
from tests.test_delay import SERVICE_DATE, at


def vehicles_msg(*vehicles):
    msg = gtfs_rt.FeedMessage()
    msg.header.timestamp = int(at(18240).timestamp())
    for vid, trip_id, seq in vehicles:
        e = msg.entity.add()
        e.id = vid
        e.vehicle.vehicle.id = vid
        e.vehicle.trip.trip_id = trip_id
        e.vehicle.trip.start_date = SERVICE_DATE.strftime("%Y%m%d")
        e.vehicle.current_stop_sequence = seq
        e.vehicle.position.latitude = 42.35
        e.vehicle.position.longitude = -71.095
        e.vehicle.timestamp = msg.header.timestamp
    return msg


def updates_msg(trip_id, seqs):
    msg = gtfs_rt.FeedMessage()
    msg.header.timestamp = int(at(18240).timestamp())
    e = msg.entity.add()
    e.id = "u"
    e.trip_update.trip.trip_id = trip_id
    e.trip_update.trip.start_date = SERVICE_DATE.strftime("%Y%m%d")
    for seq in seqs:
        stu = e.trip_update.stop_time_update.add()
        stu.stop_sequence = seq
        stu.arrival.time = int(at(18300 + 60 * seq).timestamp())
    return msg


def test_wanted_stops_is_current_and_next():
    keep = realtime.wanted_stops(vehicles_msg(("v1", "T1", 2), ("v2", "T2", 3)))
    assert keep == {("T1", 2), ("T1", 3), ("T2", 3), ("T2", 4)}


async def test_ingest_keeps_only_wanted_stops(conn):
    # the fixture schedules via trip_stop_offset only; the ingest joins stop_time
    await conn.execute(
        "INSERT INTO stop_time VALUES ('T1', 2, 'ST2', 18300, 18360)"
        " ON CONFLICT DO NOTHING"
    )
    keep = realtime.wanted_stops(vehicles_msg(("v1", "T1", 2)))
    n = await realtime.ingest_trip_updates(conn, updates_msg("T1", [1, 2, 3]), keep)
    rows = await conn.fetch("SELECT stop_sequence, delay_s FROM trip_update ORDER BY 1")
    assert n == 2
    assert [r["stop_sequence"] for r in rows] == [2, 3]
    # seq 2: predicted 18420 against scheduled arrival 18300
    assert rows[0]["delay_s"] == 120


async def test_ingest_without_filter_keeps_everything(conn):
    n = await realtime.ingest_trip_updates(conn, updates_msg("T1", [1, 2, 3]))
    assert n == 3


async def test_prune_deletes_in_batches(conn):
    realtime.PRUNE_BATCH, saved = 7, realtime.PRUNE_BATCH
    try:
        old = at(0) - timedelta(days=400)
        await conn.executemany(
            "INSERT INTO trip_update (trip_id, stop_sequence, ts) VALUES ('T1', $1, $2)",
            [(i, old + timedelta(seconds=i)) for i in range(20)],
        )
        await conn.execute(
            "INSERT INTO trip_update (trip_id, stop_sequence, ts) VALUES ('T1', 99, now())"
        )
        deleted = await realtime.prune(conn)
    finally:
        realtime.PRUNE_BATCH = saved
    assert deleted["trip_update"] == 20
    assert await conn.fetchval("SELECT count(*) FROM trip_update") == 1
