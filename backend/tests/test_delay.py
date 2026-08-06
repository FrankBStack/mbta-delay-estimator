"""The estimator itself: placement methods, the layover rule, the feed join,
and the confidence flags, run against a real PostGIS database with a synthetic
route (see conftest.STATIC_SQL for the geometry and schedule)."""

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from app.services import delay

TZ = ZoneInfo("America/New_York")
SERVICE_DATE = date(2026, 8, 5)


def at(secs, service_date=SERVICE_DATE):
    """Same instant gtfs_ts() produces: noon minus 12h, plus secs, in UTC."""
    noon = datetime.combine(service_date, time(12), tzinfo=TZ).astimezone(timezone.utc)
    return noon - timedelta(hours=12) + timedelta(seconds=secs)


async def observe(conn, ts, lon, *, seq, status, lat=42.35, vehicle="v1"):
    await conn.execute(
        """
        INSERT INTO vehicle_position
            (vehicle_id, trip_id, route_id, direction_id, start_date, ts,
             geom, geom_p, current_status, current_stop_sequence)
        SELECT $1, 'T1', 'R1', 0, $2, $3, g, ST_Transform(g, 26986), $4, $5
        FROM (SELECT ST_SetSRID(ST_MakePoint($6, $7), 4326) AS g) p
        """,
        vehicle, SERVICE_DATE, ts, status, seq, lon, lat,
    )
    ids = [r["id"] for r in await conn.fetch("SELECT id FROM vehicle_position")]
    await delay.compute(conn, ids)
    return await conn.fetchrow(
        "SELECT * FROM delay_observation WHERE vehicle_id = $1", vehicle
    )


async def test_layover_early_floors_at_zero(conn):
    # at the origin at 04:55 for an 05:00 departure: on time, not 5 min early
    row = await observe(conn, at(17700), -71.10, seq=1, status="STOPPED_AT")
    assert row["method"] == "layover"
    assert row["computed_delay_s"] == 0
    assert row["confidence"] == "high"


async def test_layover_after_departure_is_late(conn):
    row = await observe(conn, at(18120), -71.10, seq=1, status="STOPPED_AT")
    assert row["method"] == "layover"
    assert row["computed_delay_s"] == 120


async def test_stopped_at_keeps_sign(conn):
    # early at a mid-route timepoint is genuinely early
    row = await observe(conn, at(18180), -71.09, seq=2, status="STOPPED_AT")
    assert row["method"] == "stopped_at"
    assert row["computed_delay_s"] == -120


async def test_interpolated_prorates_between_stops(conn):
    # 25% along the line = halfway through the leg; scheduled there is 18150
    row = await observe(conn, at(18240), -71.095, seq=2, status="IN_TRANSIT_TO")
    assert row["method"] == "interpolated"
    assert abs(row["computed_delay_s"] - 90) <= 1
    assert row["confidence"] == "high"


async def test_first_stop_measured_against_arrival(conn):
    row = await observe(conn, at(18060), -71.10, seq=1, status="IN_TRANSIT_TO")
    assert row["method"] == "first_stop"
    assert row["computed_delay_s"] == 60
    assert row["confidence"] == "medium"


async def test_overrun_ratio_clamped(conn):
    # past the stop it claims to be heading for: clamp to that stop's time
    row = await observe(conn, at(18300), -71.086, seq=2, status="IN_TRANSIT_TO")
    assert row["method"] == "interpolated"
    assert abs(row["computed_delay_s"]) <= 1
    assert row["confidence"] == "medium"


async def test_off_route_position_is_low_confidence(conn):
    # ~550m north of the shape, past MAX_SNAP_ERROR_M
    row = await observe(conn, at(18300), -71.09, lat=42.355, seq=2, status="STOPPED_AT")
    assert row["snap_error_m"] > 150
    assert row["confidence"] == "low"


async def test_implausible_delay_is_low_confidence(conn):
    row = await observe(conn, at(18300 + 4 * 3600), -71.09, seq=2, status="STOPPED_AT")
    assert row["computed_delay_s"] == 4 * 3600
    assert row["confidence"] == "low"


async def test_feed_join_takes_nearest_prediction(conn):
    obs_ts = at(18240)
    await conn.executemany(
        """
        INSERT INTO trip_update (trip_id, stop_sequence, ts, delay_s)
        VALUES ('T1', 2, $1, $2)
        """,
        [(obs_ts + timedelta(seconds=60), 100),
         (obs_ts + timedelta(seconds=240), 999)],
    )
    row = await observe(conn, obs_ts, -71.095, seq=2, status="IN_TRANSIT_TO")
    assert row["feed_delay_s"] == 100
    assert row["divergence_s"] == row["computed_delay_s"] - 100


async def test_feed_join_ignores_distant_predictions(conn):
    obs_ts = at(18240)
    await conn.execute(
        """
        INSERT INTO trip_update (trip_id, stop_sequence, ts, delay_s)
        VALUES ('T1', 2, $1, 100)
        """,
        obs_ts + timedelta(seconds=400),
    )
    row = await observe(conn, obs_ts, -71.095, seq=2, status="IN_TRANSIT_TO")
    assert row["feed_delay_s"] is None
    assert row["divergence_s"] is None


async def test_no_stop_sequence_is_skipped(conn):
    row = await observe(conn, at(18240), -71.095, seq=None, status="IN_TRANSIT_TO")
    assert row is None


async def test_gtfs_ts_past_midnight(conn):
    got = await conn.fetchval(
        "SELECT gtfs_ts($1, 90000, 'America/New_York')", SERVICE_DATE
    )
    assert got == at(90000)  # 25:00:00 lands on the next calendar day, 01:00


async def test_gtfs_ts_survives_dst_fallback(conn):
    fallback = date(2026, 11, 1)
    got = await conn.fetchval(
        "SELECT gtfs_ts($1, 10800, 'America/New_York')", fallback
    )
    assert got == at(10800, fallback)
