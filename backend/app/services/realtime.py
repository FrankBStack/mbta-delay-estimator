"""Poll the GTFS-realtime feeds into Postgres.

VehiclePositions gives us where things are. TripUpdates gives predicted arrival
times -- note there is no `delay` field in the MBTA's feed, so we derive one
here by subtracting the scheduled time for the same trip and stop.
"""

import asyncio
import datetime as dt
import json
import logging

import httpx
from google.transit import gtfs_realtime_pb2 as gtfs_rt

from .. import db
from ..config import (
    AGENCY_TZ,
    BACKFILL_HOURS,
    POLL_INTERVAL_S,
    PROJECTED_SRID,
    RETENTION_HOURS,
    TRIP_UPDATES_URL,
    VEHICLE_POSITIONS_URL,
)
from . import delay

log = logging.getLogger("tracker.realtime")

_STATUS = {0: "INCOMING_AT", 1: "STOPPED_AT", 2: "IN_TRANSIT_TO"}

STATE = {
    "last_poll": None,
    "last_error": None,
    "feed_timestamp": None,
    "vehicles_seen": 0,
    "positions_inserted": 0,
    "trip_updates_inserted": 0,
    "delays_computed": 0,
    "polls": 0,
    "last_prune": None,
    "last_prune_error": None,
}

RETENTION = {
    "vehicle_position": RETENTION_HOURS,
    "delay_observation": RETENTION_HOURS,
    "trip_update": BACKFILL_HOURS,
}


def _date(value):
    if not value or len(value) != 8:
        return None
    try:
        return dt.date(int(value[:4]), int(value[4:6]), int(value[6:8]))
    except ValueError:
        return None


def _utc(epoch):
    return dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc)


async def fetch(client, url):
    resp = await client.get(url)
    resp.raise_for_status()
    msg = gtfs_rt.FeedMessage()
    msg.ParseFromString(resp.content)
    return msg


async def ingest_vehicles(conn, msg):
    """Insert positions, return ids of the rows that were actually new.

    The feed keeps republishing a vehicle at its old timestamp when it has
    nothing fresher, so the unique constraint dedupes and we skip recomputing
    delays for vehicles that haven't moved.
    """
    cols = [[] for _ in range(14)]
    for entity in msg.entity:
        if not entity.HasField("vehicle"):
            continue
        v = entity.vehicle
        if not v.HasField("position") or not v.HasField("timestamp"):
            continue
        pos = v.position
        trip = v.trip if v.HasField("trip") else None
        vid = v.vehicle.id or entity.id
        if not vid:
            continue
        values = [
            vid,
            v.vehicle.label or None,
            (trip.trip_id or None) if trip else None,
            (trip.route_id or None) if trip else None,
            (trip.direction_id if trip and trip.HasField("direction_id") else None),
            _date(trip.start_date) if trip else None,
            _utc(v.timestamp),
            pos.longitude,
            pos.latitude,
            pos.bearing if pos.HasField("bearing") else None,
            pos.speed if pos.HasField("speed") else None,
            _STATUS.get(v.current_status) if v.HasField("current_status") else None,
            v.current_stop_sequence if v.HasField("current_stop_sequence") else None,
            v.stop_id or None,
        ]
        for i, value in enumerate(values):
            cols[i].append(value)

    STATE["vehicles_seen"] = len(cols[0])
    if not cols[0]:
        return []

    rows = await conn.fetch(
        f"""
        INSERT INTO vehicle_position
            (vehicle_id, label, trip_id, route_id, direction_id, start_date, ts,
             geom, geom_p, bearing, speed, current_status, current_stop_sequence, stop_id)
        SELECT vehicle_id, label, trip_id, route_id, direction_id, start_date, ts,
               ST_SetSRID(ST_MakePoint(lon, lat), 4326),
               ST_Transform(ST_SetSRID(ST_MakePoint(lon, lat), 4326), {PROJECTED_SRID}),
               bearing, speed, current_status, current_stop_sequence, stop_id
        FROM unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::smallint[],
                    $6::date[], $7::timestamptz[], $8::double precision[],
                    $9::double precision[], $10::real[], $11::real[], $12::text[],
                    $13::integer[], $14::text[])
             AS t(vehicle_id, label, trip_id, route_id, direction_id, start_date, ts,
                  lon, lat, bearing, speed, current_status, current_stop_sequence, stop_id)
        ON CONFLICT (vehicle_id, ts) DO NOTHING
        RETURNING id
        """,
        *cols,
    )
    return [r["id"] for r in rows]


async def ingest_trip_updates(conn, msg):
    """Insert predictions and derive a delay for each.

    A stop_time_update can carry arrival, departure, both or neither. Prefer
    arrival, fall back to departure.
    """
    feed_ts = _utc(msg.header.timestamp) if msg.header.timestamp else _utc(0)
    cols = [[] for _ in range(8)]

    for entity in msg.entity:
        if not entity.HasField("trip_update"):
            continue
        tu = entity.trip_update
        trip = tu.trip
        trip_id = trip.trip_id
        if not trip_id:
            continue
        start_date = _date(trip.start_date)
        for stu in tu.stop_time_update:
            if not stu.HasField("stop_sequence"):
                continue
            arrival = stu.arrival.time if stu.HasField("arrival") and stu.arrival.time else None
            departure = (
                stu.departure.time if stu.HasField("departure") and stu.departure.time else None
            )
            if arrival is None and departure is None:
                continue
            for i, value in enumerate([
                trip_id,
                stu.stop_sequence,
                stu.stop_id or None,
                trip.route_id or None,
                start_date,
                feed_ts,
                _utc(arrival) if arrival else None,
                _utc(departure) if departure else None,
            ]):
                cols[i].append(value)

    if not cols[0]:
        return 0

    # predicted minus scheduled, positive = late
    rows = await conn.fetch(
        """
        INSERT INTO trip_update
            (trip_id, stop_sequence, stop_id, route_id, start_date, ts,
             arrival_time, departure_time, delay_s)
        SELECT u.trip_id, u.stop_sequence, u.stop_id, u.route_id, u.start_date, u.ts,
               u.arrival_time, u.departure_time,
               CASE WHEN st.arrival_s IS NULL OR u.start_date IS NULL THEN NULL
                    ELSE round(extract(epoch FROM
                             COALESCE(u.arrival_time, u.departure_time)
                             - gtfs_ts(u.start_date,
                                       COALESCE(st.arrival_s, st.departure_s),
                                       $9::text)))::integer
               END
        FROM unnest($1::text[], $2::integer[], $3::text[], $4::text[], $5::date[],
                    $6::timestamptz[], $7::timestamptz[], $8::timestamptz[])
             AS u(trip_id, stop_sequence, stop_id, route_id, start_date, ts,
                  arrival_time, departure_time)
        LEFT JOIN stop_time st
               ON st.trip_id = u.trip_id AND st.stop_sequence = u.stop_sequence
        ON CONFLICT (trip_id, stop_sequence, ts) DO NOTHING
        RETURNING 1
        """,
        *cols,
        AGENCY_TZ,
    )
    return len(rows)


async def prune(conn):
    deleted = {}
    for table, hours in RETENTION.items():
        status = await conn.execute(
            f"DELETE FROM {table} WHERE ts < now() - ($1 || ' hours')::interval",
            str(hours),
        )
        deleted[table] = int(status.split()[-1])
    return deleted


HEARTBEAT_KEY = "poller_state"


def snapshot():
    def iso(v):
        return v.isoformat() if v else None

    return {
        "polls": STATE["polls"],
        "last_poll": iso(STATE["last_poll"]),
        "feed_timestamp": iso(STATE["feed_timestamp"]),
        "vehicles_seen": STATE["vehicles_seen"],
        "last_error": STATE["last_error"],
        "last_prune": iso(STATE["last_prune"]),
        "last_prune_error": STATE["last_prune_error"],
    }


# Written to the database rather than kept in memory so /health reports the
# real poller even when it runs as a separate process.
async def write_heartbeat(conn):
    await conn.execute(
        """
        INSERT INTO feed_meta (key, value) VALUES ($1, $2)
        ON CONFLICT (key) DO UPDATE SET value = excluded.value
        """,
        HEARTBEAT_KEY,
        json.dumps(snapshot()),
    )


async def read_heartbeat(conn):
    raw = await conn.fetchval("SELECT value FROM feed_meta WHERE key = $1", HEARTBEAT_KEY)
    return json.loads(raw) if raw else None


async def poll_once(client):
    vehicles_msg, updates_msg = await asyncio.gather(
        fetch(client, VEHICLE_POSITIONS_URL),
        fetch(client, TRIP_UPDATES_URL),
    )

    pool = db.pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # predictions first, so the delay pass can join against them in the
            # same poll rather than lagging a cycle behind
            updates = await ingest_trip_updates(conn, updates_msg)
            new_ids = await ingest_vehicles(conn, vehicles_msg)
            computed = await delay.compute(conn, new_ids) if new_ids else 0

    STATE.update(
        last_poll=dt.datetime.now(dt.timezone.utc),
        feed_timestamp=(
            _utc(vehicles_msg.header.timestamp)
            if vehicles_msg.header.timestamp
            else None
        ),
        positions_inserted=len(new_ids),
        trip_updates_inserted=updates,
        delays_computed=computed,
        last_error=None,
        polls=STATE["polls"] + 1,
    )
    return STATE


async def run_forever():
    prune_interval = dt.timedelta(hours=1)
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        while True:
            started = asyncio.get_running_loop().time()
            try:
                await poll_once(client)
                log.info(
                    "poll ok: %d vehicles, %d new positions, %d delays",
                    STATE["vehicles_seen"],
                    STATE["positions_inserted"],
                    STATE["delays_computed"],
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # keep polling across transient feed or network failures
                STATE["last_error"] = f"{type(exc).__name__}: {exc}"
                log.warning("poll failed: %s", STATE["last_error"])

            # wall clock, not a poll count: `polls` only advances on success
            now = dt.datetime.now(dt.timezone.utc)
            if STATE["last_prune"] is None or now - STATE["last_prune"] >= prune_interval:
                try:
                    async with db.pool().acquire() as conn:
                        deleted = await prune(conn)
                    STATE["last_prune"] = now
                    STATE["last_prune_error"] = None
                    log.info(
                        "pruned %s",
                        ", ".join(f"{t} {n:,}" for t, n in deleted.items()),
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    STATE["last_prune_error"] = f"{type(exc).__name__}: {exc}"
                    log.error("prune failed: %s", STATE["last_prune_error"])

            try:
                async with db.pool().acquire() as conn:
                    await write_heartbeat(conn)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("heartbeat failed: %s", exc)

            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1.0, POLL_INTERVAL_S - elapsed))
